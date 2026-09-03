"""B10 — single-use, scope-limited capability tokens. [NOVEL-N11]

Approval does not grant *authority*, it grants **one specific capability, once**. There is
no standing permission anywhere in this system. An attacker who steals an approved token
has stolen the right to make exactly the payment that was already reviewed, to the
account already reviewed, before it expires — a materially different security posture
from a session cookie or an OAuth bearer.

The MAC is HMAC-SHA256 over the canonical form of every field except `mac` and
`redeemed_at`, keyed by `INTENTLOCK_HMAC_SECRET`. Verified with `hmac.compare_digest`,
never `==`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..assess import preimage_fields
from ..clock import iso, parse_iso
from ..config import settings
from ..crypto.canonical import canonical_bytes
from ..crypto.fingerprint import fingerprint
from ..models import Action, CapabilityToken, Decision, RiskAssessment, TokenScope, TransactionIntent
from ..policy.constants import TOKEN_TTL_SECONDS
from ..policy.version import policy_hash, policy_version


class TokenError(Exception):
    """A named redemption failure. Codes per §13's table."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _mac(token: CapabilityToken) -> str:
    """HMAC-SHA256 over the canonical serialization of everything except mac/redeemed_at."""
    secret = settings().hmac_secret.encode()
    return hmac.new(secret, canonical_bytes(token.mac_preimage()), hashlib.sha256).hexdigest()


def mint(
    assessment: RiskAssessment,
    intent: TransactionIntent,
    *,
    now: datetime | None = None,
    ttl_seconds: int = TOKEN_TTL_SECONDS,
) -> CapabilityToken:
    """Invariant 9: only the policy may mint, and only on APPROVE. Never on duress.

    `scope.max_amount` is the EXACT approved amount, not a headroom band — there is no
    business reason for a token to permit more than what was reviewed, and "a little
    headroom" is how ₹2.5 crore becomes ₹25 crore.
    """
    # Belt-and-braces alongside the model validator: minting is APPROVE-only, and a duress
    # escalation must never mint (it reads APPROVE on the wire by design).
    if assessment.decision is not Decision.APPROVE:
        raise TokenError("NOT_APPROVED", "Tokens are minted by APPROVE only.")
    if assessment.duress_escalation:
        raise TokenError("DURESS_NO_TOKEN", "A duress escalation never mints a capability.")
    if intent.action not in frozenset(a for a in Action if a is not Action.OTHER):
        raise TokenError("UNTOKENABLE_ACTION", f"Action {intent.action} carries no capability.")

    now = now or datetime.now().astimezone()
    from ..assess import minor_units as _to_paise
    amount = assessment.amount_minor_units if assessment.amount_minor_units is not None else _to_paise(intent)
    if amount is None:
        raise TokenError("NO_AMOUNT", "Cannot scope a token around an unreadable amount.")

    token = CapabilityToken(
        token_id="CAP-" + hashlib.sha256(
            f"token|{intent.transaction_id}|{policy_version()}".encode()
        ).hexdigest()[:12],
        transaction_id=intent.transaction_id,
        transaction_fingerprint=assessment.transaction_fingerprint,
        scope=TokenScope(
            action=intent.action,
            destination_account=intent.destination_account or "",
            max_amount=amount,
            currency=(intent.currency or "INR").upper(),
        ),
        issued_at=iso(now),
        expires_at=iso(now + timedelta(seconds=ttl_seconds)),
        single_use=True,
        redeemed_at=None,
        policy_version=policy_version(),
    )
    return token.model_copy(update={"mac": _mac(token)})


def verify_mac(token: CapabilityToken) -> bool:
    """A forged MAC is TOKEN_FORGED at redemption. `compare_digest`, never `==`."""
    return hmac.compare_digest(_mac(token), token.mac or "")


def redeem(
    token: CapabilityToken,
    *,
    execution_request: dict,
    now: datetime | None = None,
) -> tuple[CapabilityToken, str]:
    """Seven named checks, in §13's order. Returns the spent token and 'OK', or raises
    `TokenError` with the failure code. The caller is responsible for the atomic
    single-use update (the service wraps this in its store transaction)."""
    now = now or datetime.now().astimezone()

    # 1. MAC
    if not verify_mac(token):
        raise TokenError("TOKEN_FORGED", "The token's MAC does not verify.")
    # 2. Single use
    if token.redeemed_at is not None:
        raise TokenError("TOKEN_SPENT", f"Already redeemed at {token.redeemed_at}.")
    # 3. Expiry
    if parse_iso(token.expires_at) < now:
        raise TokenError("TOKEN_EXPIRED", f"Expired at {token.expires_at}.")
    # 4. Fingerprint binding — the execution request must hash to the bound fingerprint
    exec_fields = preimage_fields_from_request(execution_request)
    if fingerprint(exec_fields) != token.transaction_fingerprint:
        raise TokenError("TOKEN_WRONG_TXN",
                         "The execution request does not hash to the bound fingerprint.")
    # 5. Account scope — EXACT string match
    if (execution_request.get("destination_account") or "") != token.scope.destination_account:
        raise TokenError("TOKEN_SCOPE_ACCOUNT",
                         "Destination account is outside this token's scope.")
    # 6. Amount ceiling — the reviewed amount, exactly
    from ..assess import minor_units as _to_paise
    amount = int(execution_request.get("amount_minor_units") or 0) or None
    if amount is None:
        probe = TransactionIntent(
            transaction_id=str(execution_request.get("transaction_id") or token.transaction_id),
            amount=execution_request.get("amount"),
            currency=execution_request.get("currency"),
        )
        amount = _to_paise(probe)
    if amount is None or amount > token.scope.max_amount:
        raise TokenError("TOKEN_SCOPE_AMOUNT",
                         f"Amount exceeds the reviewed ceiling of {token.scope.max_amount}.")
    # 7. Action scope
    if str(execution_request.get("action") or "") != token.scope.action.value:
        raise TokenError("TOKEN_SCOPE_ACTION", "Action is outside this token's scope.")
    # 8. Policy freshness
    if token.policy_version != policy_version():
        raise TokenError(
            "TOKEN_STALE_POLICY",
            f"Issued under policy {token.policy_version}; current is {policy_version()}. "
            "Re-assess instead of redeeming.",
        )
    spent = token.model_copy(update={"redeemed_at": iso(now)})
    return spent, "OK"


def preimage_fields_from_request(execution_request: dict) -> dict:
    """The execution request -> the frozen pre-image fields, for the binding check."""
    from ..assess import minor_units as _to_paise
    probe = TransactionIntent(
        transaction_id=execution_request.get("transaction_id") or token_txn(execution_request),
        action=execution_request.get("action") or "OTHER",
        amount=execution_request.get("amount"),
        currency=execution_request.get("currency"),
        beneficiary=execution_request.get("beneficiary"),
        destination_account=execution_request.get("destination_account"),
        purpose=execution_request.get("purpose"),
        deadline=execution_request.get("deadline"),
    )
    return preimage_fields(
        probe,
        executive_id=execution_request.get("executive_id") or "",
        nonce=execution_request.get("nonce") or "",
        window_start=execution_request.get("validity_window_start_iso") or "",
        window_end=execution_request.get("validity_window_end_iso") or "",
    )


def token_txn(execution_request: dict) -> str:
    """Fallback id so a malformed request still hashes deterministically."""
    return str(execution_request.get("transaction_id") or "unknown-txn")
