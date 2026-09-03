"""Invariant 6: Verification must change channel.

A verification response arriving on the same channel, session or device as the
originating request is rejected, not merely penalised.
"""

from __future__ import annotations

import pytest

from packages.core.models import Decision
from packages.core.policy.decide import Inputs, decide


def test_same_channel_verification_fails_precondition():
    """When channel_independent is False and amount is above low-value exemption, APPROVE is blocked."""
    inp = Inputs(
        transaction_id="T-INV6",
        risk_score=10, # Very low risk
        coverage=1.0,
        fingerprint_status="MATCH",
        amount_minor_units=10_000_000, # ₹1,00,000 (above ₹50,000 exemption)
        ceiling_minor_units=50_000_000,
        channel_independent=False, # Same channel verification
        payee_label="Test Vendor",
    )
    outcome = decide(inp)
    assert outcome.decision is not Decision.APPROVE
    # Fails PC-4: channel independence required
    assert "PC-4" in outcome.failed_preconditions or outcome.decision in (Decision.CHALLENGE, Decision.BLOCK)
