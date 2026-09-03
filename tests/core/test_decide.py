"""§16's tests. Two of them exist to answer a judge's question, not to catch a regression.

`test_decide_module_never_reads_llm_fields` walks `decide.py`'s AST and fails if the module
ever touches an attribute named after model output. `test_inputs_cannot_carry_model_output`
closes the other half: the LLM cannot reach the policy because there is nowhere for it to sit.
Together they turn Invariant 2 from a claim into a passing test you can show on a projector.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from packages.core.crypto.fingerprint import FieldDelta
from packages.core.models import BreakerState, Decision
from packages.core.policy.constants import (
    HARD_OVERRIDE_IDS,
    PRECONDITION_IDS,
    REQUIRED_ACTIONS,
    single_txn_ceiling,
)
from packages.core.policy.decide import (
    APPROVE_PRECONDITIONS,
    HARD_OVERRIDES,
    Inputs,
    Outcome,
    decide,
)

DECIDE_SRC = Path("packages/core/policy/decide.py")

#: A request with nothing wrong with it. Every test below is this, minus one thing.
CLEAN = dict(
    risk_score=12,
    coverage=1.0,
    fingerprint_status="MATCH",
    amount_minor_units=35_000_00,
    ceiling_minor_units=2_000_000_00,
    channel_independent=True,
    payee_label="Ravi Enterprises",
)


def clean(**over) -> Inputs:
    return Inputs(transaction_id=over.pop("transaction_id", "T-1"), **{**CLEAN, **over})

ACCOUNT_DELTA = FieldDelta("destination_account", "XXXXXX4471", "XXXXXX9982", "critical")
PURPOSE_DELTA = FieldDelta("purpose", "Q3 vendor settlement", "Q3 vendor payment", "cosmetic")


def test_s06_blocks_via_ho1_despite_a_challenge_band_score():
    """The moment the whole project is built around. Do not tune this away."""
    d = decide(clean(transaction_id="S06", risk_score=58, fingerprint_status="MISMATCH",
                     fingerprint_deltas=(ACCOUNT_DELTA,), channel_independent=False))

    assert d.decision is Decision.BLOCK
    assert d.band_outcome is Decision.CHALLENGE       # what the score alone would have said
    assert d.override_applied == "HO-1"
    assert d.hard_overrides_fired == ("FINGERPRINT_MISMATCH",)
    assert "XXXXXX4471" in d.reasons[0].text and "XXXXXX9982" in d.reasons[0].text
    assert "9982" in d.reasons[0].text and len(d.reasons[0].text) < 300
    assert d.required_actions == ("contact_executive_out_of_band", "notify_security_officer")


def test_band_outcome_is_published_next_to_every_decision():
    """§16.7: publishing what the score would have said is the proof nothing is hidden."""
    for score, band in ((10, Decision.APPROVE), (58, Decision.CHALLENGE), (90, Decision.BLOCK)):
        d = decide(clean(risk_score=score, fingerprint_status="MISMATCH",
                         fingerprint_deltas=(ACCOUNT_DELTA,)))
        assert d.decision is Decision.BLOCK and d.band_outcome is band


def test_ho1_fires_on_any_mismatch_not_only_critical_ones():
    """Shared Invariant 4 outranks B §16.3's narrower predicate: MISMATCH always BLOCKs.

    The critical/cosmetic split chooses the remedy — re-authorize versus wake security — and
    never the outcome. A cosmetic-only mismatch is still a request that does not match its
    approval.
    """
    d = decide(clean(fingerprint_status="MISMATCH", fingerprint_deltas=(PURPOSE_DELTA,)))
    assert d.decision is Decision.BLOCK and d.override_applied == "HO-1"
    assert d.required_actions == ("reauthorize_with_current_details",)
    assert d.reasons[0].severity == "material"

    critical = decide(clean(fingerprint_status="MISMATCH", fingerprint_deltas=(ACCOUNT_DELTA,)))
    assert critical.reasons[0].severity == "critical"
    assert "notify_security_officer" in critical.required_actions


def test_mismatch_with_no_delta_list_still_blocks():
    """Hash differs, pre-image unavailable: we cannot say what changed, so we say no."""
    d = decide(clean(fingerprint_status="MISMATCH", fingerprint_deltas=()))
    assert d.decision is Decision.BLOCK and d.override_applied == "HO-1"
    assert d.reasons[0].severity == "critical"

#: One set of inputs per override, each of which makes exactly that rule the first to fire.
FIRES: dict[str, dict] = {
    "HO-1": dict(fingerprint_status="MISMATCH", fingerprint_deltas=(ACCOUNT_DELTA,)),
    "HO-2": dict(beneficiary_account_changed=True, amount_minor_units=45_00_000_00),
    "HO-3": dict(confusion_verdict="skeleton_collision", confusion_confidence=97,
                 confusion_target_label="BEN-002 Ravi Enterprises",
                 confusion_target_established=True,
                 confusion_codepoint="U+0410 CYRILLIC CAPITAL LETTER A"),
    "HO-4": dict(nonce_replayed=True, consumed_at="2026-09-18T14:02:11+05:30"),
    "HO-5": dict(challenge_outcome="FAILED_EXHAUSTED",
                 challenge_field="destination_account", challenge_attempts=2),
    "HO-6": dict(signature_verdict="INVALID"),
    "HO-7": dict(sanctions_screen="hit:OFAC-SDN"),
    "HO-8": dict(presented_policy_version="1.0.0", current_policy_version="1.1.0"),
}


@pytest.mark.parametrize("override_id", HARD_OVERRIDE_IDS)
def test_every_hard_override_fires_and_blocks(override_id):
    d = decide(clean(transaction_id=override_id, **FIRES[override_id]))
    assert d.decision is Decision.BLOCK
    assert d.override_applied == override_id
    assert d.reasons[0].code == override_id
    assert d.reasons[0].text.endswith(".") and len(d.reasons[0].text) > 40
    assert d.cooldown_seconds == 0                    # nothing to wait for; it is refused


def test_hard_override_evaluation_order_is_frozen():
    """HO-1 first, because the account is the story — not the lookalike name."""
    assert tuple(r.id for r in HARD_OVERRIDES) == HARD_OVERRIDE_IDS

    both = decide(clean(**FIRES["HO-1"], **FIRES["HO-3"]))
    assert both.override_applied == "HO-1"

    later = decide(clean(**FIRES["HO-2"], **FIRES["HO-3"]))
    assert later.override_applied == "HO-2"


def test_exactly_one_override_is_reported_per_decision():
    """`hard_overrides_fired` is not a list of everything wrong; it is the reason we refused."""
    d = decide(clean(**FIRES["HO-4"], **FIRES["HO-6"], **FIRES["HO-7"]))
    assert len(d.hard_overrides_fired) == 1
    assert d.hard_overrides_fired == ("REPLAY_CONSUMED",)

def test_ceiling_ho2_needs_both_a_new_account_and_an_excess_amount():
    """Either alone is a score input. Together they are a categorical refusal."""
    big_but_on_record = decide(clean(amount_minor_units=45_00_000_00))
    assert big_but_on_record.override_applied != "HO-2"

    new_account_but_small = decide(clean(beneficiary_account_changed=True,
                                        amount_minor_units=40_000_00))
    assert new_account_but_small.override_applied != "HO-2"

    both = decide(clean(beneficiary_account_changed=True, amount_minor_units=45_00_000_00))
    assert both.override_applied == "HO-2" and both.decision is Decision.BLOCK
    assert "₹45,00,000" in both.reasons[0].text and "₹20,00,000" in both.reasons[0].text


def test_ceiling_s21_fifteen_lakh_stays_approve_eligible():
    """§16.3's explicit warning: an earlier ₹10,00,000 draft ceiling wrongly challenged S21."""
    ceiling = single_txn_ceiling(8_00_000_00)             # EXE-001's median, ₹8,00,000
    assert 15_00_000_00 <= ceiling
    d = decide(clean(transaction_id="S21", amount_minor_units=15_00_000_00,
                     ceiling_minor_units=ceiling, beneficiary_account_changed=True))
    assert d.decision is Decision.APPROVE
    assert d.override_applied is None and d.failed_preconditions == ()


