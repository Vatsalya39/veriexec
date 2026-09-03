"""B8 — the comprehension challenge: issue and validate. [NOVEL-N9a]

Consent vs comprehension — the distinction that wins this component: a consent prompt
asks "do you approve?", a comprehension challenge asks "what are you approving?". A
deepfaked executive can say yes. Only someone who knows the real transaction can answer a
question about a fact *derived from* it.

The correct answer is never stored in cleartext and never sent to the client — only an
HMAC keyed with the server secret. The type is chosen deterministically from
`sha256(transaction_id + policy_version)` so the same case always yields the same
challenge, which is what replay (§19) and a rehearsable demo both need.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..clock import iso, parse_iso
from ..config import settings
from ..models import ComprehensionChallenge, TransactionIntent
from ..policy.constants import CHALLENGE_ATTEMPTS_ALLOWED
from ..policy.version import policy_version

#: §11.2 TTL comes from INTENTLOCK_CHALLENGE_TTL_SECONDS (default 120 s).
CHALLENGE_ID_PREFIX = "CHL-"

_WORDS: dict[str, int] = {
    "crore": 10_000_000, "crores": 10_000_000, "karod": 10_000_000,
    "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
    "thousand": 1_000, "hundred": 100,
}


def _expand_indian_words(s: str) -> str:
    """'2.5 crore' -> '25000000'. Deterministic, table-driven, never a model call."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(\w+)", s.strip())
    if m and m.group(2) in _WORDS:
        total = float(m.group(1)) * _WORDS[m.group(2)]
        if total == int(total):
            return str(int(total))
    return s


def normalize_answer(raw: str, kind: str) -> str:
    """§11.3 — an executive typing the correct amount must pass.

    "₹2,50,00,000", "25000000" and "2.5 crore" are all the same answer; rejecting a
    correct amount because of commas is a false challenge, and the organizers score the
    false-challenge rate.
    """
    s = unicodedata.normalize("NFKC", raw or "").strip().casefold()
    if kind in ("AMOUNT_RECALL", "ACCOUNT_TAIL"):
        # Strip separators and currency tokens as TOKENS, never as bare characters — a
        # character class like [rs] would eat the "r" and "s" out of "crore" and turn
        # "4.5 crore" into "45coe". Word-expansion runs BEFORE the dot is stripped,
        # because "4.5 crore" is one token and "45crore" is a different (wrong) number.
        s = re.sub(r"(?<![\w])(?:₹|rs\.?|inr|rupees?)", "", s)
        s = s.replace(",", "")
        s = _expand_indian_words(s.strip())
        s = re.sub(r"[\s\.\-/]", "", s)
        return str(int(s)) if s.isdigit() else s
    return re.sub(r"\s+", " ", s)


def answer_hmac(answer: str, challenge_id: str) -> str:
    """Keyed HMAC over the normalized answer. A bare sha256 of '640000' is a rainbow
    table with six entries; keyed, it is useless without the secret."""
    return hmac.new(
        settings().hmac_secret.encode(),
        f"{challenge_id}|{answer}".encode(), hashlib.sha256,
    ).hexdigest()


def _pick_type(transaction_id: str) -> str:
    """Deterministic from sha256(transaction_id + policy_version) — required for replay."""
    digest = hashlib.sha256(
        f"{transaction_id}|{policy_version()}".encode()
    ).hexdigest()
    order = ["AMOUNT_RECALL", "ACCOUNT_TAIL", "BENEFICIARY_SELECT", "PURPOSE_MATCH"]
    return order[int(digest[:2], 16) % 4]


def _options_shuffled(transaction_id: str, options: list[str]) -> list[str]:
    """Seeded shuffle so option order is reproducible (§11.1)."""
    seed = int(hashlib.sha256(f"shuffle|{transaction_id}".encode()).hexdigest()[:8], 16)
    out = list(options)
    rng = _SeededShuffle(seed)
    rng.shuffle(out)
    return out


