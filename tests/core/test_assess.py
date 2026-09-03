"""§16 end to end: `assess()` — bind, fuse, decide, publish.

Two tests here are the ones to put on a slide. `test_s06_blocks_end_to_end_via_ho1` is §26's
`test_minimal_mode_still_blocks_s06`: every scorer is still a stub and S06 blocks anyway,
because it blocks on the fingerprint and the fingerprint needs no detector. And
`test_intent_confidence_survives_the_voice_moving_across_its_whole_range` runs the thesis
through the real orchestrator rather than the fusion boundary — the voice score swings from
"certainly fake" to "certainly genuine", `risk_score` moves, and `intent_confidence` does not.
"""

from __future__ import annotations

import pytest

from packages.core import clock
from packages.core.assess import (
    STUBBED_DIMENSIONS,
    UNVERIFIED_CLAIMS,
    assess,
    dimensions,
    minor_units,
    preimage_fields,
)
from packages.core.crypto.fingerprint import FINGERPRINT_FIELDS, fingerprint
from packages.core.models import (
    Action,
    AssessInput,
    AuthorizationRecord,
    BreakerState,
    Channel,
    Decision,
    DeviceSignature,
    FingerprintStatus,
    SignalBundle,
    TransactionIntent,
)
from packages.core.policy.constants import REQUIRED_ACTIONS, RISK_WEIGHTS
from packages.core.scoring.fusion import INTENT_EXCLUDED_SIGNALS

#: Frozen instant. `assess()` takes `now` as a parameter precisely so a test can do this.
NOW = clock.parse_iso("2026-09-18T14:02:11+05:30")

#: From contracts/beneficiary_master.json — BEN-001's one registered account, and the
#: lookalike it becomes when someone edits the request after the CFO has approved it.
ON_RECORD = "50100234874471"
SWAPPED = "50100234879982"
BEN_NAME = "Kalyani Forge Components Pvt Ltd"


def intent(account: str = ON_RECORD, **over) -> TransactionIntent:
    base = dict(
        transaction_id="S06", requester="Ananya Rao", action=Action.TRANSFER,
        amount="4500000", currency="INR", beneficiary=BEN_NAME,
        destination_account=account, purpose="Q3 vendor settlement",
        channel=Channel.VIDEO, extraction_confidence=94,
    )
    return TransactionIntent(**{**base, **over})


def bundle(**over) -> SignalBundle:
    base = dict(
        transaction_id="S06", identity_confidence=91, communication_authenticity=96,
        deepfake_voice_score=88.0, social_engineering_score=70,
        social_engineering_indicators=["urgency", "secrecy", "authority"],
    )
    return SignalBundle(**{**base, **over})


def run(what: TransactionIntent | None = None, *, reference: dict | None = None,
        signals: SignalBundle | None = "keep", **kw):
    """One assessment. `reference` is the pre-image as the executive approved it."""
    what = what if what is not None else intent()
    if signals == "keep":
        signals = bundle()
    presented = kw.pop("presented", fingerprint(reference) if reference else "")
    breaker_state = kw.pop("breaker_state", BreakerState.CLOSED)
    return assess(
        AssessInput(intent=what, signals=signals, presented_fingerprint=presented, **kw),
        reference_fields=reference, breaker_state=breaker_state, now=NOW,
    )


#: What the CFO actually approved: the same transaction, paying the account on record.
APPROVED = preimage_fields(intent(ON_RECORD), executive_id="EXE-001")

def test_s06_blocks_end_to_end_via_ho1():
    """§26's flagship. With every real scorer landed, S06 still blocks by HO-1 — the
    override, not the weights, is what refuses a tampered account (§26 trap #4: never
    tune the score to make S06 block on numbers when HO-1 blocks on the hash)."""
    a = run(intent(SWAPPED), reference=APPROVED)

    assert a.decision is Decision.BLOCK
    # The band is whatever the real scorers fused to — publishing it next to the BLOCK is
    # §16.5's point, and it is NOT required to be CHALLENGE (the 58 was a stub-era number).
    # 35.0 now, up from 29.0: this case has an approved pre-image, so `semantic_drift` is
    # measurable and scores the swapped account (`account=100`, raw 30.0) instead of
    # abstaining. HO-1 still delivers the BLOCK on the hash, which is what trap #4 protects.
    assert a.band_outcome is Decision.CHALLENGE
    assert a.risk_score == pytest.approx(35.0, abs=1e-6)
    drift_row = next(r for r in a.contribution_table if r.factor == "semantic_drift")
    assert drift_row.abstained is False and "account=100" in drift_row.evidence
    assert a.override_applied == "HO-1"
    assert a.hard_overrides_fired == ["FINGERPRINT_MISMATCH"]
    assert a.fingerprint_status is FingerprintStatus.MISMATCH
    assert a.required_actions == ["contact_executive_out_of_band", "notify_security_officer"]
    assert a.capability_token is None


