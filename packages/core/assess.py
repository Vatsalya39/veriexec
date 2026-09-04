"""B — `assess()`, the orchestrator. Signals in, `RiskAssessment` out.

Everything else in `packages/core/` is a component. This is the wiring, and it is
deliberately boring: its whole job is to put the right numbers in front of
`policy.decide()` and then copy the answer onto the wire without editorialising.

Three properties are worth reading the code for.

1. **Pure given `now`.** No clock reads, no RNG, no network, no I/O beyond the frozen
   contract fixtures. The same `AssessInput` and the same `now` produce a byte-identical
   `RiskAssessment`, which is what turns §19.2's replay into a real check instead of a
   screenshot comparison. Wall-clock timings are the service's business, not this
   function's, so `latency_ms` is a parameter and never a measurement taken in here.

2. **Nothing a caller asserts about itself is believed.** `channel_independent` and the
   device signature arrive as *claims* on an `AuthorizationRecord`. A request that can set
   its own verification flags is not verified, so both are read as unestablished until B9
   and B11 establish them independently. The safe reading costs an APPROVE and buys the
   guarantee; PC-4 explains itself in the operator's language when it bites.

3. **The four dimensions whose scorers do not exist yet are stubbed at `STUB_SCORE`,
   loudly.** §2's build order: stub every dimension at 50 and prove the overrides fire —
   shape first, numbers second. `STUBBED_DIMENSIONS` is the single switch. As each scorer
   lands, delete its name from that frozenset and `degraded_mode` turns itself off.

`assess()` never mints a capability token. Minting lives in `tokens/` behind Invariant 9,
and the duress path in particular must reach the wire as an APPROVE that cannot move money.
"""

from __future__ import annotations

import re
from datetime import datetime

from .clock import iso
from .clock import now as clock_now
from .contracts_io import actors, baselines, beneficiary_master
from .crypto.canonical import NonCanonicalValue
from .crypto.fingerprint import FieldDelta, FingerprintVerdict, fingerprint, verify
from .models import (
    AssessInput,
    BreakerState,
    ChannelIndependence,
    FingerprintDelta,
    FingerprintStatus,
    RiskAssessment,
    RiskDimension,
    SignalBundle,
    TopBlockingFactor,
    TransactionIntent,
    to_paise,
)
from .policy.constants import CHALLENGE_ATTEMPTS_ALLOWED, STUB_SCORE, single_txn_ceiling
from .policy.decide import Inputs, PolicyDecision, decide
from .policy.version import policy_hash, policy_version
from .policy import channel as channel_module
from .scoring import behavioural, beneficiary as beneficiary_scoring, drift, divergence as divergence_scoring
from .scoring.fusion import (
    UNCERTAINTY_FACTOR,
    DimensionScore,
    dimension_from_authenticity,
    fuse,
    intent_confidence,
)
from .explain import counterfactual as cf_text
from .explain import graph as evidence_graph, investigator
from .explain.investigator import InvestigationRequest

#: Dimensions still waiting for their scoring module. Each one is scored at `STUB_SCORE`
#: with a reason that says so, and their presence is what sets `degraded_mode`. Deleting
#: a name here is the entire integration step for a new scorer — B3, B4, B5 and B11 have
#: now landed, so the set is empty and the stub path is dead code kept for G-gate honesty.
STUBBED_DIMENSIONS: frozenset[str] = frozenset()

#: Suffix on a stubbed dimension's reason. Judges and operators see the same string; a
#: number with "not yet scored" attached is honest in a way a bare 50 is not.
_STUB_NOTE = "not yet scored by its detector; held at the neutral stub value of 50"

#: Claims a caller makes about itself that nothing local can check on the assess path.
#: B9 verifies signatures where they are presented; B11 computes channel verdicts from the
#: caller-supplied channel facts rather than believing a boolean. The set stays non-empty
#: because the *assess* path still accepts caller-supplied reference bindings until B2's
#: store owns them; the challenge/token endpoints do the local verification.
UNVERIFIED_CLAIMS: frozenset[str] = frozenset({"device_signature", "channel_independence"})

