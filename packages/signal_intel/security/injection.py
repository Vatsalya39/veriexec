"""Prompt-injection hardening of our own extractor [NOVEL-N14].

The transcript is UNTRUSTED DATA, treated like a SQL parameter — never an instruction.
Pipeline: normalize (NFKC, strip zero-width, resolve bidi) -> detect -> record ->
neutralize -> route (any flag => deterministic path is authoritative, never "llm").
"""
from __future__ import annotations

import base64
import re

from ..textnorm import normalize_text

# Canary token embedded in the system prompt; if it ever surfaces in LLM output,
# the model has been induced to echo instructions => INJECTION_PROMPT_LEAK.
CANARY = "ZXlJbk5vR2VvTGl2ZU5vdy0xMzM3"

# ---------------------------------------------------------------- detection families
_PATTERNS: list[tuple[str, re.Pattern]] = [
    # Instruction override
    ("INSTRUCTION_OVERRIDE", re.compile(
        r"ignore\s+(?:all\s+)?(?:previous|prior|above)\b|disregard\s+(?:all\s+)?(?:previous|prior|above)|"
        r"forget\s+your\s+(?:previous\s+)?instructions|new\s+instructions\s*:", re.IGNORECASE)),
    # Role hijack
    ("ROLE_HIJACK", re.compile(
        r"you\s+are\s+now|act\s+as\b|^\s*system\s*:|assistant\s*:|<\|im_start\|>|###\s*System", re.IGNORECASE | re.MULTILINE)),
    # Field coercion — attempts to set our outputs/scores
    ("FIELD_COERCION", re.compile(
        r"set\s+(?:urgency|social_engineering_score|duress_flag|decision|risk_score|identity_confidence|"
        r"communication_authenticity)\s*(?::|to|=)\s*\S+|duress_flag\s*(?::|to|=)\s*\S+|"
        r"mark\s+this\s+(?:transaction\s+)?as\s+(?:approved|low\s+risk|safe)|"
        r"output\s*\{|respond\s+with\s+only", re.IGNORECASE)),
    # Prompt exfiltration
    ("PROMPT_EXFILTRATION", re.compile(
        r"repeat\s+your\s+(?:system\s+)?prompt|what\s+are\s+your\s+instructions|print\s+everything\s+above",
        re.IGNORECASE)),
    # Structural escape — delimiter-looking artifacts / nested fenced JSON
    ("STRUCTURAL_ESCAPE", re.compile(
        r"<<<[/]?TRANSCRIPT|>>>|\{\s*\"decision\"\s*:")),
    # Encoding evasion
    ("BIDI_OVERRIDE", re.compile(r"[\u202a-\u202e\u2066-\u2069]")),
    ("ZERO_WIDTH_OBFUSCATION", re.compile(r"[\u200b\u200c\u200d\ufeff]")),
]

_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
_HEX_BLOB = re.compile(r"\b[0-9a-fA-F]{40,}\b")
_HOMOGLYPH_RUN = re.compile(r"[а-яА-Я]{2,}")

_REDACTED = "[REDACTED-INJECTION]"


def _decode_b64_candidates(text: str) -> list[str]:
    """Decode base64 blobs and scan the decoded content too (encoding-evasion family)."""
    decoded = []
    for m in _B64_BLOB.finditer(text):
        tok = m.group(0)
        try:
            blob = base64.b64decode(tok + "=" * (-len(tok) % 4), validate=False)
            s = blob.decode("utf-8", errors="ignore")
            if s.isprintable() and len(s) > 8:
                decoded.append(s)
        except Exception:
            continue
    return decoded


def detect_injection(text: str) -> dict:
    """Return {flags: [family names], spans: [matched texts], neutralized: str}.

    Detection runs on the ORIGINAL text (so zero-width/bidi obfuscation is visible)
    as well as on base64-decoded content.
    """
    flags: list[str] = []
    spans: list[str] = []
    if not text:
        return {"flags": [], "spans": [], "neutralized": ""}

    normalized = normalize_text(text)
    scan_targets: list[tuple[str, str]] = [(text, "raw"), (normalized, "normalized")]
    for decoded in _decode_b64_candidates(text):
        scan_targets.append((decoded, "b64"))

    neutralized = text
    for family, pattern in _PATTERNS:
        for source, _kind in scan_targets:
            for m in pattern.finditer(source):
                if family not in flags:
                    flags.append(family)
                if m.group(0).strip() and m.group(0) not in spans:
                    spans.append(m.group(0))

    if _B64_BLOB.search(text) and "ENCODING_EVASION_B64" not in flags:
        # Only flag blobs that decode into instruction-like content
        for decoded in _decode_b64_candidates(text):
            if any(p[1].search(decoded) for p in _PATTERNS[:4]):
                flags.append("ENCODING_EVASION_B64")
                break
    if _HEX_BLOB.search(text) and "ENCODING_EVASION_HEX" not in flags:
        flags.append("ENCODING_EVASION_HEX")
    if _HOMOGLYPH_RUN.search(text) and "HOMOGLYPH_RUN" not in flags:
        # Cyrillic runs inside otherwise-Latin business text
        if re.search(r"[a-zA-Z]", text):
            flags.append("HOMOGLYPH_RUN")

    # Neutralize: replace detected instruction spans in the text we pass downstream
    for span in spans:
        if span and span in neutralized:
            neutralized = neutralized.replace(span, _REDACTED)
    neutralized = _B64_BLOB.sub(_REDACTED, neutralized)

    return {"flags": flags, "spans": spans, "neutralized": neutralized}


def scan_for_canary_leak(output_text: str) -> bool:
    """True if the canary token surfaced in model output => INJECTION_PROMPT_LEAK."""
    return bool(output_text) and CANARY in output_text
