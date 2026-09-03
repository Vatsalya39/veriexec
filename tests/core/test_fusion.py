"""§10.5's named tests, plus the ones that keep the thesis true.

`test_intent_confidence_independent_of_voice` is the test to put on a slide: it moves a voice
score from "certainly genuine" to "certainly fake" and asserts `intent_confidence` does not
budge. The spec's version calls `assess()`; this one exercises the same property at the fusion
boundary, which is where the independence is actually structural rather than incidental.
"""

from __future__ import annotations

import pytest

from packages.core.policy.constants import (
    INTENT_PENALTY_WEIGHTS,
    MIN_COVERAGE,
    RISK_WEIGHTS,
)
from packages.core.scoring.fusion import (
    INTENT_EXCLUDED_SIGNALS,
    UNCERTAINTY_FACTOR,
    DimensionScore,
    dimension_from_authenticity,
    fuse,
    intent_confidence,
    reconciles,
)

#: §10.4's worked example for S06 — the flagship scenario, term for term.
S06_PENALTIES = {
    "semantic_drift": 88,
    "behavioural": 70,
    "device_channel": 80,
    "beneficiary": 60,
    "extraction_inverse": 6,          # 100 - extraction_confidence(94)
}


def dim(name: str, score: float | None = 50.0) -> DimensionScore:
    if score is None:
        return DimensionScore(dimension=name, score=None,
                              abstain_reason=f"{name}: detector returned no signal")
    return DimensionScore(dimension=name, score=score, reason=f"{name} scored {score}",
                          evidence_ref=f"{name}.evidence[0]")


def all_dims(**over: float | None) -> dict[str, DimensionScore]:
    return {k: dim(k, over.get(k, 50.0)) for k in RISK_WEIGHTS}

def test_weights_sum_to_one():
    assert round(sum(RISK_WEIGHTS.values()), 10) == 1.0
    assert round(sum(INTENT_PENALTY_WEIGHTS.values()), 10) == 1.0
    assert len(RISK_WEIGHTS) == 7


def test_beneficiary_carries_the_heaviest_weight():
    """A deepfake is a delivery mechanism; the destination account is the crime."""
    assert max(RISK_WEIGHTS, key=RISK_WEIGHTS.get) == "beneficiary"


@pytest.mark.parametrize("absent", sorted(RISK_WEIGHTS))
def test_abstain_never_lowers_score(absent):
    """Treating `None` as `0` is the bug that turns a broken microphone into an approval."""
    baseline = fuse(all_dims())
    thinned = fuse(all_dims(**{absent: None}))

    assert baseline.score == 50
    assert thinned.score >= baseline.score
    assert thinned.abstained == (absent,)
    assert thinned.coverage == pytest.approx(1.0 - RISK_WEIGHTS[absent], abs=1e-6)


def test_abstention_penalty_is_exactly_the_published_formula():
    """No fudge factor: 50 + 0.30 * (1 - 0.65) * 100 = 60.5, and 60.5 rounds to 60.

    Python's round-half-to-even is what makes that last step identical on every platform, so
    replay stays byte-identical. It is a deliberate choice, not an accident of the language.
    """
    result = fuse(all_dims(behavioural=None, beneficiary=None))
    coverage = 1.0 - RISK_WEIGHTS["behavioural"] - RISK_WEIGHTS["beneficiary"]

    assert result.coverage == pytest.approx(coverage, abs=1e-6)      # 0.65
    assert result.weighted_before_penalty == pytest.approx(50.0, abs=1e-6)
    assert result.uncertainty_points == pytest.approx(10.5, abs=1e-3)
    assert result.total_before_clamp == pytest.approx(60.5, abs=1e-3)
    assert result.score == 60


def test_zero_coverage_forces_challenge():
    """Nothing could be evaluated. That is not a low score; it is no score."""
    result = fuse({k: dim(k, None) for k in RISK_WEIGHTS})

    assert result.score is None
    assert result.coverage == 0.0
    assert result.forced_outcome == "CHALLENGE"
    assert "No risk dimension could be evaluated" in result.reason


def test_thin_coverage_forces_challenge_below_the_floor():
    result = fuse(all_dims(communication_authenticity=None, social_engineering=None,
                           behavioural=None, beneficiary=None, semantic_drift=None))

    assert result.coverage < MIN_COVERAGE
    assert result.forced_outcome == "CHALLENGE"
    assert "insufficient evidence to approve" in result.reason
    assert result.score is not None               # the number still exists; it just cannot approve