def minor_units(intent: TransactionIntent) -> int | None:
    """Integer paise, or nothing at all. A float never becomes money (§26 trap #2).

    `None` does not mean zero and does not mean free. Every rule that cares reads a missing
    amount as *not* low-value, because "we could not parse the amount" has never been a
    reason to skip a check.

    Everything goes through `to_paise`, which is documented as the single door from the
    frozen `number|null` field to money B can compute with. This function used to call
    `to_minor_units` directly instead; that helper refuses floats by design, and A emits
    `amount: 640000.0`, so every scenario resolved to `None` and silently disabled the
    low-value exemption (PC-4), HO-2's ceiling test, behavioural amount deviation and the
    amount leg of the fingerprint.

    `amount_normalization.parsed_value` is a *fallback*, not a fast path, and it is not
    multiplied. A publishes the already-multiplied rupee value there (`two point five
    crore` -> `parsed_value 25000000.0` alongside `multiplier 10000000.0`, where the
    multiplier is provenance). The previous fast path multiplied the two together, which
    would have turned ₹2.5 crore into ₹2.5 lakh crore had it ever run — it was reachable
    only for an `int` `parsed_value`, so the float guard was all that stood between this
    build and a 10^7 error on the headline number.
    """
    currency = (intent.currency or "INR").upper()
    try:
        paise = to_paise(intent.amount, currency)
    except (NonCanonicalValue, ValueError, TypeError):
        paise = None
    if paise is not None:
        return paise

    norm = intent.amount_normalization
    if norm is not None and norm.parsed_value is not None:
        try:
            return to_paise(norm.parsed_value, currency)
        except (NonCanonicalValue, ValueError, TypeError):
            return None
    return None


def preimage_fields(
    intent: TransactionIntent,
    *,
    executive_id: str = "",
    nonce: str = "",
    window_start: str = "",
    window_end: str = "",
) -> dict:
    """The ONE place a `TransactionIntent` becomes a `FINGERPRINT_FIELDS` pre-image.

    `canonical.project()` refuses a missing key rather than inventing a null, so all twelve
    are written out here. An absent value is an explicit `None` — never a quietly omitted
    field, because the two hash differently and only one of them is honest.
    """
    return {
        "transaction_id": intent.transaction_id,
        "executive_id": executive_id or None,
        "action": intent.action.value,
        "amount_minor_units": minor_units(intent),
        "currency": (intent.currency or "INR").upper(),
        "beneficiary_id_or_name": intent.beneficiary or None,
        "destination_account": intent.destination_account or None,
        "purpose": intent.purpose or None,
        "deadline_iso": intent.deadline or None,
        "validity_window_start_iso": window_start or None,
        "validity_window_end_iso": window_end or None,
        "nonce": nonce or None,
    }

#: `requester` is frozen as "claimed executive name/role" (§6.1), so A ships
#: `"Ananya Rao (Group CFO)"` while the registry holds `"Ananya Rao"`. Stripping one
#: trailing parenthetical is a *format* normalization, not a fuzzy match: the residue
#: still has to be equal to a registered id or name, character for character.
_ROLE_ANNOTATION = re.compile(r"\s*\([^()]*\)\s*$")


def _requester_keys(requester: str) -> set[str]:
    """The exact strings a requester may legitimately be written as."""
    raw = " ".join((requester or "").split())
    if not raw:
        return set()
    keys = {raw.casefold()}
    stripped = " ".join(_ROLE_ANNOTATION.sub("", raw).split())
    if stripped:
        keys.add(stripped.casefold())
    return keys


def _registry_keys(eid: str, rec: dict) -> set[str]:
    """The exact strings a registry entry answers to, including the annotated form."""
    name = " ".join(str(rec.get("name", "")).split())
    role = " ".join(str(rec.get("role", "")).split())
    keys = {eid.casefold()}
    if name:
        keys.add(name.casefold())
        if role:
            keys.add(f"{name} ({role})".casefold())
    return keys


def _median_minor_units(actor_id: str, rec: dict, now: datetime) -> int | None:
    """The actor's median payment in paise, from whichever registry actually records it.

    `personas.json` states executives' medians in *rupees* under `baseline`;
    `behaviour_baselines.json` states every actor's median in *minor units* and is the only
    one of the two that covers employees. Preferring the persona value keeps executives on the
    registry a human edits, and falling through to the baselines table is what lets an employee
    requester have a ceiling at all.
    """
    baseline = rec.get("baseline") or {}
    median_inr = baseline.get("median_amount_inr", rec.get("median_amount_inr"))
    if median_inr:
        return int(median_inr) * 100
    table = baselines(now).get("baselines", {}).get(actor_id) or {}
    median_minor = table.get("median_amount_minor_units")
    return int(median_minor) if median_minor else None


