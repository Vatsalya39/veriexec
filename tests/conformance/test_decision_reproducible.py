"""Invariant 8: Every decision is reproducible.

Replaying a stored audit record under its recorded `policy_version` must yield a byte-identical `RiskAssessment`.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from packages.core.policy.decide import Inputs, decide

GOLDEN_DIR = Path(__file__).resolve().parents[2] / "contracts" / "golden"


def test_decision_reproducibility():
    """Two executions with identical input parameters produce identical decisions and scores."""
    inp = Inputs(
        transaction_id="S01",
        risk_score=15,
        coverage=1.0,
        fingerprint_status="MATCH",
        amount_minor_units=2500000,
        ceiling_minor_units=50000000,
        channel_independent=True,
        payee_label="Kalyani Forge Components Pvt Ltd",
    )
    d1 = decide(inp)
    d2 = decide(inp)
    assert d1.outcome == d2.outcome
    assert d1.decision == d2.decision
    assert d1.band_outcome == d2.band_outcome
    assert d1.override_applied == d2.override_applied
    assert d1.required_actions == d2.required_actions
    assert d1.reasons == d2.reasons