def test_ceiling_uses_the_lower_of_absolute_and_relative():
    assert single_txn_ceiling(8_00_000_00) == 2_000_000_00     # absolute cap wins
    assert single_txn_ceiling(2_50_000_00) == 6_25_000_00      # 2.5x own median wins
    assert isinstance(single_txn_ceiling(1_23_456_79), int)    # money never becomes a float

#: One broken precondition each. PC-3 is absent on purpose: duress returns at step 3 and is
#: covered by `test_duress_reads_approve_and_leaks_no_marker` below.
BREAKS: dict[str, dict] = {
    "PC-1": dict(fingerprint_status="NOT_YET_VERIFIED"),
    "PC-2": dict(coverage=0.40, forced_outcome="CHALLENGE",
                 abstained=("behavioural", "beneficiary")),
    "PC-4": dict(channel_independent=False, amount_minor_units=8_00_000_00),
    "PC-5": dict(replay_risk=55),
    "PC-6": dict(breaker_state=BreakerState.HALF_OPEN),
}

#: The string §16.4 forbids. "The difference between those two strings is most of the
#: perceived quality of the product."
GENERIC = "additional verification required"


@pytest.mark.parametrize("pc_id", sorted(BREAKS))
def test_each_failed_precondition_challenges_and_names_its_remedy(pc_id):
    d = decide(clean(transaction_id=pc_id, **BREAKS[pc_id]))

    assert d.decision is Decision.CHALLENGE
    assert d.band_outcome is Decision.APPROVE          # the score was fine; the policy was not
    assert pc_id in d.failed_preconditions
    assert d.override_applied is None

    reason = next(r for r in d.reasons if r.code == pc_id)
    assert GENERIC not in reason.text.lower()
    assert len(reason.text) > 60 and reason.evidence_ref
    assert set(d.required_actions) <= set(REQUIRED_ACTIONS)
    assert d.required_actions != ("none",)