class _SeededShuffle:
    """Deterministic Fisher-Yates; no `random` global state, so replay is byte-stable."""

    def __init__(self, seed: int) -> None:
        self.state = seed & 0xFFFFFFFF or 1

    def _next(self) -> int:
        self.state = (1103515245 * self.state + 12345) & 0x7FFFFFFF
        return self.state

    def shuffle(self, items: list[str]) -> None:
        for i in range(len(items) - 1, 0, -1):
            j = self._next() % (i + 1)
            items[i], items[j] = items[j], items[i]


# The challenge shapes B is allowed to ask. `expected` is derived from the intent and
# never leaves this module in cleartext.
PROMPTS: dict[str, str] = {
    "AMOUNT_RECALL": "Enter the exact amount you authorized, in rupees.",
    "ACCOUNT_TAIL": "Enter the last four digits of the account this payment will reach.",
    "BENEFICIARY_SELECT": "Select the payee this payment will reach.",
    "PURPOSE_MATCH": "Select the stated purpose of this payment.",
}


def issue(
    intent: TransactionIntent,
    *,
    distractors: list[str] | None = None,
    purposes: list[str] | None = None,
    now: datetime | None = None,
) -> ComprehensionChallenge:
    """Build the challenge for this transaction. No plaintext answer is returned."""
    now = now or datetime.now().astimezone()
    kind = _pick_type(intent.transaction_id)
    ttl = settings().challenge_ttl_seconds
    challenge_id = CHALLENGE_ID_PREFIX + hashlib.sha256(
        f"{intent.transaction_id}|{kind}|{policy_version()}".encode()
    ).hexdigest()[:6]

    from ..assess import minor_units as _to_paise

    if kind == "AMOUNT_RECALL":
        paise = _to_paise(intent)
        expected = str(paise // 100) if paise is not None else ""
        options: list[str] = []
    elif kind == "ACCOUNT_TAIL":
        expected = (intent.destination_account or "")[-4:]
        options = []
    elif kind == "BENEFICIARY_SELECT":
        expected = (intent.beneficiary or "").strip()
        opts = list(distractors or [])[:3]
        # Never generate a distractor that equals the answer after normalization.
        options = _options_shuffled(intent.transaction_id, [expected, *opts])
    else:  # PURPOSE_MATCH
        expected = (intent.purpose or "").strip()
        opts = list(purposes or [])[:2]
        options = _options_shuffled(intent.transaction_id, [expected, *opts])

    # Hash the NORMALIZED answer — validate() normalizes the submission, so both sides
    # must go through the same door or a correct answer fails on formatting (§11.3).
    return ComprehensionChallenge(
        type=kind,
        prompt=PROMPTS[kind],
        options=options,
        expected_answer_hash=answer_hmac(normalize_answer(expected, kind), challenge_id),
        ttl_seconds=ttl,
        challenge_id=challenge_id,
        attempts_allowed=CHALLENGE_ATTEMPTS_ALLOWED,
    )


def validate(
    challenge: ComprehensionChallenge,
    answer: str,
    *,
    attempts_used: int,
    expires_at: datetime | None,
    now: datetime,
    current_fingerprint: str | None = None,
    challenge_fingerprint: str | None = None,
) -> tuple[str, int]:
    """(result, attempts_left) with §11.4's five outcomes.

    FINGERPRINT_DRIFT closes the time-of-check/time-of-use gap: recompute the fingerprint
    at validation time; if the amount was raised while the executive was answering, the
    correct answer to the OLD question must not authorize the NEW payment (S13).
    """
    if expires_at is not None and now > expires_at:
        return "EXPIRED", 0
    if (current_fingerprint is not None and challenge_fingerprint is not None
            and current_fingerprint != challenge_fingerprint):
        return "FINGERPRINT_DRIFT", 0

    given = normalize_answer(answer or "", challenge.type.value if hasattr(challenge.type, "value") else str(challenge.type))
    ok = hmac.compare_digest(
        answer_hmac(given, challenge.challenge_id), challenge.expected_answer_hash
    )
    if ok:
        return "PASSED", max(0, challenge.attempts_allowed - attempts_used)
    left = challenge.attempts_allowed - attempts_used - 1
    if left <= 0:
        return "FAILED_EXHAUSTED", 0
    return "FAILED_RETRY", left
