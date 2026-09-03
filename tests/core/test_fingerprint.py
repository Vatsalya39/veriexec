"""B1 conformance — the six tests named in 02_TEAM_B_RISK_FUSION_CORE.md §4.

If any of these go red the whole project is unsound: every authorization, every token
MAC and every golden fixture is bound to these bytes.
"""

from __future__ import annotations

import pytest

from packages.core.crypto import fingerprint as fp
from packages.core.crypto.canonical import NULL_SENTINEL, canonical_str, to_minor_units
from packages.core.crypto.fingerprint import FingerprintVerdict


def preimage(**over):
    base = {
        "transaction_id": "11111111-2222-3333-4444-555555555555",
        "executive_id": "EXE-001",
        "action": "TRANSFER",
        "amount_minor_units": 100_000_000,  # Rs 10,00,000 in paise
        "currency": "INR",
        "beneficiary_id_or_name": "BEN-001",
        "destination_account": "50100234874471",
        "purpose": "Q3 forging components invoice",
        "deadline_iso": "2026-09-03T18:00:00+05:30",
        "validity_window_start_iso": "2026-09-03T13:00:00+05:30",
        "validity_window_end_iso": "2026-09-03T13:15:00+05:30",
        "nonce": "n-0001",
    }
    base.update(over)
    return base


def test_fingerprint_stable_across_key_order():
    a = preimage()
    b = {k: a[k] for k in reversed(list(a))}
    assert list(a) != list(b)
    assert fp.fingerprint(a) == fp.fingerprint(b)


def test_fingerprint_nfc_equivalence():
    """"Kalyani" typed on macOS (NFD) and on Windows (NFC) are the same payee."""
    nfc = "Kalyanī Forge"          # ī as one codepoint
    nfd = "Kalyanī Forge"         # i + combining macron
    assert nfc != nfd
    assert fp.fingerprint(preimage(beneficiary_id_or_name=nfc)) == fp.fingerprint(
        preimage(beneficiary_id_or_name=nfd)
    )


def test_one_paisa_changes_hash():
    a = fp.fingerprint(preimage(amount_minor_units=100_000_000))
    b = fp.fingerprint(preimage(amount_minor_units=100_000_001))
    assert a != b


def test_null_vs_missing_differ():
    """Present-and-null must not hash like absent — otherwise dropping a field is free."""
    with_null = fp.fingerprint(preimage(purpose=None))
    with_empty = fp.fingerprint(preimage(purpose=""))
    with_value = fp.fingerprint(preimage(purpose="x"))
    assert len({with_null, with_empty, with_value}) == 3
    # The sentinel travels as JSON-escaped U+0000, which is what Team C's mirror must
    # also emit. Assert the wire form, not the Python char.
    assert canonical_str({"purpose": None}) == '{"purpose":"\\u0000"}'
    assert NULL_SENTINEL == chr(0)

    missing = preimage()
    del missing["purpose"]
    with pytest.raises(KeyError) as ei:
        fp.fingerprint(missing)
    assert "purpose" in str(ei.value)


def test_no_float_reaches_canonical_form():
    with pytest.raises(TypeError):
        fp.fingerprint(preimage(amount_minor_units=2.5))
    with pytest.raises(TypeError):
        canonical_str({"amount": 0.1 + 0.2})


def test_unverifiable_never_approves():
    """No presented fingerprint is UNVERIFIABLE, not MATCH. PC-1 then blocks APPROVE."""
    verdict, ds = fp.verify(None, preimage(), preimage())
    assert verdict is FingerprintVerdict.UNVERIFIABLE
    assert ds == []
    assert verdict.wire() == "NOT_YET_VERIFIED"

    # And a hash we cannot explain is unverifiable too, never a silent pass.
    verdict2, _ = fp.verify("deadbeef" * 8, preimage(), None)
    assert verdict2 is FingerprintVerdict.UNVERIFIABLE


# --- delta / severity behaviour that HO-1 depends on -------------------------------

def test_tampered_account_is_a_critical_delta():
    approved = preimage()
    executed = preimage(destination_account="30070019929982", amount_minor_units=1_000_000_000)
    verdict, ds = fp.verify(fp.fingerprint(approved), executed, approved)
    assert verdict is FingerprintVerdict.MISMATCH
    assert fp.has_critical(ds)
    fields = [d.field for d in ds]
    assert fields[:2] == ["amount_minor_units", "destination_account"]  # critical first


def test_account_numbers_are_redacted_in_deltas():
    approved = preimage()
    executed = preimage(destination_account="30070019929982")
    _, ds = fp.verify(fp.fingerprint(approved), executed, approved)
    d = next(x for x in ds if x.field == "destination_account")
    assert d.expected.endswith("4471") and d.presented.endswith("9982")
    assert "50100234874471" not in d.expected
    assert "30070019929982" not in d.presented


def test_cosmetic_only_drift_is_mismatch_without_critical():
    approved = preimage()
    executed = preimage(purpose="Q3 forging components invoice (revised wording)")
    verdict, ds = fp.verify(fp.fingerprint(approved), executed, approved)
    assert verdict is FingerprintVerdict.MISMATCH
    assert not fp.has_critical(ds)  # -> CHALLENGE via PC-1, not BLOCK via HO-1


def test_forged_fingerprint_with_identical_preimage_is_critical():
    approved = preimage()
    verdict, ds = fp.verify("0" * 64, approved, approved)
    assert verdict is FingerprintVerdict.MISMATCH
    assert fp.has_critical(ds)
    assert ds[0].field == "transaction_fingerprint"


def test_fingerprint_fields_are_frozen():
    """Guard against Team B §26 trap #1: quietly editing FINGERPRINT_FIELDS."""
    assert fp.FINGERPRINT_FIELDS == (
        "transaction_id", "executive_id", "action", "amount_minor_units", "currency",
        "beneficiary_id_or_name", "destination_account", "purpose", "deadline_iso",
        "validity_window_start_iso", "validity_window_end_iso", "nonce",
    )
    assert set(fp.FIELD_SEVERITY) >= set(fp.FINGERPRINT_FIELDS)


def test_money_helper_refuses_lossy_input():
    assert to_minor_units(1_500_000) == 150_000_000
    assert to_minor_units("15,00,000") == 150_000_000
    assert to_minor_units("2.50") == 250
    with pytest.raises(TypeError):
        to_minor_units(2.5)
    with pytest.raises(TypeError):
        to_minor_units("1.005")