def test_preconditions_are_the_six_frozen_ids_in_order():
    assert tuple(p.id for p in APPROVE_PRECONDITIONS) == PRECONDITION_IDS


def test_approve_means_low_risk_and_all_six_held():
    d = decide(clean())
    assert d.decision is Decision.APPROVE and d.outcome is Outcome.APPROVE
    assert d.failed_preconditions == () and d.required_actions == ("none",)
    assert d.reasons and d.reasons[0].code == "BAND"    # Invariant 7 even on a clean approve


def test_every_failed_precondition_is_reported_not_just_the_first():
    """An operator about to make a phone call deserves the whole list."""
    d = decide(clean(**BREAKS["PC-1"], **BREAKS["PC-4"], **BREAKS["PC-5"]))
    assert d.failed_preconditions == ("PC-1", "PC-4", "PC-5")
    assert len({r.code for r in d.reasons}) == 4        # three failures plus the band

def test_never_downgrade_a_block_band_keeps_blocking():
    """Step 7. Failing preconditions can only escalate; they never rescue a BLOCK band."""
    d = decide(clean(risk_score=88, **BREAKS["PC-1"], **BREAKS["PC-2"]))
    assert d.decision is Decision.BLOCK and d.band_outcome is Decision.BLOCK
    assert d.failed_preconditions == ("PC-1", "PC-2")   # still reported, still blocked


def test_forced_challenge_from_fusion_cannot_lower_a_block():
    d = decide(clean(risk_score=95, coverage=0.30, forced_outcome="CHALLENGE"))
    assert d.decision is Decision.BLOCK


def test_forced_challenge_from_fusion_raises_an_approve():
    d = decide(clean(risk_score=8, coverage=0.30, forced_outcome="CHALLENGE",
                     abstained=("behavioural",)))
    assert d.decision is Decision.CHALLENGE