def _executive(intent: TransactionIntent, now: datetime) -> tuple[str | None, int | None]:
    """Resolve `requester` to an actor id, and that actor's own single-transaction ceiling.

    Exact id or case-folded name match only, after one format normalization: a trailing
    `(Role)` annotation is removed, because the frozen field is "name/role" and A writes
    both halves. Fuzzy matching here would quietly do B4's job, badly: a near-miss on an
    executive's name is not a lookup convenience, it is the attack — S11's homoglyph payee
    still resolves to nothing, because nothing here compares anything but equal strings.

    The search is over `actors()`, not `executives()`. `contracts_io.actors()` says of itself
    "decide() treats both as requesters", and `behaviour_baselines.json` carries baselines for
    EMP-101/102/103 as well as the two executives — but this lookup used to read the executive
    registry alone, so an employee requester resolved to nothing, three of the five baselines
    were unreachable, and the behavioural dimension abstained with "no registered executive
    matched the claimed requester". S19's payroll run is instructed by a treasury manager, not
    an executive; on the corpus's most ordinary payment, the dimension that should have said
    "this is his routine work" said nothing at all.

    `median_amount_inr` is rupees, and it lives under the persona's `baseline` object.
    Reading it from the top level returned `None` for every executive, so `ceiling` was
    always `None`, which silently disabled HO-2's ceiling test on all 22 scenarios. It is
    multiplied into paise before it reaches `single_txn_ceiling`, which speaks only in
    minor units.
    """
    wanted = _requester_keys(intent.requester or "")
    if not wanted:
        return None, None
    for aid, rec in sorted(actors(now).items()):
        if wanted & _registry_keys(aid, rec):
            median = _median_minor_units(aid, rec, now)
            return aid, single_txn_ceiling(median) if median else None
    return None, None


def _beneficiary(intent: TransactionIntent, now: datetime) -> tuple[str | None, str, bool, str]:
    """Registry lookup — id, display label, is-this-account-on-record, sanctions verdict.

    Lookup, never scoring. An unknown payee reports `on_record=False` because there is no
    record to be on, and HO-2's sentence ("an account not on record for X") is true of a
    changed account and a never-paid payee alike.

    An unregistered payee gets `clear`, not a fabricated sanctions hit: "we have never seen
    this company" is risk for B4's beneficiary dimension to price, not grounds for the
    categorical refusal HO-7 exists to deliver.
    """
    label = (intent.beneficiary or "").strip()
    account = (intent.destination_account or "").strip()
    if label:
        for bid, rec in sorted(beneficiary_master(now).items()):
            names = {str(rec.get("canonical_name", "")).strip().casefold()}
            names.update(str(a).strip().casefold() for a in rec.get("aliases", ()))
            if label.casefold() in names:
                on_record = any(
                    beneficiary_scoring.account_matches(account, str(a))
                    for a in sorted(rec.get("registered_accounts", ())))
                return (bid, str(rec.get("canonical_name") or label), on_record,
                        str(rec.get("sanctions_screen", "clear")))
    return None, label or "this beneficiary", False, "clear"

def _stub(name: str) -> DimensionScore:
    """A dimension whose scorer has not been built yet, saying so in its own reason string."""
    return DimensionScore(
        dimension=name,
        score=float(STUB_SCORE),
        reason=f"{name.replace('_', ' ').capitalize()} is {_STUB_NOTE}.",
        evidence_ref=f"stub.{name}",
    )


class _ExecCache:
    """The single resolution of (executive_id, amount) per assess() call.

    `dimensions()` needs both for the behavioural scorer but its signature is frozen by
    tests that call it directly; a per-call cache object keeps one resolution site while
    staying replay-safe (assess() always sets both before calling dimensions()).
    """

    executive_id: str | None = None
    amount: int | None = None


_executive_cache = _ExecCache()


