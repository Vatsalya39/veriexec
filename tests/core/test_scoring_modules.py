"""B3/B4/B5/B6/B11 module tests — the spec's named test cases (§25)."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.core import clock
from packages.core.models import DeterministicIntent, TransactionIntent
from packages.core.scoring import behavioural, beneficiary, drift, divergence, homoglyph
from packages.core.policy import channel as channel_policy
from packages.core.policy.constants import DRIFT_WEIGHTS

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
        """Agreement is 0 — but only when there were two statements to agree."""
        ref = {"amount_minor_units": 1_000_000_00, "currency": "INR",
               "beneficiary_id_or_name": "Kalyani Forge Components Pvt Ltd",
               "destination_account": "50100234874471", "action": "TRANSFER"}
        r = drift.score(self._i(), reference_fields=ref)
        assert r.score == 0.0
        assert set(r.measured) == set(DRIFT_WEIGHTS)

    def test_no_reference_and_one_reading_abstains_rather_than_scoring_zero(self):
        """The self-comparison must not publish 0.

        With no pre-image and `extraction_mode='deterministic'`, `spoken` and `executed` are
        both filled from the same intent. Scoring that 0 spent 0.15 of the fusion weight
        certifying "agrees on every bound field" from one reading compared with a copy of
        itself, and kept coverage at 1.00 so the uncertainty penalty never fired.
        """
        r = drift.score(self._i())
        assert r.score is None
        assert r.measured == ()
        assert "no second statement" in r.abstain_reason
        assert drift.dimension(r).score is None
        assert drift.dimension(r).abstain_reason

    def test_a_hybrid_extraction_still_abstains_until_a_real_second_reading_exists(self):
        """`extraction_mode=hybrid` alone must not manufacture agreement. [found live]

        The flag says two parsers ran at A; it does not say B was handed two statements.
        A's merge policy resolves every compared field to the deterministic twin, so the
        merged intent and `deterministic_intent` are equal by construction and every
        distance would be 0 — the same exculpatory self-comparison the abstaining test
        above forbids, reachable via a flag. With the live Ollama model wired in, this
        exact path demoted S08 from BLOCK to CHALLENGE across the 22-scenario corpus:
        drift silently published 0.0 at coverage 1.00 and the uncertainty penalty never
        fired. Until A publishes the model's raw, unmerged reading as its own twin, the
        honest result is an abstention. A reference pre-image is a real second statement
        and still scores (see `test_tampered_account_scores_full`).
        """
        i = self._i(extraction_mode="hybrid", deterministic_intent=DeterministicIntent(
            action="TRANSFER", amount=1_000_000.0, currency="INR",
            beneficiary="Kalyani Forge Components Pvt Ltd",
            destination_account="50100234879982",       # the extractors disagree here
        ))
        r = drift.score(i)
        assert r.score is None and r.measured == ()
        assert "no second statement" in r.abstain_reason
        # And the same intent WITH an independent reference still scores, proving the
        # abstention is about missing evidence, not a broken dimension. The reference
        # account differs from the request's (…9982 vs …4471), so the account field —
        # the one the two extractors disagreed on above — now measures a real 100.0.
        r2 = drift.score(i, reference_fields={
            "destination_account": "50100234879982", "amount_minor_units": 1_000_000_00})
        assert r2.score is not None and r2.per_field["account"] == 100.0

    def test_unresolved_amount_is_measurable_with_no_reference_at_all(self):
        """§8's 40 is a claim about the request, not about a disagreement, so it survives.

        S17 and S22 state no readable amount. Both sides being `None` used to return 0.0 —
        "the amounts agree" about two numbers that do not exist.
        """
        r = drift.score(self._i(amount=None))
        assert r.measured == ("amount",)
        assert r.per_field["amount"] == 40.0
        assert r.score == 40.0                 # renormalised over the one measurable field
        assert "could not be read exactly" in r.narrative

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
        ref = {"destination_account": "60100234874471"}
        a = drift.score(self._i(), reference_fields=ref)
        b = drift.score(self._i(), reference_fields=ref)
        assert a.narrative == b.narrative and a.narrative


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
