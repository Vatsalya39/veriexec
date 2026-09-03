"""Invariant 5: Duress is silent.

`duress_flag == true` => `duress_escalation == true`, a normal-looking flow for the actor,
and a separate alert to the security view. Never a visible "duress detected" banner to the requester.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from packages.core.models import Decision
from packages.core.policy.decide import Inputs, Outcome, decide
from packages.signal_intel.duress.detector import detect_duress

SAMPLES = Path(__file__).resolve().parents[2] / "packages" / "signal_intel" / "samples"


def test_duress_flag_sets_silent_escalation():
    """When duress is flagged, the decision is SILENT_ESCALATION without leaking details."""
    inp = Inputs(
        transaction_id="S09",
        risk_score=35,
        coverage=1.0,
        fingerprint_status="MATCH",
        duress_suspected=True,
        amount_minor_units=450000000,
        ceiling_minor_units=500000000,
        channel_independent=True,
        payee_label="Global Trading FZE",
    )
    outcome = decide(inp)
    assert outcome.duress_escalation is True
    assert outcome.outcome is Outcome.SILENT_ESCALATION


def test_duress_reason_never_names_marker_or_scheme():
    """Duress reason contains only categorical strings, never plaintext markers or schemes."""
    sample_file = SAMPLES / "S09.json"
    if sample_file.exists():
        s = json.loads(sample_file.read_text(encoding="utf-8"))
        intent = {
            "destination_account": "ADCB0000099287",
            "beneficiary": "Global Trading FZE",
            "raw_transcript_or_text": s["raw_text_or_transcript"],
            "amount": 4500000,
        }
        fired, reason = detect_duress(intent, "EXE-001")
        assert fired is True
        assert "7" not in reason
        assert "marker" not in reason.lower()
        assert "scheme" not in reason.lower()