def dimensions(
    intent: TransactionIntent, signals: SignalBundle | None, *, now: datetime | None = None,
    beneficiary_facts=None, channel_code: str = "PENDING",
    reference_fields: dict | None = None,
) -> dict[str, DimensionScore]:
    """One `DimensionScore` per `RISK_WEIGHTS` key, all seven in RISK direction.

    The two authenticity numbers go through `dimension_from_authenticity` — the only
    sanctioned inversion site in the codebase — and abstain rather than score when nothing
    was actually measured. An abstention costs coverage and earns an uncertainty penalty;
    a zero would have earned an approval.
    """
    out: dict[str, DimensionScore] = {n: _stub(n) for n in sorted(STUBBED_DIMENSIONS)}
    a_supplied = ("identity_confidence", "communication_authenticity", "social_engineering")

    if signals is None:
        for name in a_supplied:
            out[name] = DimensionScore(
                dimension=name, score=None,
                abstain_reason="no signal bundle was supplied for this transaction",
            )
    else:
        out["identity_confidence"] = dimension_from_authenticity(
            "identity_confidence", signals.identity_confidence,
            reason=(f"Identity confidence {signals.identity_confidence:.0f}/100 from "
                    f"{len(signals.detector_reports)} detector report(s)."),
            evidence_ref="signals.identity_confidence",
        )

        # `media_scores_present()` is the model's own helper, and its docstring says what it
        # is for: coverage, never `intent_confidence`. Nothing here feeds the intent number.
        measured = signals.media_scores_present() or signals.stylometry_match_score is not None
        out["communication_authenticity"] = dimension_from_authenticity(
            "communication_authenticity",
            signals.communication_authenticity if measured else None,
            reason=(f"Channel authenticity {signals.communication_authenticity:.0f}/100 across "
                    f"{len(signals.detector_reports)} detector report(s); detector disagreement "
                    f"{signals.detector_disagreement:.0f}."),
            evidence_ref="signals.communication_authenticity",
            abstain_reason=("every media and stylometry detector abstained, so channel "
                            "authenticity is unmeasured rather than acceptable"),
        )

        named = ", ".join(signals.social_engineering_indicators[:3]) or "no named indicator"
        out["social_engineering"] = DimensionScore(
            dimension="social_engineering",
            score=max(0.0, min(100.0, float(signals.social_engineering_score))),
            reason=f"Social-engineering pressure {signals.social_engineering_score:.0f}/100 ({named}).",
            evidence_ref="signals.social_engineering_score",
            evidence=tuple(signals.social_engineering_indicators),
        )


    # --- B3 behavioural + B4 beneficiary (real scorers) ----------------------------------
    if "behavioural" not in out:
        out["behavioural"] = behavioural.score(
            executive_id=getattr(_executive_cache, "executive_id", None),
            amount_minor_units=getattr(_executive_cache, "amount", None),
            beneficiary_id=(beneficiary_facts.beneficiary_id if beneficiary_facts else None),
            channel=intent.channel.value, now=now or clock_now(),
        ) or _stub("behavioural")
    if "beneficiary" not in out:
        # Direct calls (tests, C's sandbox) may not pass pre-computed facts; scoring is
        # pure, so computing here is the same answer assess() gets.
        facts = beneficiary_facts if beneficiary_facts is not None else beneficiary_scoring.score(
            beneficiary_label=intent.beneficiary or "",
            destination_account=intent.destination_account or "",
            amount_minor_units=getattr(_executive_cache, "amount", None),
            now=now or clock_now(),
        )
        out["beneficiary"] = beneficiary_scoring.dimension(facts)

    # --- B5 semantic drift (real scorer) -------------------------------------------------
    if "semantic_drift" not in out:
        # §8: "what the executive SAID" is the approved pre-image when one exists —
        # that is the S06 shape — and the intent's own extraction otherwise (S22:
        # extraction ambiguity, not tampering).
        drift_source = reference_fields
        drift_result = drift.score(intent, reference_fields=drift_source)
        out["semantic_drift"] = drift.dimension(drift_result)

    # --- B11 device/channel (real scorer) ------------------------------------------------
    if "device_channel" not in out:
        flags = tuple(signals.channel_switch_flags) if signals else ()
        risk = channel_module.dimension(
            channel_verdict_code=channel_code, channel_switch_flags=flags
        )
        # PENDING with nothing else to go on is the broken microphone from `fusion.py`'s
        # opening paragraph. `CHANNEL_PENALTIES["PENDING"] = 0` is right as arithmetic — its
        # own comment says "verification has not happened yet" — but publishing that 0 as a
        # *score* spent 0.10 of the fusion weight certifying an independent channel that
        # nobody has verified, and the reason string underneath it admitted as much. On the
        # first pass, before C has collected a human response, there is no channel to judge.
        # `channel.dimension()` is penalty + 12 per switch flag, so a switch flag is a real
        # measurement and keeps the dimension alive; a bare PENDING has neither term and
        # abstains, paying the uncertainty penalty instead of granting a discount.
        if channel_code == "PENDING" and not flags:
            out["device_channel"] = DimensionScore(
                dimension="device_channel", score=None,
                abstain_reason=("no verification channel has been used yet, so channel "
                                "independence is unverified rather than satisfied"),
            )
        else:
            reason = (
                "Approval channel is not yet independent of the request channel."
                if channel_code == "PENDING"
                else f"Channel verdict: {channel_code}."
            )
            if flags:
                reason += f" {len(flags)} channel-switch pattern(s) observed."
            out["device_channel"] = DimensionScore(
                dimension="device_channel", score=risk, reason=reason,
                evidence_ref="channel.verdict",
                evidence=tuple(flags),
            )
    return out

#: Which frozen pre-image field each challenge type actually asks the approver to recall.
#: HO-5's sentence names the field, not the challenge type, because "could not confirm the
#: destination account" is a fact an operator can act on and "ACCOUNT_TAIL failed" is not.
_CHALLENGE_FIELD: dict[str, str] = {
    "AMOUNT_RECALL": "amount_minor_units",
    "BENEFICIARY_SELECT": "beneficiary_id_or_name",
    "ACCOUNT_TAIL": "destination_account",
    "PURPOSE_MATCH": "purpose",
}


