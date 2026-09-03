"""Contract conformance: all 22 samples produce schema-valid intent + signals with
EVERY v1.1 extension key present (base AND extensions, §16)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jsonschema import validate  # noqa: E402

from packages.signal_intel.pipeline import process_communication  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
SAMPLES = Path(__file__).resolve().parents[1] / "samples"

INTENT_BASE = ["transaction_id", "requester", "action", "amount", "currency", "beneficiary",
               "destination_account", "purpose", "deadline", "urgency", "secrecy_flags",
               "channel", "raw_transcript_or_text", "timestamp"]
INTENT_EXT = ["extraction_confidence", "extraction_mode", "deterministic_intent",
              "extraction_divergence", "injection_flags", "amount_normalization",
              "language_detected", "origin_session_id", "sample_id"]

SIGNALS_BASE = ["transaction_id", "identity_confidence", "communication_authenticity",
                "deepfake_voice_score", "deepfake_video_score", "stylometry_match_score",
                "social_engineering_score", "social_engineering_indicators", "duress_flag",
                "duress_reason", "channel_timeline", "device_info"]
SIGNALS_EXT = ["detector_reports", "detector_disagreement", "voice_abstain", "video_abstain",
               "replay_similarity", "freshness_token_echoed", "channel_switch_flags",
               "origin_channel_id", "stylometry_features"]

ALL_IDS = [f"S{i:02d}" for i in range(1, 23)]


def _run(sample_id):
    s = json.loads((SAMPLES / f"{sample_id}.json").read_text(encoding="utf-8"))
    return process_communication({
        "channel": s["channel"], "raw_text_or_transcript": s["raw_text_or_transcript"],
        "metadata": s["metadata"], "sample_id": s["sample_id"],
        "detector_script": s["detector_script"]})


def test_all_22_present_and_schema_valid():
    for sid in ALL_IDS:
        out = _run(sid)
        assert set(INTENT_BASE + INTENT_EXT) <= set(out["intent"].keys()), f"{sid} intent keys"
        assert set(SIGNALS_BASE + SIGNALS_EXT) <= set(out["signals"].keys()), f"{sid} signals keys"


def test_intent_types():
    for sid in ALL_IDS:
        intent = _run(sid)["intent"]
        assert intent["action"] in ("TRANSFER", "CREDENTIAL_RESET", "BENEFICIARY_CHANGE",
                                    "PAYMENT_LIMIT_CHANGE", "OTHER")
        assert intent["urgency"] in ("LOW", "MEDIUM", "HIGH")
        assert intent["amount"] is None or isinstance(intent["amount"], (int, float))
        assert intent["channel"] in ("PHONE", "VIDEO", "EMAIL", "CHAT", "COLLAB_PLATFORM")
        assert isinstance(intent["secrecy_flags"], list)
        assert 0 <= intent["extraction_confidence"] <= 100
        assert intent["extraction_mode"] in ("llm", "deterministic", "hybrid", "failed")


def test_signal_ranges_and_directions():
    for sid in ALL_IDS:
        sig = _run(sid)["signals"]
        # direction comments (trap #1): these are 0-100
        for k in ("identity_confidence", "communication_authenticity", "social_engineering_score"):
            assert 0 <= sig[k] <= 100, f"{sid}.{k}={sig[k]}"
        for k in ("deepfake_voice_score", "deepfake_video_score", "stylometry_match_score"):
            v = sig[k]
            assert v is None or 0 <= v <= 100
        assert isinstance(sig["social_engineering_indicators"], list)
        assert isinstance(sig["channel_timeline"], list)
        assert isinstance(sig["origin_channel_id"], str) and len(sig["origin_channel_id"]) == 32


def test_every_score_carries_reasons():
    # Invariant 7: a populated material score must have reasons
    for sid in ALL_IDS:
        sig = _run(sid)["signals"]
        if sig["social_engineering_score"] >= 30:
            assert sig["social_engineering_indicators"], f"{sid}: score w/o reasons"
        if sig["duress_flag"]:
            assert sig["duress_reason"]


def test_determinism_two_runs_identical():
    for sid in ("S01", "S06", "S09", "S15", "S22"):
        a = _run(sid)
        b = _run(sid)
        # strip per-call uuids and seeded jitter (deterministic per transaction_id,
        # which differs per call); the FIELD VALUES must be identical across runs
        for o in (a, b):
            o["intent"]["transaction_id"] = ""
            o["intent"]["deterministic_intent"]["transaction_id"] = ""
            o["signals"]["transaction_id"] = ""
            for k in ("identity_evidence", "authenticity_evidence"):
                o["signals"].pop(k, None)
        # compare key fields explicitly
        for f in ("action", "amount", "beneficiary", "destination_account", "urgency"):
            assert a["intent"][f] == b["intent"][f], f"{sid}.{f} nondeterministic"
        for f in ("identity_confidence", "communication_authenticity",
                  "social_engineering_score", "duress_flag", "detector_disagreement",
                  "channel_switch_flags"):
            assert a["signals"][f] == b["signals"][f], f"{sid}.{f} nondeterministic"
