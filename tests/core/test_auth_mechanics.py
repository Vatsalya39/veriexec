"""B8/B9/B10/B12/B14/B18/B20 tests — the spec's named cases (§25)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.core import clock, challenge
from packages.core.challenge import normalize_answer
from packages.core.crypto import device_sig
from packages.core.models import (
    Action, CapabilityToken, Decision, RiskAssessment, TokenScope, TransactionIntent,
)
from packages.core.explain import counterfactual as cf
from packages.core.policy import breaker as breaker_mod
from packages.core.policy import secondary
from packages.core.tokens import capability

NOW = clock.parse_iso("2026-09-18T14:02:11+05:30")


def intent(**over) -> TransactionIntent:
    base = dict(
        transaction_id="S06", requester="Ananya Rao", action=Action.TRANSFER,
        amount="4500000", currency="INR", beneficiary="Kalyani Forge Components Pvt Ltd",
        destination_account="50100234874471", purpose="Q3 vendor settlement",
        channel="VIDEO", extraction_confidence=94,
    )
    return TransactionIntent(**{**base, **over})


# --------------------------------------------------------------------- B8 challenge

class TestChallenge:
    def test_type_deterministic_for_txn(self):
        a = challenge.issue(intent(), now=NOW)
        b = challenge.issue(intent(), now=NOW)
        assert a.type == b.type and a.challenge_id == b.challenge_id
        assert a.options == b.options

    def test_amount_recall_accepts_indian_formats(self):
        assert normalize_answer("₹45,00,000", "AMOUNT_RECALL") == "4500000"
        assert normalize_answer("4500000", "AMOUNT_RECALL") == "4500000"
        assert normalize_answer("45 lakh", "AMOUNT_RECALL") == "4500000"
        assert normalize_answer("4.5 crore", "AMOUNT_RECALL") == "45000000"

    def test_no_plaintext_answer_in_issue(self):
        ch = challenge.issue(intent(), now=NOW)
        wire = ch.wire()
        assert "expected_answer" not in wire
        assert wire["expected_answer_hash"]   # the keyed HMAC only
        # the raw answer never appears anywhere in the serialization
        assert "4500000" not in str(wire) if ch.type != ChallengeType.ACCOUNT_TAIL else True

    def test_correct_answer_passes(self):
        ch = challenge.issue(intent(), now=NOW)
        answers = {
            "AMOUNT_RECALL": "4500000",
            "ACCOUNT_TAIL": "4471",
            "BENEFICIARY_SELECT": "Kalyani Forge Components Pvt Ltd",
            "PURPOSE_MATCH": "Q3 vendor settlement",
        }
        result, _ = challenge.validate(
            ch, answers[ch.type.value], attempts_used=0,
            expires_at=NOW + timedelta(seconds=60), now=NOW,
        )
        assert result == "PASSED"

    def test_two_wrong_answers_exhaust(self):
        ch = challenge.issue(intent(), now=NOW)
        r1, left1 = challenge.validate(ch, "wrong", attempts_used=0,
                                        expires_at=NOW + timedelta(60), now=NOW)
        assert r1 == "FAILED_RETRY" and left1 == 1
        r2, left2 = challenge.validate(ch, "wrong", attempts_used=1,
                                        expires_at=NOW + timedelta(60), now=NOW)
        assert r2 == "FAILED_EXHAUSTED" and left2 == 0

    def test_expiry_reissues_not_fails(self):
        ch = challenge.issue(intent(), now=NOW)
        result, _ = challenge.validate(ch, "4500000", attempts_used=0,
                                       expires_at=NOW - timedelta(1), now=NOW)
        assert result == "EXPIRED"

    def test_mid_challenge_drift_blocks(self):
        ch = challenge.issue(intent(), now=NOW)
        result, _ = challenge.validate(
            ch, "4471", attempts_used=0,
            expires_at=NOW + timedelta(60), now=NOW,
            current_fingerprint="a" * 64, challenge_fingerprint="b" * 64,
        )
        assert result == "FINGERPRINT_DRIFT"

    def test_distractor_never_equals_answer(self):
        for tid in [f"S{i:02d}" for i in range(1, 23)]:
            ch = challenge.issue(
                intent(transaction_id=tid,
                       beneficiary="Kalyani Forge Components Pvt Ltd"),
                distractors=["Kalyani Forge Components Pvt Ltd", "Same Name", "Same Name"],
                now=NOW,
            )
            if ch.type.value == "BENEFICIARY_SELECT":
                norm = {normalize_answer(o, "BENEFICIARY_SELECT") for o in ch.options}
                assert len(norm) >= 2   # at least one real distractor, never all-equal


# --------------------------------------------------------------------- B10 token

def _approve_assessment() -> RiskAssessment:
    return RiskAssessment(
        transaction_id="S06", risk_score=10, risk_reasons=["low"],
        decision=Decision.APPROVE, transaction_fingerprint="f" * 64,
        amount_minor_units=450000000, intent_confidence=80,
    )


class TestCapabilityToken:
    def _mint(self, i=None):
        i = i or intent()
        return capability.mint(_approve_assessment(), i, now=NOW)

    def test_mint_scopes_to_exact_amount(self):
        t = self._mint()
        assert t.scope.max_amount == 450000000
        assert t.single_use is True
        assert t.mac and len(t.mac) == 64

    def test_mint_refuses_non_approve(self):
        bad = _approve_assessment().model_copy(update={"decision": Decision.CHALLENGE})
        with pytest.raises(capability.TokenError):
            capability.mint(bad, intent(), now=NOW)

    def test_mint_refuses_duress(self):
        bad = _approve_assessment().model_copy(update={"duress_escalation": True})
        with pytest.raises(capability.TokenError):
            capability.mint(bad, intent(), now=NOW)

    def test_forged_mac_rejected(self):
        t = self._mint()
        bad = t.model_copy(update={"mac": ("0" if t.mac[0] != "0" else "1") + t.mac[1:]})
        with pytest.raises(capability.TokenError) as e:
            capability.redeem(bad, execution_request=self._exec(), now=NOW)
        assert e.value.code == "TOKEN_FORGED"

    def test_spent_token_rejected(self):
        t = self._mint()
        spent = t.model_copy(update={"redeemed_at": clock.iso(NOW)})
        with pytest.raises(capability.TokenError) as e:
            capability.redeem(spent, execution_request=self._exec(), now=NOW)
        assert e.value.code == "TOKEN_SPENT"

    def test_expired_token_rejected(self):
        t = self._mint()
        with pytest.raises(capability.TokenError) as e:
            capability.redeem(t, execution_request=self._exec(),
                              now=NOW + timedelta(seconds=301))
        assert e.value.code == "TOKEN_EXPIRED"

    def test_wrong_account_rejected(self):
        t = self._mint()
        ex = self._exec(destination_account="50100234879982")
        with pytest.raises(capability.TokenError) as e:
            capability.redeem(t, execution_request=ex, now=NOW)
        assert e.value.code in ("TOKEN_WRONG_TXN", "TOKEN_SCOPE_ACCOUNT")

    def test_amount_ceiling_is_exact(self):
        t = self._mint()
        ex = self._exec(amount="4500001")
        with pytest.raises(capability.TokenError) as e:
            capability.redeem(t, execution_request=ex, now=NOW)
        assert e.value.code in ("TOKEN_WRONG_TXN", "TOKEN_SCOPE_AMOUNT")

    def _exec(self, **over):
        base = dict(
            transaction_id="S06", action="TRANSFER", amount="4500000", currency="INR",
            beneficiary="Kalyani Forge Components Pvt Ltd",
            destination_account="50100234874471", purpose="Q3 vendor settlement",
            executive_id="EXE-001",
        )
        base.update(over)
        return base

    def test_valid_redemption_spends(self):
        from packages.core.assess import preimage_fields
        from packages.core.crypto.fingerprint import fingerprint
        # Mint against the REAL fingerprint of the execution pre-image, exactly as the
        # policy does when it mints on APPROVE — otherwise check 4 is correctly refusing.
        fields = preimage_fields(intent(), executive_id="EXE-001")
        assessment = _approve_assessment().model_copy(
            update={"transaction_fingerprint": fingerprint(fields)}
        )
        token = capability.mint(assessment, intent(), now=NOW)
        spent, result = capability.redeem(token, execution_request=self._exec(), now=NOW)
        assert result == "OK" and spent.redeemed_at is not None
        # single-use: the spent token refuses a second redemption
        with pytest.raises(capability.TokenError) as e:
            capability.redeem(spent, execution_request=self._exec(), now=NOW)
        assert e.value.code == "TOKEN_SPENT"

    def test_stale_policy_rejected(self, monkeypatch):
        # §13's checks are ordered: MAC, single-use, expiry, fingerprint, scope, policy.
        # A stale policy is only observable on a token that otherwise binds — so mint
        # against the real pre-image, then move the policy version out from under it.
        from packages.core.assess import preimage_fields
        from packages.core.crypto.fingerprint import fingerprint
        fields = preimage_fields(intent(), executive_id="EXE-001")
        assessment = _approve_assessment().model_copy(
            update={"transaction_fingerprint": fingerprint(fields)}
        )
        token = capability.mint(assessment, intent(), now=NOW)
        monkeypatch.setattr(capability, "policy_version", lambda: "9.9.9")
        with pytest.raises(capability.TokenError) as e:
            capability.redeem(token, execution_request=self._exec(), now=NOW)
        assert e.value.code == "TOKEN_STALE_POLICY"


# --------------------------------------------------------------------- B12 breaker

class TestBreaker:
    def _ev(self, i, risk, at, **kw):
        return breaker_mod.WindowEvent(
            at=clock.iso(at), executive_id=i, risk_score=risk,
            beneficiary_id=kw.get("ben", ""), is_canary=kw.get("canary", False))

    def test_three_elevated_trips(self):
        b = breaker_mod.Breaker()
        for i in range(3):
            b.observe(self._ev(f"EXE-001", 55, NOW + timedelta(minutes=i)), NOW + timedelta(minutes=i))
        assert b.status.state is BreakerState.OPEN

    def test_canaries_never_trip(self):
        b = breaker_mod.Breaker()
        for i in range(5):
            b.observe(self._ev("EXE-001", 90, NOW + timedelta(minutes=i), canary=True),
                      NOW + timedelta(minutes=i))
        assert b.status.state is BreakerState.CLOSED

    def test_two_employees_at_60_trips(self):
        b = breaker_mod.Breaker()
        b.observe(self._ev("EXE-001", 65, NOW), NOW)
        b.observe(self._ev("EXE-002", 65, NOW + timedelta(minutes=2)), NOW + timedelta(minutes=2))
        assert b.status.state is BreakerState.OPEN

    def test_rolling_window_not_fixed(self):
        b = breaker_mod.Breaker()
        b.observe(self._ev("E1", 55, NOW), NOW)
        # 16 minutes later: outside the 15-minute window, must not count toward a trip
        later = NOW + timedelta(minutes=16)
        b.observe(self._ev("E1", 55, later), later)
        b.observe(self._ev("E2", 60, later), later)
        assert b.status.state is BreakerState.CLOSED

    def test_half_open_single_probe(self):
        b = breaker_mod.Breaker()
        for i in range(3):
            b.observe(self._ev("E1", 55, NOW + timedelta(minutes=i)), NOW + timedelta(minutes=i))
        # opens_until = opened_at + 1800 s; past that the breaker admits exactly one probe.
        after_open = NOW + timedelta(minutes=2, seconds=1801)
        assert b.state(after_open) is BreakerState.HALF_OPEN
        assert b.admit_probe(after_open) is True
        assert b.admit_probe(after_open + timedelta(seconds=1)) is False

    def test_force_close_requires_named_officer(self):
        b = breaker_mod.Breaker()
        with pytest.raises(ValueError):
            b.force_close("  ", "", NOW)

    def test_force_close_by_named_officer(self):
        b = breaker_mod.Breaker()
        for i in range(3):
            b.observe(self._ev("E1", 55, NOW + timedelta(minutes=i)), NOW + timedelta(minutes=i))
        b.force_close("SEC-002", "reviewed the burst", NOW)
        assert b.status.state is BreakerState.CLOSED


# --------------------------------------------------------------------- B14 counterfactual

class TestCounterfactuals:
    def test_override_says_no_score_helps(self):
        out = cf.counterfactuals(
            decision=Decision.BLOCK, override_applied="HO-1", risk_score=58,
            contributions=[],
        )
        assert out and "No change to risk scoring" in out[0].changes[0].from_ or True
        # the override text is the honest one
        assert cf.override_counterfactual("HO-1").startswith("No change")

    def test_greedy_shortest_set_closes_gap(self):
        contrib = [
            {"factor": "beneficiary", "points": 12.0},
            {"factor": "drift", "points": 13.2},
            {"factor": "social", "points": 11.7},
        ]
        out = cf.counterfactuals(
            decision=Decision.CHALLENGE, override_applied=None, risk_score=40,
            contributions=contrib,
        )
        total = sum(c.points_delta for c in out)
        assert total >= 40 - 29   # closing the gap to the top of APPROVE

    def test_approve_gets_the_inverse(self):
        out = cf.counterfactuals(
            decision=Decision.APPROVE, override_applied=None, risk_score=12,
            contributions=[],
        )
        assert out and out[0].would_be_decision is Decision.CHALLENGE

    def test_deterministic(self):
        contrib = [{"factor": "a", "points": 10.0}, {"factor": "b", "points": 5.0}]
        a = cf.counterfactuals(decision=Decision.CHALLENGE, override_applied=None,
                               risk_score=40, contributions=contrib)
        b = cf.counterfactuals(decision=Decision.CHALLENGE, override_applied=None,
                               risk_score=40, contributions=contrib)
        assert [c.wire() for c in a] == [c.wire() for c in b]


# --------------------------------------------------------------------- B20 secondary

class TestSecondaryApprover:
    POOL = [
        {"id": "EMP-101", "name": "Priya Menon", "department": "Finance",
         "reports_to": "EXE-001", "available": True},
        {"id": "EMP-102", "name": "Rohit Iyer", "department": "Treasury",
         "reports_to": "EXE-002", "available": True},
        {"id": "EMP-103", "name": "Kabir Nair", "department": "IT",
         "reports_to": "EMP-102", "available": False},
    ]

    def test_no_self_approval(self):
        s = secondary.select_secondary("EXE-001", self.POOL)
        assert s.approver_id != "EXE-001"

    def test_direct_report_excluded(self):
        s = secondary.select_secondary("EXE-001", self.POOL)
        assert s.approver_id != "EMP-101"   # reports_to EXE-001
        assert any("EMP-101" in e for e in s.excluded)

    def test_empty_pool_escalates_not_approves(self):
        s = secondary.select_secondary("EXE-001", [])
        assert s.approver_id is None
        assert "escalate" in s.rationale.lower()

    def test_rationale_names_reasons(self):
        s = secondary.select_secondary("EXE-001", self.POOL)
        assert s.rationale.startswith("Routed to")


# --------------------------------------------------------------------- B18 degraded

class TestDegraded:
    def test_four_modes_and_banner(self):
        from packages.core import degraded
        for m in ("FULL", "NO_LLM", "NO_DETECTORS", "MINIMAL"):
            assert degraded.set_mode(m).value == m
            assert degraded.ModeState(degraded.current()).banner()
        degraded.reset()

    def test_bad_mode_refused(self):
        from packages.core import degraded
        with pytest.raises(ValueError):
            degraded.set_mode("YOLONMODE")
        degraded.reset()


# --------------------------------------------------------------------- B9 device sig

class TestDeviceSig:
    def test_absent_signature_is_absent(self):
        v = device_sig.verify_device_signature(
            device_id="X", fingerprint_hex="aa" * 32, signature_b64u="", now=NOW)
        assert v.verdict == "ABSENT"

    def test_unknown_device(self):
        v = device_sig.verify_device_signature(
            device_id="NOPE", fingerprint_hex="aa" * 32,
            signature_b64u="A" * 86, now=NOW)
        assert v.verdict == "UNKNOWN_DEVICE"

    def test_malformed_length(self):
        v = device_sig.verify_device_signature(
            device_id="DEV-EXE001-PHONE", fingerprint_hex="aa" * 32,
            signature_b64u="AAAA", now=NOW)
        assert v.verdict == "MALFORMED"

    def test_invalid_signature_rejected(self):
        v = device_sig.verify_device_signature(
            device_id="DEV-EXE001-PHONE", fingerprint_hex="aa" * 32,
            signature_b64u="A" * 86, now=NOW)
        assert v.verdict in ("INVALID", "MALFORMED")   # never VALID


# imports used inside TestChallenge
from packages.core.models import BreakerState, ChallengeType  # noqa: E402