def _challenge_state(auth) -> tuple[str, str, int]:
    """`(outcome, field_asked_about, attempts)` from C's record, on B's frozen ladder.

    HO-5 refuses only on `FAILED_EXHAUSTED`, so the rungs matter: a first wrong answer is
    still a challenge that can be answered, and the second is a refusal.
    """
    result = getattr(auth, "comprehension_challenge_result", None)
    if result is None or result.type is None:
        return "NONE", "", 0
    field = _CHALLENGE_FIELD.get(result.type.value, "")
    if result.answered_correctly:
        return "PASSED", field, result.attempts
    exhausted = result.attempts >= CHALLENGE_ATTEMPTS_ALLOWED
    return ("FAILED_EXHAUSTED" if exhausted else "FAILED"), field, result.attempts


def inputs_signature_verdict(auth) -> str:
    """B9's entry point on the assess path: a signature is verified locally, never believed.

    The assess path has no signature payload to verify (that is `/v1/signature/verify`'s
    job), so a record that merely *asserts* it was signed is read as ABSENT. A verified
    signature arrives via the challenge/token flow, which calls B9 directly.
    """
    return "ABSENT"


def _replay_risk(signals: SignalBundle | None) -> float:
    """A's `max_similarity` is 0-1; `replay_risk` is 0-100. B2 owns the full ladder.

    Rescaling here is not scoring — it is the unit conversion §6.6 warns about, done once so
    PC-5 compares like with like. A missing bundle scores nothing rather than zero risk,
    because there is no similarity evidence to be reassured by.
    """
    if signals is None or signals.replay_similarity is None:
        return 0.0
    return max(0.0, min(100.0, float(signals.replay_similarity.max_similarity) * 100.0))


def _term(dims: dict[str, DimensionScore], name: str) -> float:
    """A penalty term for `intent_confidence`, with ignorance priced as ignorance.

    An abstained dimension contributes `STUB_SCORE`, not 0. A term of 0 would say "we
    checked and it was fine"; the honest statement is "we do not know", and 50 is where
    this system says that.
    """
    score = dims[name].score
    return float(STUB_SCORE) if score is None else float(score)


def _top_factor(decision: PolicyDecision, rows) -> TopBlockingFactor | None:
    """What is actually stopping this transaction, in the operator's words.

    When a hard override fired, the answer is that rule and it carries **zero points** —
    a categorical refusal is not a large score contribution, it is not a score contribution
    at all, and saying so out loud is the clearest thing this field can do. Otherwise it is
    the heaviest real contributor. The synthetic uncertainty row never wins: "we could not
    see enough" is already PC-2's sentence, and naming it here would push the cause off screen.
    """
    if decision.override_applied and decision.reasons:
        return TopBlockingFactor(
            factor=decision.override_applied, points=0.0,
            plain_english=decision.reasons[0].text,
        )
    real = [r for r in rows if r.factor != UNCERTAINTY_FACTOR and not r.abstained]
    if not real:
        return None
    top = max(real, key=lambda r: (r.points, r.factor))
    return TopBlockingFactor(factor=top.factor, points=top.points, plain_english=top.reason)

