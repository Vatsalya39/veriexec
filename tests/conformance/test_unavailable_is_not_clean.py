"""Invariant 3: Unavailable != clean.

A detector that abstains (short utterance, low SNR, unknown codec, missing modality)
contributes ZERO authenticity evidence. Missing evidence may never be scored as favourable evidence.

`fuse()` has always handled abstention correctly. The gap this file now also closes is one
level earlier: the *producers*. `semantic_drift` and `device_channel` each published a real
`0.0` when they had nothing to measure — a self-comparison with no pre-image, and a channel
verdict of `PENDING` before any verification had happened. Between them that spent 0.25 of
the fusion weight certifying innocence on no evidence and, because neither ever abstained,
held coverage at 1.00 so the uncertainty penalty never applied. An invariant proven only
about the machinery and not about its inputs is not enforced.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.core.assess import assess
from packages.core.models import AssessInput
from packages.core.scoring.fusion import fuse, DimensionScore
from packages.signal_intel.pipeline import process_communication


def test_abstained_score_increases_risk_via_uncertainty():
    """Null score reduces coverage and incurs an uncertainty penalty compared to favourable score."""
    # Favourable scores across all 7 dimensions
    all_favourable = [
        DimensionScore("beneficiary", 10.0, "Low payee risk", "EV-1"),
        DimensionScore("behavioural", 10.0, "Normal baseline", "EV-2"),
        DimensionScore("semantic_drift", 10.0, "No drift", "EV-3"),
        DimensionScore("device_channel", 10.0, "Independent channel", "EV-4"),
        DimensionScore("social_engineering", 10.0, "No pressure", "EV-5"),
        DimensionScore("communication_authenticity", 10.0, "Voice genuine", "EV-6"),
        DimensionScore("identity_confidence", 10.0, "MFA matched", "EV-7"),
    ]
    fused_clean = fuse({d.dimension: d for d in all_favourable})
    assert fused_clean.coverage == 1.0
    assert fused_clean.uncertainty_points == 0.0

    # With communication_authenticity and identity_confidence abstained (None)
    abstained = [
        DimensionScore("beneficiary", 10.0, "Low payee risk", "EV-1"),
        DimensionScore("behavioural", 10.0, "Normal baseline", "EV-2"),
        DimensionScore("semantic_drift", 10.0, "No drift", "EV-3"),
        DimensionScore("device_channel", 10.0, "Independent channel", "EV-4"),
        DimensionScore("social_engineering", 10.0, "No pressure", "EV-5"),
        DimensionScore("communication_authenticity", None, abstain_reason="No audio/video data"),
        DimensionScore("identity_confidence", None, abstain_reason="Device unknown"),
    ]
    fused_abstained = fuse({d.dimension: d for d in abstained})
    assert fused_abstained.coverage < 1.0
    assert fused_abstained.uncertainty_points > 0.0
    assert fused_abstained.score is not None and fused_clean.score is not None
    assert fused_abstained.score > fused_clean.score, "Abstaining must yield higher risk than favourable evidence"


# ------------------------------------------------- the same invariant, at the producers

SAMPLES = Path(__file__).resolve().parents[2] / "packages" / "signal_intel" / "samples"


def _first_pass(sample_id: str):
    """A -> B exactly as the pipeline runs it, with no second pass and no world state."""
    d = json.loads((SAMPLES / f"{sample_id}.json").read_text(encoding="utf-8"))
    out = process_communication({
        "channel": d["channel"], "raw_text_or_transcript": d["raw_text_or_transcript"],
        "metadata": d["metadata"], "sample_id": sample_id,
        "detector_script": d.get("detector_script") or {},
        "freshness_token": None, "freshness_echoed": d.get("freshness_echoed"),
    })
    return assess(AssessInput.model_validate(
        {"intent": out["intent"], "signals": out["signals"], "scenario_id": sample_id}))


ALL_SAMPLES = sorted(p.stem for p in SAMPLES.glob("S*.json"))


@pytest.mark.parametrize("sample_id", ALL_SAMPLES)
def test_no_dimension_scores_zero_without_evidence(sample_id):
    """A populated `0.0` is a claim of innocence, and a claim needs evidence.

    §10.3 already forbids a reason string with no `evidence_ref`. This is the same rule about
    the number: a dimension that reports the lowest possible risk must be able to say what it
    looked at. `semantic_drift` and `device_channel` both failed it on every sample.
    """
    a = _first_pass(sample_id)
    naked = [r.factor for r in a.contribution_table
             if not r.abstained and r.factor != "uncertainty"
             and float(r.raw_score) == 0.0 and not r.evidence]
    assert not naked, f"{sample_id}: scored 0.0 with no evidence: {naked}"


@pytest.mark.parametrize("sample_id", ALL_SAMPLES)
def test_a_first_pass_never_claims_full_coverage(sample_id):
    """Nothing has been verified yet, so the uncertainty penalty must be doing work.

    Before C collects a human response there is no approved pre-image and no verification
    channel, so `semantic_drift` and `device_channel` cannot be measured. Coverage of 1.00
    on that input meant the 0.30 penalty was multiplied by zero on all 22 scenarios — the
    arithmetic through which "we have not checked" and "we checked and it is fine" became
    the same number.
    """
    a = _first_pass(sample_id)
    assert a.coverage < 1.0, f"{sample_id}: claims full coverage before anything was verified"
    assert any(r.factor == "uncertainty" and r.points > 0 for r in a.contribution_table)
    assert all(r.abstain_reason for r in a.contribution_table if r.abstained)

    # Both dimensions abstain on a first pass *unless* they hold a measurement that does not
    # depend on a second pass. For `device_channel` that is A's `channel_switch_flags` (12
    # points each); for `semantic_drift` it is §8's 40 for an amount the request never stated
    # in a readable form — a fact about the request itself, not a disagreement between two
    # statements, so it survives with no pre-image at all (S17, S22). Either way, neither
    # dimension may publish a 0.
    rows = {r.factor: r for r in a.contribution_table}
    dev = rows["device_channel"]
    if dev.abstained:
        assert not dev.evidence
    else:
        assert dev.evidence and dev.raw_score > 0

    drift = rows["semantic_drift"]
    if a.amount_minor_units is None:
        assert not drift.abstained and drift.raw_score == 40.0
    else:
        assert drift.abstained
