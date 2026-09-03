"""Unicode normalization for untrusted text (Team A trap #7: NFKC before every comparison).

Homoglyphs ('Kalyanl' with a Cyrillic 'а'), zero-width chars and bidi overrides are
normalized away BEFORE beneficiary matching and injection detection run.
"""
import re
import unicodedata

# Zero-width and bidi control characters that carry no visible content.
ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
BIDI = re.compile(r"[\u202a-\u202e\u2066-\u2069]")

# Latin lookalikes -> ASCII (confusables that matter for vendor-name matching).
_HOMOGLYPH_MAP = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "і": "i", "ѕ": "s", "ԁ": "d", "ɡ": "g", "Ɩ": "l", "Ａ": "A", "Ｂ": "B",
})


def normalize_text(text: str) -> str:
    """NFKC + strip zero-width/bidi + homoglyph fold + collapse whitespace."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = ZERO_WIDTH.sub("", t)
    t = BIDI.sub("", t)
    t = t.translate(_HOMOGLYPH_MAP)
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def ascii_fold(text: str) -> str:
    """Aggressive fold for comparison: lowercase ASCII, drop non-alphanumerics."""
    t = normalize_text(text).lower()
    return re.sub(r"[^a-z0-9]", "", t)