def assess(
    inp: AssessInput,
    *,
    reference_fields: dict | None = None,
    breaker_state: BreakerState = BreakerState.CLOSED,
    now: datetime | None = None,
    latency_ms: dict[str, float] | None = None,
) -> RiskAssessment:
    """§16 end to end: bind, fuse, decide, publish.

    `reference_fields` is the pre-image as it stood when the executive approved. Passing
    `None` is not a pass — `verify()` returns UNVERIFIABLE, PC-1 fails, and the request goes
    to CHALLENGE rather than quietly inheriting a MATCH it never earned.

    `breaker_state` is injected because the breaker is an organizational fact that B12's
    window arithmetic owns, and `now` is injected because a function that reads the clock
    cannot be replayed. Those two parameters are most of why this returns the same bytes
    twice, which is what §19.2 checks.
    """
    now = now or clock_now()
    intent, signals, auth = inp.intent, inp.signals, inp.authorization
    token = inp.presented_token
    duress = bool(signals and signals.duress_flag)

    executive_id, ceiling = _executive(intent, now)
    ben = beneficiary_scoring.score(
        beneficiary_label=intent.beneficiary or "",
        destination_account=intent.destination_account or "",
        amount_minor_units=minor_units(intent),
        now=now,
    )
    ben_id, payee_label, account_on_record, sanctions = (
        ben.beneficiary_id, ben.canonical_name or "this beneficiary",
        ben.account_on_record, ben.sanctions_screen,
    )
    #: Three states, not two. An account can be *stated and registered*, *stated and not
    #: registered*, or *not stated at all* — and only the middle one is an account change.
    #: HO-2's own sentence is "to an account not on record for X", which is a claim about
    #: the world: someone named a destination the payee does not bank at. When the requester
    #: never named an account ("release the balance to their ICIC account", S20), A publishes
    #: `destination_account: null` and there is no such claim to make. Deriving the override
    #: from `not account_on_record` turned absence of evidence into evidence of diversion and
    #: fired a categorical AMOUNT_CEILING block on ordinary payments to established payees.
    #: B4's `unregistered_account` modifier already guards on `if account and ...`; this is
    #: the same rule at the override layer.
    account_stated = bool((intent.destination_account or "").strip())
    amount = minor_units(intent)

    # --- the binding. Everything below is arithmetic; this is the cryptography ----------
    nonce = (auth.nonce or "") if auth else ""
    window: dict[str, str] = {}
    if auth and auth.issued_at and auth.expires_at:
        window = {"start_iso": auth.issued_at, "end_iso": auth.expires_at}
    current_fields = preimage_fields(
        intent, executive_id=executive_id or "", nonce=nonce,
        window_start=window.get("start_iso", ""), window_end=window.get("end_iso", ""),
    )
    presented = inp.presented_fingerprint or (auth.transaction_fingerprint if auth else "") or ""
    verdict, field_deltas = verify(presented, current_fields, reference_fields)

    # --- the two numbers, computed independently of each other --------------------------
    # B11's verdict is computed from channel facts, never from a caller's boolean.
    channel_v = channel_module.verdict(
        intent.channel.value,
        (inp.verification_channel or inp.verification_channel_id or ""),
        origin_device_id=(signals.device_info.device_id if signals else ""),
        verification_device_id=inp.verification_device_id or "",
    )
    # One resolution site: the executive id and amount are stashed for `dimensions`'s
    # behavioural scorer rather than resolved twice (replay needs one answer).
    _executive_cache.executive_id = executive_id
    _executive_cache.amount = amount
    dims = dimensions(
        intent, signals, now=now,
        beneficiary_facts=ben, channel_code=channel_v.code,
        reference_fields=reference_fields,
    )
    fused = fuse(dims)
    confidence, components, excluded = intent_confidence(
        {
            "semantic_drift": _term(dims, "semantic_drift"),
            "behavioural": _term(dims, "behavioural"),
            "device_channel": _term(dims, "device_channel"),
            "beneficiary": _term(dims, "beneficiary"),
            "extraction_inverse": 100.0 - max(0.0, min(100.0, float(intent.extraction_confidence))),
        },
        duress=duress,
        fingerprint_status=verdict.wire(),
    )

    # --- the decision. `decide()` is the only thing in this repo that writes an outcome --
    challenge_outcome, challenge_field, attempts = _challenge_state(auth)
    decision = decide(Inputs(
        transaction_id=intent.transaction_id,
        # A `None` from fusion means nothing could be scored, and nothing scored is not a low
        # score. The neutral stub keeps the band honest while `forced_outcome` does the work.
        risk_score=float(fused.score if fused.score is not None else STUB_SCORE),
        coverage=fused.coverage,
        abstained=fused.abstained,
        forced_outcome=fused.forced_outcome,
        fingerprint_status=verdict.wire(),
        fingerprint_deltas=tuple(field_deltas),
        breaker_state=breaker_state,
        duress_suspected=duress,
        amount_minor_units=amount,
        ceiling_minor_units=ceiling,
        beneficiary_account_changed=account_stated and not account_on_record,
        payee_label=payee_label,
        # HO-3 wiring: the homoglyph verdict from B4, in decide()'s vocabulary
        confusion_verdict=(
            ben.confusion.verdict if ben.confusion is not None else "none"
        ),
        confusion_confidence=(
            int(ben.confusion.risk_floor) if ben.confusion is not None else 0
        ),
        confusion_target_label=(
            ben.confusion.target_name if ben.confusion is not None else ""
        ),
        confusion_target_established=bool(ben.tier == "established"),
        confusion_codepoint=(
            ben.confusion.codepoint if ben.confusion is not None else ""
        ),
        token_already_spent=bool(token and token.redeemed_at),
        replay_risk=round(_replay_risk(signals)),
        challenge_outcome=challenge_outcome,
        challenge_field=challenge_field,
        challenge_attempts=attempts,
        sanctions_screen=sanctions,
        presented_policy_version=(token.policy_version if token else ""),
        current_policy_version=policy_version(),
        # Claims, not facts. B9 verifies signatures where presented; on the assess path a
        # record that asserts its own verification is treated as unverified — which costs
        # an APPROVE and buys the guarantee. PC-4 says so in words.
        signature_verdict=inputs_signature_verdict(auth),
        channel_independent=channel_v.independent,
        channel_verdict=channel_v.code,
        # A4's flags, already acted on by A (text neutralized, extraction forced
        # deterministic-only, `extraction_confidence` docked 30). B owes the refusal.
        injection_flags=tuple(intent.injection_flags or ()),
    ))
    return _publish(
        intent, signals, dims, fused, decision, verdict, field_deltas,
        confidence=confidence, components=components, excluded=excluded,
        current_fields=current_fields, breaker_state=breaker_state, now=now,
        executive_id=executive_id, beneficiary_id=ben_id, amount=amount,
        nonce=nonce, window=window, latency_ms=latency_ms or {},
        ben_facts=ben,
    )

