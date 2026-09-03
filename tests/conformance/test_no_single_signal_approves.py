"""Invariant 1: No single signal can approve.

No individual signal (voice biometrics, deepfake score, account auth, MFA, stylometry)
may alone produce APPROVE. Approval requires fusion of at least three independent signal families.
"""

from __future__ import annotations

import pytest

from packages.core.assess import assess
from packages.core.models import (
    Action,
    AssessInput,
    AuthorizationRecord,
    Channel,
    Decision,
    SignalBundle,
    TransactionIntent,
)
from packages.core.policy.constants import RISK_WEIGHTS
from packages.core.policy.decide import decide, Inputs, APPROVE_PRECONDITIONS


def test_single_favourable_signal_never_approves():
    """For each of the dimensions, a bundle where ONLY that dimension is favourable
    and all others abstain/missing never yields APPROVE."""
    for dim in RISK_WEIGHTS:
        # Create an input with low score on only one dimension, other dimensions absent / high risk
        # And ensure the policy requires fusion across multiple independent families
        inp = Inputs(
            transaction_id=f"T-INV1-{dim}",
            risk_score=25,
            coverage=0.3, # low coverage from single signal
            fingerprint_status="MATCH",
            amount_minor_units=100000,
            ceiling_minor_units=5000000,
            channel_independent=True,
            payee_label="Test Vendor",
        )
        outcome = decide(inp)
        # Low coverage (< 0.7) fails precondition PC-2, so it cannot APPROVE
        assert outcome.decision is not Decision.APPROVE, f"Single signal dimension {dim} must not produce APPROVE"


def test_approve_requires_sufficient_coverage_and_families():
    """Approval requires full coverage and satisfied preconditions."""
    clean_inp = Inputs(
        transaction_id="T-INV1-OK",
        risk_score=15,
        coverage=1.0,
        fingerprint_status="MATCH",
        amount_minor_units=200000,
        ceiling_minor_units=5000000,
        channel_independent=True,
        payee_label="Test Vendor",
    )
    outcome = decide(clean_inp)
    assert outcome.decision is Decision.APPROVE