def test_contributions_reconcile():
    """§10.3: a scorer whose parts do not add to its whole is a black box."""
    for scores in (all_dims(),
                   all_dims(behavioural=None),
                   all_dims(semantic_drift=88, beneficiary=60, device_channel=80),
                   all_dims(identity_confidence=None, device_channel=None)):
        result = fuse(scores)
        assert reconciles(result)
        assert sum(r.points for r in result.contributions) == pytest.approx(
            result.total_before_clamp, abs=0.5
        )


def test_contribution_rows_expose_both_the_nominal_and_renormalised_weight():
    result = fuse(all_dims(behavioural=None))
    row = next(r for r in result.contributions if r.factor == "beneficiary")

    assert row.weight == RISK_WEIGHTS["beneficiary"]              # frozen §6.6 key
    assert row.effective_weight > row.weight                      # additive, shows the maths
    assert row.points == pytest.approx(row.effective_weight * row.raw_score, abs=1e-3)
    assert row.dimension == row.factor and row.evidence


def test_abstained_rows_are_present_and_score_nothing():
    result = fuse(all_dims(behavioural=None))
    row = next(r for r in result.contributions if r.factor == "behavioural")

    assert row.abstained is True
    assert row.points == 0.0 and row.effective_weight == 0.0
    assert row.abstain_reason and row.evidence_ref == ""
    assert any(r.factor == UNCERTAINTY_FACTOR for r in result.contributions)


def test_contribution_rows_are_ordered_deterministically():
    """Biggest contributor first, ties broken by name — never by dict insertion order."""
    a = fuse(all_dims(semantic_drift=90, beneficiary=10))
    b = fuse(dict(reversed(list(all_dims(semantic_drift=90, beneficiary=10).items()))))

    assert [r.factor for r in a.contributions] == [r.factor for r in b.contributions]
    assert a == b
    points = [r.points for r in a.contributions]
    assert points == sorted(points, reverse=True)

def test_authenticity_is_inverted_exactly_once():
    """§6.2 warns every team inverts one of these at least once. One function, one comment."""
    genuine = dimension_from_authenticity("communication_authenticity", 96,
                                          reason="voice matched enrolment",
                                          evidence_ref="voice.report")
    fake = dimension_from_authenticity("communication_authenticity", 4,
                                       reason="voice did not match enrolment",
                                       evidence_ref="voice.report")

    assert genuine.score == 4.0 and fake.score == 96.0      # authenticity 96 => risk 4
    assert fuse({**all_dims(), "communication_authenticity": fake}).score > \
           fuse({**all_dims(), "communication_authenticity": genuine}).score


def test_authenticity_none_abstains_rather_than_scoring_zero():
    d = dimension_from_authenticity("identity_confidence", None,
                                    reason="unused", evidence_ref="unused")
    assert d.score is None and d.abstain_reason


def test_invariant_7_a_populated_score_needs_a_reason_and_an_evidence_ref():
    with pytest.raises(ValueError, match="Invariant 7"):
        DimensionScore(dimension="behavioural", score=70.0)
    with pytest.raises(ValueError, match="evidence_ref"):
        DimensionScore(dimension="behavioural", score=70.0, reason="unusual hour")
    with pytest.raises(ValueError, match="why it abstained"):
        DimensionScore(dimension="behavioural", score=None)


def test_unknown_dimension_is_rejected_at_construction():
    with pytest.raises(KeyError):
        DimensionScore(dimension="vibes", score=10.0, reason="r", evidence_ref="e")
    with pytest.raises(KeyError, match="not risk dimensions"):
        fuse({**all_dims(), "vibes": dim("behavioural", 10)})

def test_s06_intent_confidence_matches_the_spec_worked_example():
    """§10.4's table, term for term: 100 - 79.6 = 20."""
    value, components, excluded = intent_confidence(
        S06_PENALTIES, duress=False, fingerprint_status="MISMATCH"
    )

    assert value == 20
    assert components == {"behavioural": 10.5, "beneficiary": 6.0, "device_channel": 12.0,
                          "extraction_inverse": 0.3, "fingerprint": 20.0,
                          "semantic_drift": 30.8}
    assert round(sum(components.values()), 4) == 79.6
    assert 18 <= value <= 24                       # the pitched "about 20 out of 100"
    assert excluded == INTENT_EXCLUDED_SIGNALS


