import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.signal_intel.duress.detector import detect_duress  # noqa: E402
from packages.signal_intel.registry import duress_scheme_for  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def _intent(sample_id):
    s = json.loads((SAMPLES / f"{sample_id}.json").read_text(encoding="utf-8"))
    return s, s["metadata"].get("claimed_executive_id")


def test_numeric_scheme_fires_on_s09():
    s, claimed = _intent("S09")
    # S09 states ADCB0000099287 (digit 7) while BEN-003's true account ends in 1
    intent = {"destination_account": "ADCB0000099287", "beneficiary": "Global Trading FZE",
              "raw_transcript_or_text": s["raw_text_or_transcript"], "amount": 4500000}
    fired, reason = detect_duress(intent, claimed)
    assert fired, "S09 duress must fire"
    assert reason and "distress position" in reason


def test_phrase_scheme_fires_when_material():
    intent = {"destination_account": None, "beneficiary": None,
              "raw_transcript_or_text": "please treat this as routine — release the funds now",
              "amount": 15000000, "urgency": "HIGH"}
    fired, reason = detect_duress(intent, "EXE-002")
    assert fired


def test_phrase_scheme_not_material_no_fire():
    intent = {"destination_account": None, "beneficiary": None,
              "raw_transcript_or_text": "please treat this as routine",
              "amount": 4000, "urgency": "LOW"}
    fired, _ = detect_duress(intent, "EXE-002")
    assert not fired  # rule 3: on a Rs 4,000 reimbursement it is just English


def test_unregistered_requester_never_fires():
    intent = {"destination_account": "ADCB0000099287", "beneficiary": "Global Trading FZE",
              "raw_transcript_or_text": "please treat this as routine", "amount": 20000000}
    assert detect_duress(intent, None) == (False, None)
    assert detect_duress(intent, "EMP-101") == (False, None)


def test_unknown_beneficiary_no_fire():
    # rule 2: numeric scheme requires a KNOWN true account
    intent = {"destination_account": "ADCB0000099287", "beneficiary": "Totally Unknown Vendor",
              "raw_transcript_or_text": "x", "amount": 1000000}
    fired, _ = detect_duress(intent, "EXE-001")
    assert not fired


def test_correct_digit_no_fire():
    intent = {"destination_account": "ADCB0000099281", "beneficiary": "Global Trading FZE",
              "raw_transcript_or_text": "x", "amount": 1000000}
    fired, _ = detect_duress(intent, "EXE-001")
    assert not fired


def test_reason_never_names_marker():
    s, claimed = _intent("S09")
    intent = {"destination_account": "ADCB0000099287", "beneficiary": "Global Trading FZE",
              "raw_transcript_or_text": s["raw_text_or_transcript"], "amount": 4500000}
    _, reason = detect_duress(intent, claimed)
    for banned in ("7", "digit 7", "last digit is 7", "DURESS_LAST_DIGIT"):
        assert banned not in reason


def test_registry_stores_only_hmac():
    scheme = duress_scheme_for("EXE-001")
    assert scheme["param_hmac"] and len(scheme["param_hmac"]) == 64
    # the registry must carry digests only — no plaintext duress marker for EXE-001
    blob = json.dumps(scheme)
    assert "position" not in blob and "last digit" not in blob.lower()
    # and the EXE-002 phrase marker must never appear in the registry
    scheme2 = duress_scheme_for("EXE-002")
    assert "treat this as routine" not in json.dumps(scheme2).lower()