def test_breaker_precedes_individual_assessment():
    """Step 1. An organizational stop is not a judgement about this request."""
    d = decide(clean(risk_score=4, breaker_state=BreakerState.OPEN))
    assert d.decision is Decision.BLOCK
    assert d.outcome is Outcome.BREAKER_TRIPPED
    assert d.override_applied == "BREAKER"
    assert d.hard_overrides_fired == ("BREAKER_TRIPPED",)
    assert d.required_actions == ("named_human_review",)
    assert d.band_outcome is Decision.APPROVE


def test_breaker_outranks_a_fingerprint_mismatch():
    d = decide(clean(breaker_state=BreakerState.OPEN, **FIRES["HO-1"]))
    assert d.override_applied == "BREAKER"


def test_challenge_always_tells_the_approver_what_to_answer():
    """A CHALLENGE with `required_actions: ["none"]` is just an unexplained refusal."""
    d = decide(clean(risk_score=45))
    assert d.decision is Decision.CHALLENGE
    assert d.required_actions == ("answer_comprehension_challenge",)

    pending = decide(clean(risk_score=45, challenge_outcome="PENDING"))
    assert pending.required_actions[0] == "answer_comprehension_challenge"

    failed_once = decide(clean(risk_score=45, challenge_outcome="FAILED", challenge_attempts=1))
    assert failed_once.decision is Decision.CHALLENGE
    assert "answer_comprehension_challenge" in failed_once.required_actions

#: Words that would tell an attacker who reads one assessment how the duress scheme works.
LEAKY_WORDS = ("duress", "coerc", "marker", "phrase", "codeword", "code word", "safe word",
               "hostage", "under threat", "signal")


def test_duress_reads_approve_and_leaks_no_marker():
    """S09. The requester sees a routine screen; security is already awake.

    The wire `decision` is APPROVE and no capability token is minted, so C's executor — which
    cannot move money without a token — releases nothing. That is the whole trick.
    """
    d = decide(clean(risk_score=22, duress_suspected=True))

    assert d.outcome is Outcome.SILENT_ESCALATION
    assert d.decision is Decision.APPROVE
    assert d.duress_escalation is True
    assert d.visible_to_requester == "PROCESSING"
    assert d.requires_out_of_band_verification is True
    assert "notify_security_officer" in d.required_actions
    assert d.cooldown_seconds > 0                      # the delay is what buys the phone call

    text = " ".join(r.text for r in d.reasons).lower()
    for word in LEAKY_WORDS:
        assert word not in text, f"duress reason leaks {word!r}"


def test_duress_never_reaches_the_precondition_stage():
    """PC-3 exists as defence in depth, but the silent path returns before it runs."""
    d = decide(clean(duress_suspected=True, **BREAKS["PC-4"]))
    assert d.failed_preconditions == ()
    assert d.outcome is Outcome.SILENT_ESCALATION


def test_a_hard_override_outranks_the_silent_path_but_still_escalates():
    """A mismatch is not made routine by coercion — and refusing the money is not safety.

    The transaction blocks on HO-1 (which leaks nothing about the duress scheme, because the
    reason it gives is the account), and the escalation fires anyway: the money and the person
    are independent concerns.
    """
    d = decide(clean(duress_suspected=True, **FIRES["HO-1"]))
    assert d.decision is Decision.BLOCK and d.override_applied == "HO-1"
    assert d.duress_escalation is True
    assert "notify_security_officer" in d.required_actions

    text = " ".join(r.text for r in d.reasons).lower()
    for word in LEAKY_WORDS:
        assert word not in text


def test_breaker_with_duress_still_escalates():
    d = decide(clean(breaker_state=BreakerState.OPEN, duress_suspected=True))
    assert d.duress_escalation is True
    assert "notify_security_officer" in d.required_actions

