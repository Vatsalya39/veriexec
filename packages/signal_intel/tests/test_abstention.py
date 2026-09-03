import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.signal_intel.detectors.harness import (DetectorReport,  # noqa: E402
                                               detector_disagreement, score_all,
                                               voice_abstain)


def _script(**kw):
    base = {"spectral_v1": 90, "prosody_v2": 90, "video_v1": None, "abstain": False,
            "abstain_reason": None, "clip_duration_s": 12.0, "snr_db": 30.0,
            "codec": "opus", "email_auth": None}
    base.update(kw)
    return base


def test_short_clip_abstains():
    reports = score_all(_script(spectral_v1=90, prosody_v2=90, clip_duration_s=3.2), "T1", "PHONE")
    assert all(r.abstain and r.score is None for r in reports)
    assert all(r.abstain_reason == "CLIP_TOO_SHORT" for r in reports)
    assert voice_abstain(reports)


def test_low_snr_abstains():
    reports = score_all(_script(snr_db=9.0), "T1", "PHONE")
    assert all(r.abstain and r.abstain_reason == "LOW_SNR" for r in reports)


def test_unknown_codec_abstains():
    reports = score_all(_script(codec="weird-v0"), "T1", "PHONE")
    assert all(r.abstain and r.abstain_reason == "UNKNOWN_CODEC" for r in reports)


def test_text_channel_no_modality():
    reports = score_all(_script(), "T1", "EMAIL")
    assert all(r.abstain and r.abstain_reason == "NO_MODALITY" for r in reports)


def test_never_default_substitution():
    # the entire point of Invariant 3: no code path anywhere substitutes a number
    reports = score_all(_script(spectral_v1=None, prosody_v2=None, abstain=True,
                                abstain_reason="CLIP_TOO_SHORT", clip_duration_s=2.0), "T", "PHONE")
    for r in reports:
        assert r.score is None and r.abstain


def test_disagreement_computed():
    reports = score_all(_script(spectral_v1=80, prosody_v2=40), "T1", "PHONE")
    d = detector_disagreement(reports)
    assert abs(d - 40) < 3


def test_disagreement_zero_when_abstain():
    reports = score_all(_script(spectral_v1=None, prosody_v2=None, clip_duration_s=2.0), "T", "PHONE")
    assert detector_disagreement(reports) == 0.0


def test_s15_end_to_end():
    import json
    sample = json.loads((Path(__file__).resolve().parents[1] / "samples" / "S15.json")
                        .read_text(encoding="utf-8"))
    reports = score_all(sample["detector_script"], "S15", sample["channel"])
    assert all(r.score is None and r.abstain for r in reports)
    assert voice_abstain(reports)