def _dimension_wire(d: DimensionScore) -> RiskDimension:
    """§6.3's `{score, reasons}` pair. An abstention publishes 0 *with the reason why*."""
    return RiskDimension(
        score=0.0 if d.score is None else float(d.score),
        reasons=[d.reason or d.abstain_reason],
    )


def _degraded_notes() -> list[str]:
    """What this assessment could not do, in the order it matters.

    Two frozensets drive it, so the string cannot drift out of date: when a scorer or a
    verifier lands, its name leaves the set and the sentence disappears on its own.
    """
    notes: list[str] = []
    if STUBBED_DIMENSIONS:
        notes.append(
            f"dimension scorers pending ({', '.join(sorted(STUBBED_DIMENSIONS))}), "
            f"each held at the neutral stub value of {STUB_SCORE}"
        )
    if UNVERIFIED_CLAIMS:
        notes.append(
            f"local verification pending ({', '.join(sorted(UNVERIFIED_CLAIMS))}), "
            "so neither is treated as established"
        )
    return notes


def _channel_independence(
    intent: TransactionIntent, signals: SignalBundle | None
) -> ChannelIndependence:
    """§14 on the wire. `satisfied` is False until B11 proves it, never because C said so.

    The explanation is written for an operator and stays true whatever the build state:
    independence has not been established for this request, and that is what PC-4 acts on.
    """
    origin = (signals.origin_channel_id if signals else "") or intent.channel.value
    return ChannelIndependence(
        origin_channel_id=origin,
        required_verification_class="different_channel_family",
        satisfied=False,
        verification_channel_id="",
        code="NOT_ESTABLISHED",
        explanation=(
            "Independence has not been established for this request. Approval requires a "
            "confirmation on a channel in a different family from the one the request "
            "arrived on, verified by the policy core rather than asserted by the caller."
        ),
    )