def test_decide_module_never_reads_llm_fields():
    """§16.6's AST guard, verbatim. The fastest possible answer to "is the LLM deciding?"."""
    tree = ast.parse(DECIDE_SRC.read_text(encoding="utf-8"))
    banned = {"llm", "model_output", "completion", "narrative", "advisory", "summary"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in banned:
            pytest.fail(f"decide.py touches model output at line {node.lineno}")


def test_inputs_cannot_carry_model_output():
    """The other half of Invariant 2: there is nowhere for a completion to sit."""
    banned = {"llm", "model_output", "completion", "narrative", "advisory", "summary",
              "explanation", "investigator_note", "prompt", "response"}
    assert banned.isdisjoint(Inputs.__dataclass_fields__)


def test_decide_imports_nothing_that_could_reach_a_model_or_a_clock():
    """Determinism and containment are both properties of the import list."""
    tree = ast.parse(DECIDE_SRC.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    forbidden = {"random", "datetime", "time", "os", "httpx", "requests", "openai", "anthropic"}
    assert forbidden.isdisjoint(modules), f"decide.py imports {forbidden & modules}"


def test_decide_is_pure_and_repeatable():
    """§19.2's replay depends on this: same Inputs, byte-identical PolicyDecision."""
    inputs = clean(risk_score=58, **FIRES["HO-1"])
    first = decide(inputs)
    for _ in range(50):
        assert decide(inputs) == first


@pytest.mark.parametrize("case", [*FIRES.values(), *BREAKS.values(), {}])
def test_every_required_action_is_in_the_closed_vocabulary(case):
    d = decide(clean(**case))
    assert d.required_actions
    for action in d.required_actions:
        assert action in REQUIRED_ACTIONS
    assert "additional verification required" not in " ".join(d.required_actions)

def test_unknown_required_action_is_rejected_loudly():
    """A remedy C cannot render is worse than no remedy; catch the typo in CI, not in the demo."""
    from packages.core.policy.decide import _actions

    with pytest.raises(ValueError, match="closed REQUIRED_ACTIONS"):
        _actions(("do_something_vague",))


def test_cooldown_is_risk_proportional_except_when_refused():
    """§15.1. A BLOCK has nothing to wait for; everything else pays six seconds per point."""
    assert decide(clean(risk_score=0)).cooldown_seconds == 0
    assert decide(clean(risk_score=25)).cooldown_seconds == 150
    assert decide(clean(risk_score=45)).cooldown_seconds == 270
    assert decide(clean(risk_score=95)).cooldown_seconds == 0          # BLOCK band
    assert decide(clean(**FIRES["HO-4"])).cooldown_seconds == 0        # override

    scores = [decide(clean(risk_score=s)).cooldown_seconds for s in range(0, 70, 7)]
    assert scores == sorted(scores)                                    # monotonic, no step edge


def test_every_reason_carries_a_code_a_severity_and_an_evidence_ref():
    """Invariant 7 at the reason level: no floating assertions."""
    for case in (*FIRES.values(), *BREAKS.values(), {}, dict(duress_suspected=True),
                 dict(breaker_state=BreakerState.OPEN)):
        d = decide(clean(**case))
        assert d.reasons, "a populated risk_score with no reasons violates Invariant 7"
        for r in d.reasons:
            assert r.code and r.text and r.evidence_ref
            assert r.severity in ("critical", "material", "cosmetic", "info")
        assert d.risk_reasons == tuple(r.text for r in d.reasons)


def test_wire_decision_is_always_one_of_the_frozen_three():
    for case in (*FIRES.values(), *BREAKS.values(), {}, dict(duress_suspected=True),
                 dict(breaker_state=BreakerState.OPEN)):
        d = decide(clean(**case))
        assert d.decision.value in ("APPROVE", "CHALLENGE", "BLOCK")
        assert isinstance(d.decision, Decision)


def test_no_path_returns_approve_with_an_override_applied():
    """The one shape that would let a categorical refusal release money."""
    for case in (*FIRES.values(), dict(breaker_state=BreakerState.OPEN)):
        d = decide(clean(risk_score=2, **case))
        assert d.decision is not Decision.APPROVE