def test_the_delta_names_the_account_and_redacts_it():
    a = run(intent(SWAPPED), reference=APPROVED)
    delta = a.fingerprint_deltas[0]

    assert delta.field == "destination_account" and delta.severity == "critical"
    assert delta.expected.endswith("4471") and delta.presented.endswith("9982")
    assert ON_RECORD not in delta.expected and SWAPPED not in delta.presented
    assert "4471" in a.reasons_detailed[0].text and "9982" in a.reasons_detailed[0].text


def test_a_matching_binding_is_never_manufactured_from_a_missing_reference():
    """No stored pre-image means UNVERIFIABLE, never MATCH. PC-1 keeps it off the approve path."""
    a = run(presented="deadbeef" * 8)

    assert a.fingerprint_status is FingerprintStatus.NOT_YET_VERIFIED
    assert a.decision is not Decision.APPROVE
    assert a.override_applied != "HO-1"                  # nothing to compare is not tampering


def test_assess_is_byte_identical_on_replay():
    """§19.2 in one line. Pure given `now`, which is why `now` is a parameter."""
    first = run(intent(SWAPPED), reference=APPROVED).model_dump_json()
    for _ in range(25):
        assert run(intent(SWAPPED), reference=APPROVED).model_dump_json() == first

def test_intent_confidence_survives_the_voice_moving_across_its_whole_range():
    """The thesis, through the real orchestrator: "almost certainly his voice, almost
    certainly not his transaction".

    The media scores move from "certainly a deepfake" to "certainly genuine". `risk_score`
    moves, because authenticity is a risk input and should be. `intent_confidence` does not
    move at all, because no media term exists for it to move.
    """
    fake = run(signals=bundle(communication_authenticity=4, identity_confidence=6,
                              deepfake_voice_score=2.0, deepfake_video_score=3.0))
    genuine = run(signals=bundle(communication_authenticity=99, identity_confidence=98,
                                 deepfake_voice_score=97.0, deepfake_video_score=96.0))

    assert fake.intent_confidence == genuine.intent_confidence
    assert fake.intent_confidence_components == genuine.intent_confidence_components
    assert fake.risk_score > genuine.risk_score          # risk MAY move; intent may not


def test_excluded_signals_are_published_not_just_documented():
    a = run()
    assert a.intent_confidence_excluded_signals == list(INTENT_EXCLUDED_SIGNALS)
    assert "deepfake_voice_score" in a.intent_confidence_excluded_signals
    assert set(a.intent_confidence_components).isdisjoint(INTENT_EXCLUDED_SIGNALS)


def test_a_mismatch_caps_intent_confidence_whatever_the_media_says():
    """A perfect voice cannot rescue a broken binding. 25 is the cap, and it is the point."""
    a = run(intent(SWAPPED), reference=APPROVED,
            signals=bundle(communication_authenticity=100, identity_confidence=100))
    assert a.intent_confidence == 25

def _codes(a) -> set[str]:
    return {r.code for r in a.reasons_detailed}


def test_no_signal_bundle_abstains_rather_than_reading_clean():
    """Invariant 3 as arithmetic: a missing bundle must score worse than a good one."""
    blind = run(signals=None)
    seeing = run()

    # 0.35, not 0.60: the three A-supplied dimensions abstain for want of a bundle (0.40),
    # and `semantic_drift` (0.15) and `device_channel` (0.10) abstain because a first pass
    # with no pre-image and no verification channel has nothing to compare either. That is
    # below MIN_COVERAGE, which is the correct reading of "we were handed no evidence".
    assert blind.coverage == pytest.approx(0.35, abs=1e-6)
    assert blind.risk_score > seeing.risk_score
    assert blind.decision is not Decision.APPROVE
    assert any(r.factor == "uncertainty" for r in blind.contribution_table)
    assert any(r.abstained and r.abstain_reason for r in blind.contribution_table)


