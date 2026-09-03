import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.signal_intel.stylometry.twin import score_stylometry  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
CORPUS = SAMPLES / "genuine_corpus"


def _genuine(exec_id, idx=0):
    lines = (CORPUS / f"{exec_id}.jsonl").read_text(encoding="utf-8").splitlines()
    return json.loads(lines[idx])["body"]


import json  # noqa: E402


def test_s05_scores_low_against_exe002():
    s05 = json.loads((SAMPLES / "S05.json").read_text(encoding="utf-8"))
    body = s05["raw_text_or_transcript"].split("\n\n", 1)[1]
    r = score_stylometry(body, "EXE-002", "EMAIL")
    assert r.score is not None and r.score < 40, f"S05 scored {r.score}"  # brief threshold
    assert len(r.features["top_deviations"]) >= 1


def test_genuine_corpus_scores_high():
    for exec_id in ("EXE-001", "EXE-002"):
        scores = []
        for i in range(8):
            r = score_stylometry(_genuine(exec_id, i), exec_id, "EMAIL")
            scores.append(r.score)
        # brief: a genuine corpus message scores > 75
        assert max(scores) > 75, f"{exec_id} max {max(scores)}"


def test_short_message_returns_null():
    r = score_stylometry("pay now please", "EXE-001", "EMAIL")
    assert r.score is None


def test_twelve_word_message_returns_null():
    # brief: a 12-word message returns null — under the 25-word guard
    r = score_stylometry("Please process this payment today itself as discussed on our call",
                         "EXE-001", "EMAIL")
    assert r.score is None


def test_phone_returns_null():
    r = score_stylometry("Rohit it's Ananya, please release the funds immediately as discussed "
                         "on our call earlier today regarding the quarterly vendor payments",
                         "EXE-001", "PHONE")
    assert r.score is None


def test_top_deviations_plain_english():
    s05 = json.loads((SAMPLES / "S05.json").read_text(encoding="utf-8"))
    body = s05["raw_text_or_transcript"].split("\n\n", 1)[1]
    r = score_stylometry(body, "EXE-002", "EMAIL")
    for dev in r.features["top_deviations"]:
        assert len(dev) < 90  # plain English, no feature names
