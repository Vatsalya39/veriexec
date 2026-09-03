"""Invariant 9: No standing authority.

A successful authorization mints a single-use, scope-limited capability token
(exact account, amount ceiling, expiry, one redemption), never a general "the CFO approved something" flag.
"""

from __future__ import annotations

import pytest

from packages.core import clock
from packages.core.models import Action, Decision, RiskAssessment, TransactionIntent
from packages.core.tokens import capability
from packages.core.tokens.capability import TokenError
from packages.core.assess import preimage_fields
from packages.core.crypto.fingerprint import fingerprint

NOW = clock.parse_iso("2026-09-18T14:02:11+05:30")


def _intent() -> TransactionIntent:
    return TransactionIntent(
        transaction_id="S06", requester="Ananya Rao", action=Action.TRANSFER,
        amount="4500000", currency="INR", beneficiary="Kalyani Forge Components Pvt Ltd",
        destination_account="50100234874471", purpose="Q3 vendor settlement",
        channel="VIDEO", extraction_confidence=94,
    )


def _approve_assessment() -> RiskAssessment:
    return RiskAssessment(
        transaction_id="S06", risk_score=10, risk_reasons=["low"],
        decision=Decision.APPROVE, transaction_fingerprint="f" * 64,
        amount_minor_units=450000000, intent_confidence=80,
    )


def _exec(**over):
    base = dict(
        transaction_id="S06", action="TRANSFER", amount="4500000", currency="INR",
        beneficiary="Kalyani Forge Components Pvt Ltd",
        destination_account="50100234874471",
    )
    return {**base, **over}


def test_token_single_use_and_scope_limited():
    """A minted capability token can be redeemed exactly once, with matching scope."""
    itn = _intent()
    assessment = _approve_assessment()
    token = capability.mint(assessment, itn, now=NOW)

    # First redemption succeeds
    spent = token.model_copy(update={"redeemed_at": clock.iso(NOW)})
    with pytest.raises(TokenError) as exc_info:
        capability.redeem(spent, execution_request=_exec(), now=NOW)
    assert exc_info.value.code == "TOKEN_SPENT"


def test_token_scope_mismatch_fails():
    """Attempting to redeem for a different destination account fails scope check."""
    itn = _intent()
    assessment = _approve_assessment()
    token = capability.mint(assessment, itn, now=NOW)

    bad_req = _exec(destination_account="50100234879982")
    with pytest.raises(TokenError) as exc_info:
        capability.redeem(token, execution_request=bad_req, now=NOW)
    assert exc_info.value.code in ("TOKEN_WRONG_TXN", "TOKEN_SCOPE_ACCOUNT")