def test_a_caller_cannot_assert_its_own_verification():
    """A record that sets `channel_independent: true` on itself has proved nothing.

    B11 establishes independence by comparing channel families; until then the claim is read
    as unestablished, PC-4 fails, and the operator gets a sentence naming the remedy. The
    alternative — trusting the field — means a compromised console can approve its own work.
    """
    auth = AuthorizationRecord(
        transaction_id="S06", executive_id="EXE-001",
        transaction_fingerprint=fingerprint(APPROVED),
        channel_independent=True,
        device_signature=DeviceSignature(alg="ECDSA_P256_SHA256", signature_b64="Zm9v"),
    )
    a = run(reference=APPROVED, authorization=auth)

    assert a.fingerprint_status is FingerprintStatus.MATCH        # the binding really did hold
    assert a.decision is Decision.CHALLENGE
    assert "PC-4" in _codes(a)
    assert a.channel_independence.satisfied is False
    assert a.channel_independence.code == "NOT_ESTABLISHED"
    assert "contact_executive_out_of_band" in a.required_actions


def test_an_unparseable_amount_is_not_a_small_amount():
    """A lossy amount is refused (§26 trap #2), and "no amount" reads as "not low-value"."""
    # Sub-paise precision is the thing that must never be silently rounded.
    assert minor_units(intent(amount=45.005)) is None
    assert minor_units(intent(amount="not a number")) is None
    assert minor_units(intent(amount=None)) is None
    assert minor_units(intent(amount="4500000")) == 450_000_000

    # A whole float is money: the frozen field is `number|null` and A really does emit
    # `640000.0`. Refusing it here is what pinned `amount_minor_units` to None on all 22
    # scenarios and disabled the low-value exemption, the ceiling test and amount deviation.
    assert minor_units(intent(amount=45.0)) == 4_500
    assert minor_units(intent(amount=6_40_000.0)) == 6_40_00_000

    # `amount_normalization` is an audit trail (§6.6 / Team A §5), never an arithmetic
    # input: `amount` is authoritative and the object only explains how it was read. B used
    # to compute `parsed_value * multiplier` instead, which an attacker who controls the
    # transcript controls both halves of — a crafted `{parsed_value: 1, multiplier: 1}` on a
    # ₹1 crore request would have landed under the ₹50,000 exemption and walked through PC-4.
    assert minor_units(intent(amount=4_500_000, amount_normalization={
        "raw_span": "45 lakh", "parsed_value": 4_500_000, "multiplier": 100_000,
        "rule": "lakh"})) == 450_000_000
    assert minor_units(intent(amount=1_00_00_000, amount_normalization={
        "raw_span": "one crore", "parsed_value": 1, "multiplier": 1,
        "rule": "hostile"})) == 1_00_00_00_000

    a = run(intent(amount=45.005))
    assert a.amount_minor_units is None
    assert {"PC-1", "PC-4"} <= _codes(a)               # unknown amount still needs a channel


def test_an_amount_we_cannot_parse_breaks_the_binding_too():
    """A pleasant consequence: `None` hashes differently from `45,00,000`.

    An amount that arrives in a form this system refuses to treat as money cannot match the
    pre-image the executive signed, so it surfaces as a critical delta rather than as a
    silently missing field.
    """
    a = run(intent(amount=45.005), reference=APPROVED)

    assert a.decision is Decision.BLOCK and a.override_applied == "HO-1"
    assert [d.field for d in a.fingerprint_deltas] == ["amount_minor_units"]
    assert a.fingerprint_deltas[0].severity == "critical"

#: Words that would tell an attacker reading one assessment how the duress scheme works.
LEAKY_WORDS = ("duress", "coerc", "marker", "phrase", "codeword", "code word", "safe word",
               "hostage", "under threat", "signal")


def test_duress_reads_approve_mints_nothing_and_names_nothing():
    """S09. Invariant 5: the requester sees a routine screen and no money can move.

    `decision` is APPROVE on purpose — an assessment that visibly refuses tells the person
    holding the phone that the marker was used. Safety comes from the absent capability
    token, not from a visible refusal, and C's executor cannot release funds without one.
    """
    a = run(reference=APPROVED, signals=bundle(duress_flag=True))

    assert a.decision is Decision.APPROVE
    assert a.duress_escalation is True
    assert a.capability_token is None                  # Invariant 5's teeth, and Invariant 9's
    assert a.requires_out_of_band_verification is True
    assert a.cooldown_seconds > 0                      # the delay is what buys the phone call

    text = " ".join([*a.risk_reasons, a.degraded_reason,
                     *(r.text for r in a.reasons_detailed)]).lower()
    for word in LEAKY_WORDS:
        assert word not in text, f"a duress assessment leaks {word!r}"


