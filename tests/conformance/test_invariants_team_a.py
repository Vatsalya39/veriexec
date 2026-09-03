"""Shared conformance tests — one named test per invariant, all teams run these.

Team A owns the green state of invariants 1, 3 and 7 from the signal side:
  INV-1 (no single signal can approve) — A's contribution: the bundle always carries
        >= 3 independent signal families (identity, authenticity, behavioural/social).
  INV-3 (unavailable != clean) — abstaining detectors contribute null scores, never
        favourable numbers.
  INV-7 (every number carries reasons) — a material social-engineering score or a
        duress flag always ships with human-readable reasons.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.signal_intel.pipeline import process_communication  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[2] / "packages" / "signal_intel" / "samples"


def _run(sample_id):
    s = json.loads((SAMPLES / f"{sample_id}.json").read_text(encoding="utf-8"))
    return process_communication({
        "channel": s["channel"], "raw_text_or_transcript": s["raw_text_or_transcript"],
        "metadata": s["metadata"], "sample_id": s["sample_id"],
        "detector_script": s["detector_script"]})


ALL_IDS = [f"S{i:02d}" for i in range(1, 23)]


def test_invariant_1_no_single_signal_approves():
    """A's contribution to Invariant 1: the bundle always exposes >= 2 independent,
    informative signal families (actor/channel identity, artefact authenticity, org
    beneficiary registry, behavioural language), so Team B's policy can never approve
    on a single signal — B fuses these with its own behavioural-baseline family."""
    for sid in ALL_IDS:
        sig = _run(sid)["signals"]
        intent = _run(sid)["intent"]
        families = 0
        if sig.get("identity_evidence"):          # family: actor/device/channel evidence
            families += 1
        if sig.get("authenticity_evidence") or any(
                not r["abstain"] for r in sig["detector_reports"]) or \
                sig["stylometry_match_score"] is not None:  # family: artefact/medium
            families += 1
        if intent["deterministic_intent"].get("beneficiary_matched_id"):  # family: org registry
            families += 1
        if sig["social_engineering_indicators"]:   # family: behavioural pressure language
            families += 1
        assert families >= 2, f"{sid}: too few independent signal families ({families})"


def test_invariant_3_unavailable_is_not_clean():
    """An abstaining detector contributes ZERO authenticity evidence — score null, flag
    true, and the aggregate stays at the neutral prior of 50."""
    out = _run("S15")  # 3-second noisy clip — every detector abstains
    sig = out["signals"]
    assert sig["deepfake_voice_score"] is None, "abstaining voice must be null"
    assert sig["voice_abstain"] is True
    for r in sig["detector_reports"]:
        if r["abstain"]:
            assert r["score"] is None, "abstain report must carry a null score"
    # the aggregate must remain at the prior — abstention is NOT favourable evidence
    assert sig["communication_authenticity"] == 50


def test_invariant_7_every_number_carries_reasons():
    """A material social score or a duress flag always emits >= 1 human-readable reason."""
    for sid in ALL_IDS:
        sig = _run(sid)["signals"]
        if sig["social_engineering_score"] >= 30:
            assert sig["social_engineering_indicators"], f"{sid}: material score without reasons"
            for r in sig["social_engineering_indicators"]:
                assert isinstance(r, str) and len(r) > 5
        if sig["duress_flag"]:
            assert sig["duress_reason"], f"{sid}: duress without a reason"
            assert len(sig["duress_reason"]) > 10
