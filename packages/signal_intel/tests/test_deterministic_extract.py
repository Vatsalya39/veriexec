import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.signal_intel.extract.deterministic import extract_deterministic  # noqa: E402


def _extract(text, claimed=None, channel="EMAIL"):
    return extract_deterministic(text, claimed_executive_id=claimed, channel=channel)


def test_action_transfer():
    r = _extract("Please transfer Rs 10,00,000 to Kalyani Forge Components Pvt Ltd")
    assert r.action == "TRANSFER"


def test_action_beneficiary_change():
    r = _extract("Vendor has revised NEFT details, kindly update the master")
    assert r.action == "BENEFICIARY_CHANGE"


def test_action_credential_reset():
    r = _extract("I am locked out, reset my MFA and password immediately")
    assert r.action == "CREDENTIAL_RESET"


def test_action_payment_limit_change():
    r = _extract("Raising my payment approval limit from Rs 50,00,000 to Rs 5 crore effective today")
    assert r.action == "PAYMENT_LIMIT_CHANGE"


def test_action_transfer_hinglish():
    r = _extract("pandrah lakh to Kalyani Forge pls, today itself", channel="CHAT")
    assert r.action == "TRANSFER"
    assert r.amount == 1500000


def test_spoken_account_ending():
    r = _extract("their account ending nine two eight one, forty-two lakh")
    assert r.destination_account == "9281"
    assert r.amount == 4200000


def test_beneficiary_fuzzy_match():
    r = _extract("Release Rs 10,00,000 to Kalyanl Forge Componets Pvt Ltd, HDFC0007777000111")
    # typosquat must NOT match BEN-001 (it matches BEN-004 at lower ratio, or stays unknown)
    assert r.beneficiary_matched_id in (None, "BEN-004")


def test_beneficiary_exact_match():
    r = _extract("pay Rs 6,40,000 to Kalyani Forge Components Pvt Ltd against PO 4471")
    assert r.beneficiary_matched_id == "BEN-001"


def test_beneficiary_unknown_note():
    r = _extract("Release Rs 95,00,000 to Global Trading FZE account ADCB0000099281")
    assert r.beneficiary is not None  # Global Trading IS in the master
    assert r.beneficiary_matched_id == "BEN-003"


def test_urgency_high():
    r = _extract("Urgent: transfer immediately, cannot wait, before market close")
    assert r.urgency == "HIGH"


def test_urgency_low_routine():
    r = _extract("Please process the routine settlement when convenient")
    assert r.urgency == "LOW"


def test_secrecy_flags_quoted():
    r = _extract("Keep this between us and do not tell anyone until the deal closes")
    assert len(r.secrecy_flags) >= 1
    assert any("between us" in f or "tell anyone" in f for f in r.secrecy_flags)


def test_requester_from_claimed_id():
    r = _extract("Please release the funds", claimed="EXE-001")
    assert "Ananya" in r.requester


def test_amount_none_on_vague():
    r = _extract("can you move some money to the vendor account today?")
    assert r.amount is None


def test_empty_text_never_raises():
    r = _extract("")
    assert r.action == "OTHER" and r.amount is None