def test_duress_with_a_mismatch_blocks_the_money_and_still_escalates():
    """Refusing the payment is not the same as making the executive safe. Both happen."""
    a = run(intent(SWAPPED), reference=APPROVED, signals=bundle(duress_flag=True))

    assert a.decision is Decision.BLOCK and a.override_applied == "HO-1"
    assert a.duress_escalation is True
    assert a.capability_token is None
    assert "notify_security_officer" in a.required_actions


@pytest.mark.parametrize("case", [
    dict(),
    dict(reference=APPROVED),
    dict(signals=None),
    dict(signals=bundle(duress_flag=True)),
    dict(breaker_state=BreakerState.OPEN),
])
def test_assess_never_mints_a_capability_token(case):
    """Invariant 9 lives in `tokens/`, after an APPROVE. `assess()` is not allowed to shortcut it."""
    assert run(**case).capability_token is None

def test_the_preimage_is_exactly_the_twelve_frozen_fields():
    """Adding, dropping or renaming one silently invalidates every stored authorization."""
    fields = preimage_fields(intent(), executive_id="EXE-001", nonce="n", window_start="a",
                             window_end="b")
    assert tuple(fields) == FINGERPRINT_FIELDS
    assert fields["amount_minor_units"] == 450_000_000 and isinstance(
        fields["amount_minor_units"], int)
    assert fields["executive_id"] == "EXE-001"
    # An absent value is an explicit None, never an omitted key: the two hash differently.
    assert preimage_fields(intent(purpose=None))["purpose"] is None


def test_dimensions_returns_every_weight_key_exactly_once():
    for signals in (bundle(), None):
        dims = dimensions(intent(), signals)
        assert set(dims) == set(RISK_WEIGHTS)
        assert all(name == d.dimension for name, d in dims.items())


def test_degraded_mode_is_driven_by_the_two_frozensets():
    """One switch each. As a scorer or a verifier lands, its name leaves the set and the
    sentence disappears — the string cannot drift out of date because nobody maintains it."""
    a = run()
    assert a.degraded_mode is bool(STUBBED_DIMENSIONS or UNVERIFIED_CLAIMS)
    for name in STUBBED_DIMENSIONS | UNVERIFIED_CLAIMS:
        assert name in a.degraded_reason
    # With all four scorers landed there are no stub rows left; when the set is empty the
    # invariant is exactly "no row claims to be a stub".
    stub_rows = [r for r in a.contribution_table if r.factor in STUBBED_DIMENSIONS]
    if STUBBED_DIMENSIONS:
        assert stub_rows and all(r.raw_score == 50 and "not yet scored" in r.reason
                                 for r in stub_rows)
    else:
        assert all("not yet scored" not in r.reason for r in a.contribution_table)


def test_top_blocking_factor_names_the_rule_when_a_rule_refused():
    """A categorical refusal carries zero points, because it is not a score contribution."""
    blocked = run(intent(SWAPPED), reference=APPROVED).top_blocking_factor
    assert blocked.factor == "HO-1" and blocked.points == 0.0
    assert "destination account" in blocked.plain_english

    a = run()
    scored = a.top_blocking_factor
    assert scored.factor == "social_engineering"       # the heaviest row that could be scored
    # 14.0, not 10.5: `points` uses the RENORMALISED weight (`_row()` in fusion.py), and with
    # drift and device_channel abstaining on a first pass the coverage is 0.75, so this row's
    # effective weight is 0.15/0.75 = 0.20 against a raw 70. The nominal 0.15 still ships in
    # the contribution row — asserted here so the renormalisation stays visible, not implied.
    assert scored.points == pytest.approx(14.0, abs=1e-3)
    row = next(r for r in a.contribution_table if r.factor == "social_engineering")
    assert row.weight == pytest.approx(0.15, abs=1e-9)
    assert row.effective_weight == pytest.approx(0.20, abs=1e-6)
    assert "Social-engineering pressure" in scored.plain_english


