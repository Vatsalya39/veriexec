"""Duress / coercion detector [NOVEL-N1a]. The most human idea in the project.

Detection compares HMAC digests — the plaintext marker is NEVER stored in the repo
(`contracts/duress.json` holds only hmac_sha256 digests). `duress_reason` names the
CATEGORY of evidence, never the scheme, the marker or the position (it lands in the
audit log, and the audit log is a disclosure target).

Anti-false-positive rules (mandatory):
 1. unregistered requester => False, always.
 2. numeric scheme requires a KNOWN true account to compare against.
 3. phrase scheme requires material risk (amount >= Rs 10,00,000 OR urgency == HIGH).
 4. duress_reason never names the marker.
"""
from __future__ import annotations

import hashlib
import hmac
import re

from ..config import CONFIG
from ..registry import account_for_beneficiary_name, duress_scheme_for

# Materiality gate for the phrase scheme (rule 3)
PHRASE_SCHEME_MIN_AMOUNT = 10_00_000


def _hmac_hex(value: str) -> str:
    return hmac.new(CONFIG.hmac_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def _hmac_eq(value: str, expected_hex: str) -> bool:
    """Constant-time comparison of a candidate plaintext's digest against the registry digest."""
    return hmac.compare_digest(_hmac_hex(value), expected_hex)


def _candidate_phrases(text: str) -> list[str]:
    """Normalized candidate substrings whose digest might match a registered marker.

    The registry only stores the digest, so we cannot simply search for the plaintext.
    We scan for hedging-style phrases (the design space of an innocuous marker) and
    digest each; a hit means the phrase is registered for this executive.
    """
    candidates = set()
    text_l = text.lower()
    # n-gram window scan over the sentence containing 'routine'-class hedges, plus
    # every 3-6 word window in the message (cheap for 60-160 word transcripts)
    words = text_l.split()
    for n in (3, 4, 5, 6):
        for i in range(len(words) - n + 1):
            candidates.add(" ".join(words[i:i + n]))
    # also whole sentences (period-stripped)
    for sent in re.split(r"[.!?]+", text_l):
        s = sent.strip()
        if s:
            candidates.add(s)
    return list(candidates)


def detect_duress(intent: dict, claimed_executive_id: str | None) -> tuple[bool, str | None]:
    """Returns (duress_flag, duress_reason). duress_reason names the category, never the marker."""
    if not claimed_executive_id:
        return False, None
    scheme = duress_scheme_for(claimed_executive_id)
    if scheme is None:  # rule 1: unregistered requester => never fire
        return False, None

    raw_text = intent.get("raw_transcript_or_text") or ""

    if scheme["kind"] == "numeric_substitution":
        stated = (intent.get("destination_account") or "")[-1:]
        beneficiary = intent.get("beneficiary")
        true_account = None
        if beneficiary:
            true_account = account_for_beneficiary_name(beneficiary)
        if not true_account:
            # rule 2: unknown beneficiary => do not fire (it already scores high on its own path)
            return False, None
        truth = true_account[-1:]
        # The pre-agreed distress position: digest of the stated digit matches the registry.
        if stated and truth and stated.isdigit() and stated != truth:
            if _hmac_eq(stated, scheme["param_hmac"]):
                return True, ("Stated account differs from the registered account in the "
                              "pre-agreed distress position")
        return False, None

    if scheme["kind"] == "innocuous_token_phrase":
        # rule 3: material risk required — an urgent or high-value request only
        amount = intent.get("amount")
        urgency = intent.get("urgency")
        material = (amount is not None and amount >= PHRASE_SCHEME_MIN_AMOUNT) or urgency == "HIGH"
        if not material:
            return False, None
        for candidate in _candidate_phrases(raw_text):
            if _hmac_eq(candidate, scheme["param_hmac"]):
                return True, ("Pre-registered distress phrase present in an urgent "
                              "high-value request")
        return False, None

    return False, None
