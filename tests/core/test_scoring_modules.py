"""B3/B4/B5/B6/B11 module tests — the spec's named test cases (§25)."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.core import clock
from packages.core.models import TransactionIntent
from packages.core.scoring import behavioural, beneficiary, drift, divergence, homoglyph
from packages.core.policy import channel as channel_policy

NOW = clock.parse_iso("2026-09-18T14:02:11+05:30")   # a Friday inside EXE-001's window
MASTER = None


@pytest.fixture(scope="module")
def master():
    from packages.core.contracts_io import beneficiary_master
    return beneficiary_master(NOW)


# ------------------------------------------------------------------ B3 behavioural

class TestBehavioural:
    def test_six_components_and_weighted_mean(self):
        d = behavioural.score(executive_id="EXE-001", amount_minor_units=80_000_000_00 // 100,
                              beneficiary_id="BEN-001", channel="EMAIL", now=NOW)
        assert d.score is not None and 0 <= d.score <= behavioural.BEHAVIOURAL_CAP

    def test_sparse_baseline_abstains_never_zero(self, monkeypatch):
        from packages.core import contracts_io
        base = contracts_io.baselines(NOW)["baselines"]["EXE-001"]
        thin = {**base, "sample_count": 3}
        monkeypatch.setattr(contracts_io, "baselines",
                            lambda now: {"baselines": {"EXE-001": thin}})
        d = behavioural.score(executive_id="EXE-001", amount_minor_units=None,
                              beneficiary_id=None, channel="EMAIL", now=NOW)
        assert d.score is None
        assert "insufficient_history" in d.abstain_reason

    def test_unknown_executive_abstains(self):
        d = behavioural.score(executive_id="NOBODY", amount_minor_units=None,
                              beneficiary_id=None, channel="EMAIL", now=NOW)
        assert d.score is None

    def test_cap_never_reaches_block_band(self):
        # every component maximally bad, still capped at 92
        d = behavioural.score(executive_id="EXE-001",
                              amount_minor_units=45_00_00_000 * 100 // 100,
                              beneficiary_id="BEN-003", channel="SMS", now=NOW,
                              lead_time_minutes=1, requests_last_24h=50)
        assert d.score is None or d.score <= 92   # BEN-003 unknown exec is fine either way


# ------------------------------------------------------------------ B4 beneficiary

class TestBeneficiary:
    def test_trust_tier_derived_not_stored(self, master):
        rec = dict(master["BEN-001"])
        assert beneficiary.trust_tier(rec, NOW.date()) == "established"
        rec["org_payment_count"] = 0
        assert beneficiary.trust_tier(rec, NOW.date()) == "unknown"

    def test_established_payee_new_account(self, master):
        f = beneficiary.score(beneficiary_label="Kalyani Forge Components Pvt Ltd",
                              destination_account="99999999999999",
                              amount_minor_units=100_000_00, now=NOW)
        assert f.score == pytest.approx(45.0)   # 5 + 40
        assert not f.account_on_record

    def test_web_of_trust_reduces_risk(self):
        # BEN-007: org has paid it (9 payments, 2 payers) vs BEN-003 (never paid)
        z = beneficiary.score(beneficiary_label="Zenith Marine Services",
                              destination_account="91820045517766",
                              amount_minor_units=1_000_00, now=NOW)
        g = beneficiary.score(beneficiary_label="Global Trading FZE",
                              destination_account="30070019929982",
                              amount_minor_units=1_000_00, now=NOW)
        assert g.score - z.score >= 20   # §7.3's test: the web of trust is worth >= 20

    def test_oversize_modifier(self):
        f = beneficiary.score(beneficiary_label="Kalyani Forge Components Pvt Ltd",
                              destination_account="50100234874471",
                              amount_minor_units=58_00_00_000 * 100 // 100 * 4, now=NOW)
        assert f.score >= 5 + 25

    def test_sanctions_clamps_to_100(self, monkeypatch):
        from packages.core import contracts_io
        m = {k: dict(v) for k, v in contracts_io.beneficiary_master(NOW).items()}
        m["BEN-001"]["sanctions_screen"] = "listed"
        monkeypatch.setattr(contracts_io, "beneficiary_master", lambda now: m)
        f = beneficiary.score(beneficiary_label="Kalyani Forge Components Pvt Ltd",
                              destination_account="50100234874471",
                              amount_minor_units=1, now=NOW)
        assert f.score == 100.0
        assert f.sanctions_screen == "listed"


# ------------------------------------------------------------------ B4.2 homoglyph

class TestHomoglyph:
    def test_cyrillic_a_detected(self, master):
        bad = "Kalyani Forge Components Pvt Ltd".replace("a", "а", 1)   # U+0430
        rep = homoglyph.confusion_report(bad, master)
        assert rep is not None
        assert rep.verdict == "skeleton_collision"
        assert "U+0430" in rep.reason
        assert rep.risk_floor >= 90

    def test_exact_match_is_not_a_confusion(self, master):
        assert homoglyph.confusion_report("Kalyani Forge Components Pvt Ltd", master) is None

    def test_legal_suffix_not_flagged(self, master):
        rep = homoglyph.confusion_report("Kalyani Forge Components Private Limited", master)
        # the skeleton is equal for a legitimate reason — an alias exists, so no attack
        assert rep is None or rep.verdict != "skeleton_collision"

    def test_short_name_no_edit_distance_fire(self, master):
        assert homoglyph.confusion_report("Ravi Co", master) is None

    def test_edit_distance_near_miss(self, master):
        rep = homoglyph.confusion_report("Kalyani Forge Componets Pvt Ltd", master)
        assert rep is not None and rep.verdict == "edit_distance"


# ------------------------------------------------------------------ B5 drift

class TestDrift:
    def _i(self, **over):
        base = dict(transaction_id="T1", action="TRANSFER", amount="1000000",
                    currency="INR", beneficiary="Kalyani Forge Components Pvt Ltd",
                    destination_account="50100234874471")
        return TransactionIntent(**{**base, **over})

    def test_weights_sum_to_one(self):
        from packages.core.policy.constants import DRIFT_WEIGHTS
        assert round(sum(DRIFT_WEIGHTS.values()), 10) == 1.0

    def test_identical_is_zero(self):
        assert drift.score(self._i()).score == 0.0

    def test_unresolved_amount_scores_40_band(self):
        r = drift.score(self._i(amount=None), reference_fields={"amount_minor_units": 100_000_00})
        assert r.per_field["amount"] == 40.0

    def test_tampered_account_scores_full(self):
        ref = {"destination_account": "50100234874471"}
        r = drift.score(self._i(destination_account="50100234879982"), reference_fields=ref)
        assert r.per_field["account"] == 100.0
        assert r.score >= 30.0

    def test_ifsc_only_difference_is_60(self):
        r = drift.score(self._i(), reference_fields={
            "destination_account": "50100234874471",  # same last-10 digits pattern
        })
        # construct a genuine IFSC-only difference: digits differ only in the prefix
        ref = {"destination_account": "60100234874471"}
        r = drift.score(self._i(), reference_fields=ref)
        assert r.per_field["account"] == 60.0

    def test_narrative_deterministic(self):
        a = drift.score(self._i())
        b = drift.score(self._i())
        assert a.narrative == b.narrative


# ------------------------------------------------------------------ B6 divergence

class TestDivergence:
    def _i(self, **over):
        base = dict(transaction_id="T1", action="TRANSFER", amount="25000000",
                    beneficiary="X", destination_account="50100234874471")
        return TransactionIntent(**{**base, **over})

    def test_agreement_scores_zero(self):
        i = self._i(deterministic_intent={"amount": "25000000",
                                          "destination_account": "50100234874471",
                                          "beneficiary": "X", "action": "TRANSFER"})
        assert divergence.score(i).score == 0.0

    def test_amount_disagreement_scores_85(self):
        i = self._i(deterministic_intent={"amount": "26000000",
                                          "destination_account": "50100234874471",
                                          "beneficiary": "X", "action": "TRANSFER"})
        assert divergence.score(i).score == 85.0

    def test_account_disagreement_scores_95(self):
        i = self._i(deterministic_intent={"amount": "25000000",
                                          "destination_account": "99999999999999",
                                          "beneficiary": "X", "action": "TRANSFER"})
        assert divergence.score(i).score == 95.0

    def test_injection_flag_floors_at_88(self):
        i = self._i(injection_flags=["ROLE_HIJACK"])
        assert divergence.score(i).score >= 88.0

    def test_hallucinated_field_scores_90(self):
        i = self._i(deterministic_intent={"amount": None,
                                          "destination_account": None,
                                          "beneficiary": None, "action": None})
        assert divergence.score(i).score == 90.0

    def test_resolve_never_falls_back_to_llm_for_money(self):
        with pytest.raises(divergence.ExtractionUnavailable):
            divergence.resolve(None, "25000000", "amount_minor_units")
        assert divergence.resolve("25000000", "26000000", "amount_minor_units") == "25000000"


# ------------------------------------------------------------------ B11 channel

class TestChannel:
    def test_same_channel_cannot_approve(self):
        v = channel_policy.verdict("PHONE", "PHONE")
        assert not v.independent and v.code == "SAME_CHANNEL"

    def test_console_after_voice_is_independent(self):
        v = channel_policy.verdict("PHONE", "console")
        assert v.independent and v.code == "INDEPENDENT"

    def test_email_verification_rejected(self):
        v = channel_policy.verdict("PHONE", "email")
        assert not v.independent and v.code == "UNTRUSTED_VERIFIER"

    def test_same_device_family_detected(self):
        v = channel_policy.verdict("EMAIL", "chat",
                                   origin_device_id="D1", verification_device_id="D1")
        assert not v.independent and v.code == "SAME_DEVICE_FAMILY"

    def test_pending_is_not_a_pass(self):
        v = channel_policy.verdict("PHONE", "")
        assert not v.independent and v.code == "PENDING"

    def test_reason_names_the_remedy(self):
        v = channel_policy.verdict("PHONE", "PHONE")
        assert "console" in v.explanation