def test_the_breaker_outranks_the_individual_assessment():
    a = run(reference=APPROVED, breaker_state=BreakerState.OPEN)
    assert a.decision is Decision.BLOCK
    assert a.override_applied == "BREAKER"
    assert a.hard_overrides_fired == ["BREAKER_TRIPPED"]
    assert a.breaker_state is BreakerState.OPEN
    assert a.required_actions == ["named_human_review"]

#: Every distinct path through `assess()`, for the invariants that must hold on all of them.
EVERY_PATH = [
    dict(),
    dict(reference=APPROVED),
    dict(signals=None),
    dict(signals=bundle(duress_flag=True)),
    dict(breaker_state=BreakerState.OPEN),
    dict(what=intent(SWAPPED), reference=APPROVED),
    dict(what=intent(amount=45.0)),
]


@pytest.mark.parametrize("case", EVERY_PATH)
def test_every_assessment_is_wire_valid_and_explains_itself(case):
    """Invariant 7 and the frozen vocabularies, on every path at once."""
    a = run(**case)

    assert a.decision.value in ("APPROVE", "CHALLENGE", "BLOCK")
    assert a.band_outcome.value in ("APPROVE", "CHALLENGE", "BLOCK")
    assert a.risk_reasons, "a populated score with no reasons violates Invariant 7"
    assert a.risk_reasons == [r.text for r in a.reasons_detailed]
    for r in a.reasons_detailed:
        assert r.code and r.text and r.evidence_ref
        assert r.severity in ("critical", "material", "cosmetic", "info")
    assert a.required_actions and set(a.required_actions) <= set(REQUIRED_ACTIONS)
    assert a.recommended_action == a.required_actions[0]
    assert "additional verification required" not in " ".join(a.risk_reasons).lower()
    assert 0.0 <= a.coverage <= 1.0 and 0 <= a.risk_score <= 100
    assert 0 <= a.intent_confidence <= 100
    assert a.policy_version == "1.0.0" and len(a.policy_hash) == 16
    assert a.assessed_at == clock.iso(NOW) and a.deterministic is True
    # B15 landed: the summary is the deterministic template (offline default), written
    # AFTER the decision and carrying the code-appended disclaimer. It is the one field
    # an LLM may author — and it must never carry a decision of its own.
    assert a.investigation_summary
    assert "did not influence the decision" in a.investigation_summary
    assert a.latency_ms == {}                 # timings are the service's business, not policy's


@pytest.mark.parametrize("case", EVERY_PATH)
def test_the_contribution_table_reconciles_with_the_published_score(case):
    """§10.3: a scorer whose parts do not add to its whole is a black box."""
    a = run(**case)
    total = sum(r.points for r in a.contribution_table)

    assert total == pytest.approx(a.risk_score, abs=0.5)
    for row in a.contribution_table:
        assert row.factor and (row.reason or row.abstain_reason)
        assert row.abstained is (row.points == 0.0 and row.effective_weight == 0.0)


@pytest.mark.parametrize("case", EVERY_PATH)
def test_no_path_approves_past_a_refusal(case):
    """The shapes that would let a categorical refusal release money anyway."""
    a = run(**case)

    if a.hard_overrides_fired and a.override_applied != "DURESS":
        assert a.decision is not Decision.APPROVE
    if a.fingerprint_status is FingerprintStatus.MISMATCH:
        assert a.decision is Decision.BLOCK
    if a.decision is Decision.APPROVE:
        assert a.capability_token is None      # minting is B10's, and it happens after this


def test_the_duress_fact_lives_in_structured_fields_and_never_in_prose():
    """Where the escalation is visible, and where it must not be — stated as a test.

    `duress_escalation` and `override_applied` are frozen §6.3/§6.6 fields: the security
    officer's console reads them, and C is responsible for not rendering them on the
    requester's screen. What B controls is the prose, and no reason string, remedy or
    degraded-mode note may name the scheme, the marker or its position. That is the half of
    the guarantee this module can actually enforce, so it is the half that is tested here.
    """
    a = run(reference=APPROVED, signals=bundle(duress_flag=True))

    assert a.duress_escalation is True and a.override_applied == "DURESS"
    prose = " ".join([*a.risk_reasons, a.degraded_reason, a.recommended_action,
                      *a.required_actions, a.channel_independence.explanation,
                      a.top_blocking_factor.plain_english if a.top_blocking_factor else ""])
    for word in LEAKY_WORDS:
        assert word not in prose.lower(), f"prose leaks {word!r}"
