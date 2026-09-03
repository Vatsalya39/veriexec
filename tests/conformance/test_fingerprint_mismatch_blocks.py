"""Invariant 4: Fingerprint mismatch is fatal.

`fingerprint_status == "MISMATCH"` => `BLOCK`, unconditionally, regardless of `risk_score`.
Enforced in code, not via weights.
"""

from __future__ import annotations

import pytest

from packages.core.models import Decision
from packages.core.policy.decide import Inputs, decide


def test_fingerprint_mismatch_unconditionally_blocks():
    """At risk 0 or risk 99, MISMATCH always causes BLOCK with HO-1 override."""
    for risk in [0, 10, 50, 99]:
        inp = Inputs(
            transaction_id=f"T-INV4-{risk}",
            risk_score=risk,
            coverage=1.0,
            fingerprint_status="MISMATCH",
            amount_minor_units=100000,
            ceiling_minor_units=5000000,
            channel_independent=True,
            payee_label="Test Vendor",
        )
        outcome = decide(inp)
        assert outcome.decision is Decision.BLOCK, f"Risk {risk} with MISMATCH must produce BLOCK"
        assert outcome.override_applied == "HO-1"


def test_fingerprint_unverifiable_never_approves():
    """UNVERIFIABLE fingerprint cannot produce APPROVE."""
    inp = Inputs(
        transaction_id="T-INV4-UNVERIFIABLE",
        risk_score=10,
        coverage=1.0,
        fingerprint_status="UNVERIFIABLE",
        amount_minor_units=100000,
        ceiling_minor_units=5000000,
        channel_independent=True,
        payee_label="Test Vendor",
    )
    outcome = decide(inp)
    assert outcome.decision is not Decision.APPROVE
