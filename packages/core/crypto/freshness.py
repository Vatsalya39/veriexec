"""B2 — nonce, validity window, replay and freshness binding. [NOVEL-N18b]

Team A issues a freshness token; B binds it. A token that is valid but was issued for a
*different transaction* is worthless, and most implementations get this wrong by checking
only the expiry. Four checks, all four required, each with its own named failure.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime

from ..clock import iso, parse_iso, seconds_between
from ..config import settings
from ..policy.constants import AUTH_WINDOW_MINUTES, FRESHNESS_TTL_SECONDS, VALIDITY_WINDOW_MINUTES

FRESHNESS_FAILURES: dict[str, str] = {
    "FRESH_EXPIRED":   "Freshness token expired at {expires_at}; now is {now}",
    "FRESH_WRONG_TXN": "Token was issued for a different transaction fingerprint",
    "FRESH_REPLAYED":  "Nonce {nonce} was already consumed at {consumed_at}",
    "FRESH_WINDOW":    "Request falls outside the intent validity window",
    "FRESH_NOT_ECHOED": "A freshness token was issued but the response did not echo it",
}


class NonceStore:
    """In-memory consumed-nonce registry for the single-process hackathon service.

    # MOCKED — replace with the SQLite `consumed_nonces` table behind the same interface
    in production. Consumption must be atomic with the decision write there.
    """

    def __init__(self) -> None:
        self._consumed: dict[str, tuple[str, str]] = {}   # nonce -> (consumed_at, txn_id)

    def consume(self, nonce: str, now_iso: str, transaction_id: str) -> bool:
        """Atomic single-use consumption: True if this call spent it, False if already spent."""
        if nonce in self._consumed:
            return False
        self._consumed[nonce] = (now_iso, transaction_id)
        return True

    def consumed_at(self, nonce: str) -> str | None:
        return self._consumed.get(nonce, (None, None))[0]

    def reset(self) -> None:
        self._consumed.clear()


#: Process-wide nonce store. The service is single-process by design (bound to 127.0.0.1).
NONCES = NonceStore()


def issue_nonce(transaction_id: str, now: datetime) -> str:
    """Deterministic-per-transaction nonce so replay tests are stable under INTENTLOCK_SEED."""
    secret = settings().hmac_secret.encode()
    return hmac.new(secret, f"nonce|{transaction_id}".encode(), hashlib.sha256).hexdigest()[:16]


def mint_window(now: datetime) -> dict[str, str]:
    """The default 15-minute validity window, as the two ISO strings the fingerprint binds."""
    return {
        "start_iso": iso(now),
        "end_iso": iso(now + _minutes(AUTH_WINDOW_MINUTES)),
    }


def _minutes(n: float):
    from datetime import timedelta
    return timedelta(minutes=n)


def replay_risk(
    *,
    nonce: str,
    nonce_replayed: bool,
    token_bound_fingerprint: str | None,
    current_fingerprint: str,
    freshness_expires_at: str | None,
    freshness_bound_fingerprint: str | None,
    window_start_iso: str | None,
    window_end_iso: str | None,
    near_duplicate_similarity: float | None,
    now: datetime,
) -> tuple[float, list[str]]:
    """§5's `replay_risk` ladder (0-100) plus the named failures that fired."""
    risk = 0.0
    failures: list[str] = []

    if nonce_replayed:
        consumed = NONCES.consumed_at(nonce) or "an earlier point in this window"
        risk = max(risk, 100.0)
        failures.append("FRESH_REPLAYED")
    if token_bound_fingerprint and token_bound_fingerprint != current_fingerprint:
        risk = max(risk, 95.0)
        failures.append("FRESH_WRONG_TXN")
    if freshness_expires_at:
        try:
            exp = parse_iso(freshness_expires_at)
            overdue = seconds_between(exp, now)
            if overdue > 0:
                risk = max(risk, 70.0 if overdue > 600 else 45.0)
                failures.append("FRESH_EXPIRED")
        except ValueError:
            failures.append("FRESH_EXPIRED")
    if window_start_iso and window_end_iso:
        try:
            if not (parse_iso(window_start_iso) <= now <= parse_iso(window_end_iso)):
                risk = max(risk, 55.0)
                failures.append("FRESH_WINDOW")
        except ValueError:
            risk = max(risk, 55.0)
            failures.append("FRESH_WINDOW")
    if near_duplicate_similarity is not None and float(near_duplicate_similarity) >= 0.92:
        risk = max(risk, 80.0)
    return round(risk, 1), failures


def freshness_failure(not_echoed: bool) -> str | None:
    """A's `freshness_token_echoed: false` becomes a named B failure (§ B2/B10 binding)."""
    return "FRESH_NOT_ECHOED" if not_echoed else None