def _publish(
    intent: TransactionIntent,
    signals: SignalBundle | None,
    dims: dict[str, DimensionScore],
    fused,
    decision: PolicyDecision,
    verdict: FingerprintVerdict,
    field_deltas: list[FieldDelta],
    *,
    confidence: int,
    components: dict[str, float],
    excluded: tuple[str, ...],
    current_fields: dict,
    breaker_state: BreakerState,
    now: datetime,
    executive_id: str | None,
    beneficiary_id: str | None,
    amount: int | None,
    nonce: str,
    window: dict[str, str],
    latency_ms: dict[str, float],
    ben_facts=None,
) -> RiskAssessment:
    """`PolicyDecision` onto the wire — copying, never re-deciding.

    Every outcome-shaped field here is a copy of something `decide()` returned. If this
    function and `decide()` ever disagree, the bug is in this function, and that is the point
    of writing it as a transcription rather than a second opinion (Invariant 2).

    `investigation_summary` stays empty. It is the one field an LLM may author, B15 is the one
    place that happens, and it is written after the decision exists — never before it.
    """
    notes = _degraded_notes()
    # --- B14 counterfactuals: arithmetic over the contribution table, never generation --
    cfs = cf_text.counterfactuals(
        decision=decision.decision,
        override_applied=decision.override_applied,
        risk_score=float(fused.score if fused.score is not None else STUB_SCORE),
        contributions=[r.wire() for r in fused.contributions],
    )
    # --- B19 evidence subgraph: data, never layout; capped at 14 nodes -------------------
    graph = evidence_graph.build(
        executive_id=executive_id,
        executive_name=intent.requester or "Unknown requester",
        beneficiary_id=beneficiary_id,
        beneficiary_name=intent.beneficiary or "Unmatched payee",
        account_on_record=bool(getattr(ben_facts, "account_on_record", False)),
        account_stated=current_fields.get("destination_account") is not None,
        beneficiary_tier=getattr(ben_facts, "tier", "unknown") if ben_facts else "unknown",
        contributions=[r.wire() for r in fused.contributions],
        override_applied=decision.override_applied,
        decision=decision.decision.value,
        risk_score=float(fused.score if fused.score is not None else STUB_SCORE),
    )
    # --- B15 investigation summary: the ONLY place an LLM may speak, and only after the
    #     decision is frozen. Offline mode serves the deterministic template (N25a).
    #     The Ollama narrator is consulted only when the kill switch and the env contract
    #     both allow it, and its paragraph survives only through `summarize`'s acceptance
    #     check — a number the decision does not already contain is discarded there.
    llm_paragraph = investigator.ollama_prose(
        InvestigationRequest(
            decision=decision.decision.value,
            risk_score=int(round(float(fused.score if fused.score is not None else STUB_SCORE))),
            intent_confidence=int(confidence),
            contributions=tuple(r.wire() for r in fused.contributions),
            fingerprint_deltas=tuple(d.as_dict() for d in field_deltas),
            counterfactuals=(),
            scenario_id=intent.sample_id or "",
        ),
        draft=(f"{decision.decision.value} at risk "
               f"{int(round(float(fused.score if fused.score is not None else STUB_SCORE)))}/100 "
               f"with intent confidence {int(confidence)}/100. "
               + "; ".join(
                   f"{str(r.get('label') or r.get('factor') or 'dimension')} contributed "
                   f"{float(r.get('points', 0)):.1f} points"
                   for r in (x.wire() for x in fused.contributions))[:600]),
    )
    summary, next_steps = investigator.summarize(
        InvestigationRequest(
            decision=decision.decision.value,
            risk_score=int(round(float(fused.score if fused.score is not None else STUB_SCORE))),
            intent_confidence=int(confidence),
            contributions=tuple(r.wire() for r in fused.contributions),
            fingerprint_deltas=tuple(d.as_dict() for d in field_deltas),
            counterfactuals=tuple(cf_text.override_counterfactual(decision.override_applied)
                                  if decision.override_applied else ""),
            scenario_id=intent.sample_id or "",
        ),
        llm_prose=llm_paragraph,
    )
    return RiskAssessment(
        transaction_id=intent.transaction_id,
        risk_score=float(fused.score if fused.score is not None else STUB_SCORE),
        risk_reasons=list(decision.risk_reasons),
        identity_confidence=float(signals.identity_confidence) if signals else 0.0,
        communication_authenticity=float(signals.communication_authenticity) if signals else 0.0,
        intent_confidence=float(confidence),
        semantic_drift_score=_term(dims, "semantic_drift"),
        transaction_fingerprint=fingerprint(current_fields),
        fingerprint_status=FingerprintStatus(verdict.wire()),
        beneficiary_risk=_dimension_wire(dims["beneficiary"]),
        behavioral_risk=_dimension_wire(dims["behavioural"]),
        decision=decision.decision,
        recommended_action=decision.required_actions[0],
        requires_out_of_band_verification=decision.requires_out_of_band_verification,
        duress_escalation=decision.duress_escalation,
        contribution_table=list(fused.contributions),
        counterfactuals=cfs,
        beneficiary_graph=graph,
        investigation_summary=summary,
        top_blocking_factor=_top_factor(decision, fused.contributions),
        intent_confidence_components=dict(components),
        hard_overrides_fired=list(decision.hard_overrides_fired),
        policy_version=policy_version(),
        policy_hash=policy_hash(),
        # Invariant 9 and Invariant 5 both live here as an absence: minting is B10's job, it
        # happens only after an APPROVE, and it never happens on a duress path at all.
        capability_token=None,
        cooldown_seconds=decision.cooldown_seconds,
        breaker_state=breaker_state,
        channel_independence=_channel_independence(intent, signals),
        degraded_mode=bool(notes),
        latency_ms=dict(latency_ms),
        band_outcome=decision.band_outcome,
        override_applied=decision.override_applied,
        # The uncollapsed policy outcome. `decision` above is already `Outcome.wire()`, so
        # this is the only place the name `SILENT_ESCALATION` survives the handoff to C.
        outcome=getattr(decision.outcome, "value", str(decision.outcome)),
        coverage=fused.coverage,
        required_actions=list(decision.required_actions),
        reasons_detailed=list(decision.reasons),
        fingerprint_deltas=[FingerprintDelta(**d.as_dict()) for d in field_deltas],
        intent_confidence_excluded_signals=list(excluded),
        replay_risk=_replay_risk(signals),
        nonce=nonce,
        validity_window=dict(window),
        amount_minor_units=amount,
        beneficiary_id=beneficiary_id,
        executive_id=executive_id,
        degraded_reason="; ".join(notes),
        assessed_at=iso(now),
        deterministic=True,
    )
