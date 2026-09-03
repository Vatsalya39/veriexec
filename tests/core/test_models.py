"""The frozen §6 shapes stay frozen, and the invariants are enforced by the models.

These tests are the tripwire for the most expensive class of mistake in a three-team build:
a base field quietly renamed, or an extension shipped without a default. Either one breaks
a consumer at integration time rather than here.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.core.models import (
    CapabilityToken,
    Counterfactual,
    Decision,
    FieldChange,
    RiskAssessment,
    RiskDimension,
    SignalBundle,
    TokenScope,
    TransactionIntent,
    to_paise,
)

RISK_ASSESSMENT_BASE = (
    "transaction_id", "risk_score", "risk_reasons", "identity_confidence",
    "communication_authenticity", "intent_confidence", "semantic_drift_score",
    "transaction_fingerprint", "fingerprint_status", "beneficiary_risk", "behavioral_risk",
    "decision", "recommended_action", "investigation_summary",
    "requires_out_of_band_verification", "duress_escalation",
)

RISK_ASSESSMENT_EXTENSIONS = (
    "contribution_table", "counterfactuals", "top_blocking_factor",
    "intent_confidence_components", "hard_overrides_fired", "policy_version",
    "policy_hash", "capability_token", "cooldown_seconds", "breaker_state",
    "secondary_approver_required", "secondary_approver_id",
    "secondary_approver_rationale", "comprehension_challenge", "channel_independence",
    "extraction_divergence_penalty", "degraded_mode", "latency_ms", "beneficiary_graph",
)


def token() -> CapabilityToken:
    return CapabilityToken(
        token_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        transaction_id="t1",
        transaction_fingerprint="a" * 64,
        scope=TokenScope(
            action="TRANSFER",
            destination_account="50100234874471",
            max_amount=100_000_000,
            currency="INR",
        ),
        issued_at="2026-09-03T13:05:00+05:30",
        expires_at="2026-09-03T13:10:00+05:30",
    )


# --- the contract itself ------------------------------------------------------------

def test_frozen_base_fields_are_all_present():
    fields = set(RiskAssessment.model_fields)
    assert set(RISK_ASSESSMENT_BASE) <= fields
    assert set(RISK_ASSESSMENT_EXTENSIONS) <= fields


def test_every_extension_key_is_always_emitted_with_its_default():
    """§6.6: producers MUST always emit every extension key. No exclude_unset anywhere."""
    wire = RiskAssessment(transaction_id="t1").wire()
    assert set(wire) == set(RiskAssessment.model_fields)
    assert wire["hard_overrides_fired"] == []
    assert wire["policy_version"] == "0.0.0"
    assert wire["capability_token"] is None
    assert wire["breaker_state"] == "CLOSED"
    assert wire["cooldown_seconds"] == 0
    assert wire["latency_ms"] == {}


def test_default_assessment_never_approves_by_omission():
    ra = RiskAssessment(transaction_id="t1")
    assert ra.decision is Decision.CHALLENGE
    assert ra.fingerprint_status.value == "NOT_YET_VERIFIED"


def test_inbound_keeps_unknown_keys_from_other_teams():
    """A ships extensions on its own schedule; that must not need a B release."""
    ti = TransactionIntent(transaction_id="t1", requester="Ananya Rao", not_yet_specified=7)
    assert ti.not_yet_specified == 7


def test_outbound_rejects_a_mistyped_key():
    with pytest.raises(ValidationError):
        RiskAssessment(transaction_id="t1", risk_scoer=1)

# --- invariants the models refuse to violate ----------------------------------------

def test_invariant_7_a_populated_score_needs_a_reason():
    with pytest.raises(ValidationError, match="Invariant 7"):
        RiskAssessment(transaction_id="t1", risk_score=58)
    with pytest.raises(ValidationError, match="Invariant 7"):
        RiskDimension(score=40)
    assert RiskDimension(score=40, reasons=["New payee, 0 prior payments"]).score == 40
    assert RiskDimension().score == 0  # zero needs nothing


def test_invariant_4_mismatch_cannot_be_anything_but_block():
    for outcome in ("APPROVE", "CHALLENGE"):
        with pytest.raises(ValidationError, match="Invariant 4"):
            RiskAssessment(
                transaction_id="t1", fingerprint_status="MISMATCH", decision=outcome,
                risk_score=58, risk_reasons=["destination account does not match"],
            )


def test_invariant_9_no_capability_without_approve():
    with pytest.raises(ValidationError, match="Invariant 9"):
        RiskAssessment(transaction_id="t1", decision="CHALLENGE", capability_token=token())
    with pytest.raises(ValidationError, match="Invariant 9"):
        RiskAssessment(
            transaction_id="t1", decision="APPROVE",
            capability_token=token().model_copy(update={"single_use": False}),
        )


def test_invariant_5_a_duress_approval_mints_nothing():
    """S09 must look routine to the requester and still execute nothing."""
    with pytest.raises(ValidationError, match="Invariant 5"):
        RiskAssessment(
            transaction_id="t1", decision="APPROVE", duress_escalation=True,
            capability_token=token(),
        )
    silent = RiskAssessment(transaction_id="t1", decision="APPROVE", duress_escalation=True)
    assert silent.capability_token is None

# --- the traps -----------------------------------------------------------------------

def test_amount_reaches_paise_without_ever_touching_a_float():
    assert TransactionIntent(
        transaction_id="t1", amount=1_500_000, currency="INR"
    ).amount_minor_units() == 150_000_000
    assert to_paise(1500000.0) == 150_000_000          # a whole float is fine
    assert to_paise("15,00,000") == 150_000_000
    assert to_paise(None) is None
    with pytest.raises(TypeError):
        to_paise(0.1 + 0.2)                            # never silently rounded
    with pytest.raises(TypeError):
        to_paise(2.555)


def test_missing_signals_default_to_no_evidence_not_good_evidence():
    """Invariant 3 as a default value: absence must never read as authenticity."""
    sb = SignalBundle(transaction_id="t1")
    assert sb.identity_confidence == 0
    assert sb.communication_authenticity == 0
    assert sb.deepfake_voice_score is None
    assert sb.device_info.known_device is False
    assert sb.media_scores_present() is False


def test_counterfactual_serialises_from_not_from_():
    cf = Counterfactual(
        would_be_decision="APPROVE",
        changes=[FieldChange(field="destination_account", **{"from": "XXXXXX9982"},
                             to="XXXXXX4471")],
        points_delta=-29,
    )
    assert cf.wire()["changes"][0] == {
        "field": "destination_account", "from": "XXXXXX9982", "to": "XXXXXX4471",
    }


def test_token_mac_preimage_excludes_exactly_mac_and_redeemed_at():
    t = token()
    assert set(t.wire()) - set(t.mac_preimage()) == {"mac", "redeemed_at"}