def test_intent_confidence_independent_of_voice():
    """The absence is the product. Move the voice score across its whole range; nothing moves.

    'Almost certainly his voice, almost certainly not his transaction' is only sayable if the
    second number cannot see the first.
    """
    quiet = fuse({**all_dims(), "communication_authenticity":
                  dimension_from_authenticity("communication_authenticity", 96,
                                              reason="voice matched", evidence_ref="voice.report")})
    loud = fuse({**all_dims(), "communication_authenticity":
                 dimension_from_authenticity("communication_authenticity", 4,
                                             reason="voice did not match",
                                             evidence_ref="voice.report")})

    a = intent_confidence(S06_PENALTIES, duress=False, fingerprint_status="MISMATCH")[0]
    b = intent_confidence(S06_PENALTIES, duress=False, fingerprint_status="MISMATCH")[0]

    assert a == b == 20
    assert quiet.score != loud.score               # risk MAY move; intent may not


@pytest.mark.parametrize("leaked", INTENT_EXCLUDED_SIGNALS)
def test_intent_confidence_refuses_media_and_identity_signals(leaked):
    """Not "ignores" — refuses. A silent drop would let the leak survive a refactor."""
    with pytest.raises(KeyError, match="may not reach intent_confidence"):
        intent_confidence({**S06_PENALTIES, leaked: 96},
                          duress=False, fingerprint_status="MATCH")


def test_intent_penalty_weights_contain_no_media_term():
    banned = {"voice_authenticity", "deepfake_probability", "face_liveness",
              "deepfake_voice_score", "deepfake_video_score", "voice", "video"}
    assert banned.isdisjoint(INTENT_PENALTY_WEIGHTS)

def test_intent_confidence_capped_on_mismatch():
    """A bound-field mismatch cannot leave us confident, whatever the rest of the evidence says."""
    clean_terms = {k: 0 for k in S06_PENALTIES}
    uncapped, _, _ = intent_confidence(clean_terms, duress=False, fingerprint_status="MATCH")
    capped, _, _ = intent_confidence(clean_terms, duress=False, fingerprint_status="MISMATCH")

    assert uncapped == 100
    assert capped == 25


def test_intent_confidence_capped_on_duress():
    """A coerced intention is not an intention."""
    clean_terms = {k: 0 for k in S06_PENALTIES}
    capped, _, _ = intent_confidence(clean_terms, duress=True, fingerprint_status="MATCH")
    assert capped == 25


def test_unverifiable_binding_is_a_real_penalty_not_a_zero():
    """"We never bound the intent" is evidence of nothing, and nothing is not reassurance."""
    clean_terms = {k: 0 for k in S06_PENALTIES}
    matched, _, _ = intent_confidence(clean_terms, duress=False, fingerprint_status="MATCH")
    unbound, _, _ = intent_confidence(clean_terms, duress=False,
                                      fingerprint_status="NOT_YET_VERIFIED")

    assert matched == 100
    assert unbound == 88                           # 100 - 0.20 * 60


def test_the_fingerprint_term_cannot_be_softened_by_the_caller():
    """It is derived from the verdict, so a caller passing `fingerprint: 0` changes nothing."""
    honest, _, _ = intent_confidence(S06_PENALTIES, duress=False,
                                     fingerprint_status="MISMATCH")
    liar, components, _ = intent_confidence({**S06_PENALTIES, "fingerprint": 0},
                                            duress=False, fingerprint_status="MISMATCH")

    assert honest == liar == 20
    assert components["fingerprint"] == 20.0


def test_intent_confidence_requires_every_term():
    with pytest.raises(KeyError, match="missing penalty term"):
        intent_confidence({"semantic_drift": 88}, duress=False, fingerprint_status="MATCH")


def test_intent_confidence_clamps_hostile_inputs():
    """A detector that returns 5000 must not push confidence negative or past 100.

    The floor with every caller-supplied term maxed out is 20, not 0, because the five terms
    the caller controls carry 0.80 of the weight and a verified binding is worth the other
    0.20. Only a MISMATCH takes it to zero — which is the arithmetic saying the same thing the
    policy says: the fingerprint is not one signal among many.
    """
    maxed, _, _ = intent_confidence({k: 5000 for k in S06_PENALTIES},
                                    duress=False, fingerprint_status="MATCH")
    maxed_unbound, _, _ = intent_confidence({k: 5000 for k in S06_PENALTIES},
                                            duress=False, fingerprint_status="MISMATCH")
    negative, _, _ = intent_confidence({k: -5000 for k in S06_PENALTIES},
                                       duress=False, fingerprint_status="MATCH")

    assert maxed == 20
    assert maxed_unbound == 0
    assert negative == 100
