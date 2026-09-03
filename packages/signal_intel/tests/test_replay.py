import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.signal_intel.replay.replay import (check_replay, issue_freshness,  # noqa: E402
                                           freshness_echoed, similarity)


def test_s04_similarity_high():
    import json
    s04 = json.loads((Path(__file__).resolve().parents[1] / "samples" / "S04.json")
                     .read_text(encoding="utf-8"))
    r = check_replay(s04["raw_text_or_transcript"], "EXE-001")
    assert r.max_similarity >= 0.92
    assert r.is_replay
    assert r.matched_utterance_id == "REPLAY-SRC-1"


def test_paraphrase_scores_low():
    para = ("Dear Rohit, Ananya here. Sundaram has imposed a customs charge of twenty-eight "
            "lakh on the Chennai shipment. It falls within the freight contract terms. "
            "Please NEFT it today so demurrage stops. Revert when done.")
    r = check_replay(para, "EXE-001")
    assert r.max_similarity < 0.92
    assert not r.is_replay


def test_freshness_token_issue():
    tok = issue_freshness("tx-1")
    assert tok["token"] and tok["ttl_seconds"] == 90 and "instruction" in tok


def test_freshness_echo_check():
    assert freshness_echoed("please repeat olive-4417 now", "olive-4417") is True
    assert freshness_echoed("I cannot do that", "olive-4417") is False
    assert freshness_echoed("anything", None) is None


def test_similarity_identical():
    assert similarity("a b c d e f g", "a b c d e f g") >= 0.99


def test_similarity_disjoint():
    # simhash of disjoint texts is still ~0.61 via 1 - hamming/64; the Jaccard floor is 0.
    # The distinguishing test is the paraphrase/S04 pair above; here we check the floor.
    assert similarity("alpha beta gamma delta", "one two three four") < 0.7
