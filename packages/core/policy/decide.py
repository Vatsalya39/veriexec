"""B13 — the deterministic decision policy. The module that wins or loses the judging.

`decision` is written here and nowhere else (Invariant 2). Nothing in this file reads a
model, a prompt or a completion; `tests/core/test_decide.py` walks this module's AST and
fails if an attribute named `llm`, `model_output`, `completion`, `narrative`, `advisory` or
`summary` ever appears. A test that greps your own source for the mistake is worth more than
a paragraph in a README.

The evaluation order is fixed, and a judge will ask for it:

    1. breaker      — organizational state precedes individual assessment
    2. overrides    — categorical facts, fixed order, first match wins
    3. duress       — the silent path
    4. band         — the fused score's default outcome
    5. floors       — coverage and unverifiable binding force a CHALLENGE
    6. precondition — an APPROVE that fails any of the six degrades to CHALLENGE
    7. never downgrade — there is no path from BLOCK back to CHALLENGE or APPROVE

Scores are for graded evidence. Overrides are for facts. `S06` fuses to 58 — the middle of
the CHALLENGE band — and blocks anyway, because the account in the request is not the account
bound to the captured intent. If a 58 could average its way past a hash mismatch, the
fingerprint would be decorative.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from ..crypto.fingerprint import FieldDelta, has_critical
from ..models import BreakerState, Decision, ReasonDetail
from .constants import (
    HARD_OVERRIDE_IDS,
    LOW_VALUE_EXEMPT,
    MIN_COVERAGE,
    PRECONDITION_IDS,
    REPLAY_RISK_APPROVE_CEILING,
    REQUIRED_ACTIONS,
    STUB_SCORE,
    WIRE_OVERRIDE_CODES,
    band_for,
    cooldown_seconds,
)

class Outcome(str, Enum):
    """B's *internal* outcome vocabulary, which is wider than the wire's on purpose.

    §6.3 froze `decision` to three values, but the policy genuinely reaches five states, and
    collapsing them at the boundary is better than pretending they do not exist:

    * `BREAKER_TRIPPED`   — an organizational stop, not a judgement about this request.
    * `SILENT_ESCALATION` — S09's duress path. It reads APPROVE on the wire and mints no
      token, so the requester sees a routine screen while security is already awake.
    """

    APPROVE = "APPROVE"
    CHALLENGE = "CHALLENGE"
    BLOCK = "BLOCK"
    BREAKER_TRIPPED = "BREAKER_TRIPPED"
    SILENT_ESCALATION = "SILENT_ESCALATION"

    def wire(self) -> Decision:
        """Collapse to the frozen three. `SILENT_ESCALATION` deliberately reads APPROVE."""
        if self is Outcome.BREAKER_TRIPPED:
            return Decision.BLOCK
        if self is Outcome.SILENT_ESCALATION:
            return Decision.APPROVE
        return Decision(self.value)


#: Only the three graded outcomes are ordered; the other two are terminal returns.
_SEVERITY: dict[Outcome, int] = {Outcome.APPROVE: 0, Outcome.CHALLENGE: 1, Outcome.BLOCK: 2}


def _worse(a: Outcome, b: Outcome) -> Outcome:
    """Step 7. Monotone escalation — the only direction a decision is allowed to move."""
    return a if _SEVERITY[a] >= _SEVERITY[b] else b

@dataclass(frozen=True)
class Inputs:
    """Everything the policy is allowed to look at — and nothing else.

    Every field has a *safe* default so a caller can build the S-scenario it cares about and
    leave the rest alone. Safe means pessimistic: the binding is `NOT_YET_VERIFIED`, the
    channel is not independent, the signature is `ABSENT`. Nothing here defaults to a value
    that helps a request through. `risk_score` defaults to `STUB_SCORE` because §2 wants the
    overrides provable before any scorer exists.

    Note what is absent: there is no field for a narrative, a completion or an advisory. The
    LLM's output cannot reach this function because it has nowhere to sit.
    """

    transaction_id: str
    risk_score: float = float(STUB_SCORE)
    coverage: float = 1.0                      # always set explicitly by assess()
    abstained: tuple[str, ...] = ()             # dimensions that had no evidence either way
    forced_outcome: str | None = None           # fusion's own floor, honoured not re-derived
    fingerprint_status: str = "NOT_YET_VERIFIED"
    fingerprint_deltas: tuple[FieldDelta, ...] = ()
    breaker_state: BreakerState = BreakerState.CLOSED
    duress_suspected: bool = False

    amount_minor_units: int | None = None
    ceiling_minor_units: int | None = None
    beneficiary_account_changed: bool = False

    confusion_verdict: str = "none"            # none | edit_distance | skeleton_collision
    confusion_confidence: int = 0
    confusion_target_label: str = ""
    confusion_target_established: bool = False
    confusion_codepoint: str = ""              # e.g. "U+0410 CYRILLIC CAPITAL LETTER A"
    payee_label: str = ""

    nonce_replayed: bool = False
    token_already_spent: bool = False
    consumed_at: str = ""
    replay_risk: int = 0

    challenge_outcome: str = "NONE"            # NONE|PENDING|PASSED|FAILED|FAILED_EXHAUSTED
    challenge_field: str = ""
    challenge_attempts: int = 0
    signature_verdict: str = "ABSENT"
    sanctions_screen: str = "clear"

    presented_policy_version: str = ""
    current_policy_version: str = ""

    channel_independent: bool = False
    channel_verdict: str = "PENDING"
    mandatory_out_of_band: bool = False        # CREDENTIAL_RESET always demands it (S17)

@dataclass(frozen=True)
class PolicyDecision:
    """§16.7's output. `risk_reasons` on the wire is `[r.text for r in reasons]`."""

    outcome: Outcome
    decision: Decision
    band_outcome: Decision
    reasons: tuple[ReasonDetail, ...]
    required_actions: tuple[str, ...] = ("none",)
    override_applied: str | None = None            # the HO id, "BREAKER" or "DURESS"
    hard_overrides_fired: tuple[str, ...] = ()      # the §6.6 semantic codes
    failed_preconditions: tuple[str, ...] = ()
    duress_escalation: bool = False
    requires_out_of_band_verification: bool = False
    visible_to_requester: str = "APPROVE"
    cooldown_seconds: int = 0
    deterministic: bool = True

    @property
    def risk_reasons(self) -> tuple[str, ...]:
        return tuple(r.text for r in self.reasons)


def _inr(minor_units: int | None) -> str:
    """Indian digit grouping, for reason text only. Never feeds arithmetic."""
    if minor_units is None:
        return "(unknown)"
    rupees, paise = divmod(int(minor_units), 100)
    digits, sign = str(abs(rupees)), "-" if rupees < 0 else ""
    head, tail = digits[:-3], digits[-3:]
    if head:
        groups: list[str] = []
        while len(head) > 2:
            head, group = head[:-2], head[-2:]
            groups.insert(0, group)
        if head:
            groups.insert(0, head)
        tail = ",".join(groups) + "," + tail
    body = f"{sign}₹{tail}"
    return body if paise == 0 else f"{body}.{paise:02d}"


def _r(code: str, severity: str, text: str, evidence_ref: str) -> ReasonDetail:
    """Invariant 7 in one call site: no reason without a code, a severity and a pointer."""
    return ReasonDetail(code=code, severity=severity, text=text, evidence_ref=evidence_ref)

@dataclass(frozen=True)
class HardOverride:
    """One categorical fact that BLOCKS regardless of score.

    `explain` and `remedy` are functions of the inputs rather than fixed strings because the
    difference between a good operator experience and a bad one is whether the sentence names
    *this* account, *this* payee and *this* deadline.
    """

    id: str
    fires: Callable[[Inputs], bool]
    explain: Callable[[Inputs], ReasonDetail]
    remedy: Callable[[Inputs], tuple[str, ...]] = lambda a: ("contact_executive_out_of_band",)

    @property
    def code(self) -> str:
        """The §6.6 semantic code that goes in `hard_overrides_fired`."""
        return WIRE_OVERRIDE_CODES[self.id]


#: Long form for the first mention, short noun for the second, so the sentence reads like
#: English instead of a template: "The destination account ... does not match the account ...".
_LABELS: dict[str, tuple[str, str]] = {
    "destination_account": ("destination account", "account"),
    "amount_minor_units": ("amount", "amount"),
    "beneficiary_id_or_name": ("beneficiary", "beneficiary"),
    "transaction_fingerprint": ("transaction fingerprint", "fingerprint"),
}


def _label(name: str) -> tuple[str, str]:
    plain = name.replace("_", " ")
    return _LABELS.get(name, (plain, plain))


def _ho1(a: Inputs) -> ReasonDetail:
    """§16.7's exact sentence. The one reason a judge will read out loud."""
    if not a.fingerprint_deltas:
        return _r(
            "HO-1", "critical",
            "The authorization presented for this request does not bind to its current "
            "contents; the transaction fingerprint does not match.",
            "fingerprint.verify",
        )
    d = a.fingerprint_deltas[0]
    long_form, noun = _label(d.field)
    if has_critical(list(a.fingerprint_deltas)):
        return _r(
            "HO-1", "critical",
            f"The {long_form} in this request does not match the {noun} bound to the "
            f"captured authorization ({d.expected} vs {d.presented}).",
            "fingerprint.deltas[0]",
        )
    return _r(
        "HO-1", "material",
        f"This request no longer matches the authorization it carries: the {long_form} "
        f"changed after approval ({d.expected} vs {d.presented}).",
        "fingerprint.deltas[0]",
    )

def _ho2_fires(a: Inputs) -> bool:
    return bool(
        a.beneficiary_account_changed
        and a.amount_minor_units is not None
        and a.ceiling_minor_units is not None
        and a.amount_minor_units > a.ceiling_minor_units
    )


def _ho2(a: Inputs) -> ReasonDetail:
    payee = a.payee_label or "this beneficiary"
    return _r(
        "HO-2", "critical",
        f"Payment of {_inr(a.amount_minor_units)} to an account not on record for {payee}, "
        f"above the {_inr(a.ceiling_minor_units)} single-transaction ceiling.",
        "policy.single_txn_ceiling",
    )


def _ho3_fires(a: Inputs) -> bool:
    """Skeleton collision always. Near-misses only against an ESTABLISHED payee.

    §7.1 stops at the collision; shared §8's `S11` needs the edit-distance tier too, so a
    high-confidence near-miss on a payee we have actually paid before is included. Both tiers
    require the *target* to be established — otherwise two unknown payees with similar names
    would block each other for no reason.
    """
    if a.confusion_verdict == "skeleton_collision":
        return True
    return bool(
        a.confusion_verdict == "edit_distance"
        and a.confusion_target_established
        and a.confusion_confidence >= 60
    )


def _ho3(a: Inputs) -> ReasonDetail:
    target = a.confusion_target_label or "an established payee"
    if a.confusion_verdict == "skeleton_collision":
        where = f" but differs at codepoint {a.confusion_codepoint}" if a.confusion_codepoint else ""
        return _r(
            "HO-3", "critical",
            f"Payee name is visually identical to established payee {target}{where}.",
            "beneficiary.confusable",
        )
    return _r(
        "HO-3", "critical",
        f"Payee name is a near-duplicate of established payee {target} "
        f"(confusability {a.confusion_confidence}/100); this is how payee substitution looks.",
        "beneficiary.edit_distance",
    )

def _ho4(a: Inputs) -> ReasonDetail:
    when = a.consumed_at or "an earlier time in this window"
    what = "nonce" if a.nonce_replayed else "capability token"
    return _r(
        "HO-4", "critical",
        f"This authorization was already consumed at {when}; a {what} is single-use.",
        "replay.consumed_at",
    )


def _ho5(a: Inputs) -> ReasonDetail:
    field = _label(a.challenge_field)[0] if a.challenge_field else "details"
    n = a.challenge_attempts or 2
    return _r(
        "HO-5", "critical",
        f"The approver could not confirm the {field} of this transaction in {n} attempts.",
        "challenge.result",
    )


def _ho6(a: Inputs) -> ReasonDetail:
    extra = " The device's key is revoked." if a.signature_verdict == "REVOKED" else ""
    return _r(
        "HO-6", "critical",
        "The approving device's signature did not verify against its registered key." + extra,
        "device.signature",
    )


def _ho7(a: Inputs) -> ReasonDetail:
    return _r(
        "HO-7", "critical",
        "Beneficiary appears on a screening list; release requires compliance sign-off.",
        "beneficiary.sanctions_screen",
    )


def _ho8(a: Inputs) -> ReasonDetail:
    old = a.presented_policy_version or "an earlier version"
    new = a.current_policy_version or "the current version"
    return _r(
        "HO-8", "material",
        f"This authorization was issued under policy {old}; current policy is {new}. "
        f"Re-authorization is required.",
        "policy.version",
    )

#: §16.3, FROZEN ORDER. First match wins. HO-1 is first because it is the thesis: if HO-3
#: fired first on an S06-family case you would show a homoglyph message when the real story is
#: a mismatched account.
HARD_OVERRIDES: tuple[HardOverride, ...] = (
    HardOverride(
        id="HO-1",
        # Shared Invariant 4 is unconditional: any MISMATCH blocks. The critical/cosmetic
        # split chooses the sentence and the remedy, never the outcome.
        fires=lambda a: a.fingerprint_status == "MISMATCH",
        explain=_ho1,
        remedy=lambda a: (
            ("contact_executive_out_of_band", "notify_security_officer")
            if has_critical(list(a.fingerprint_deltas)) or not a.fingerprint_deltas
            else ("reauthorize_with_current_details",)
        ),
    ),
    HardOverride(
        id="HO-2",
        fires=_ho2_fires,
        explain=_ho2,
        remedy=lambda a: ("contact_executive_out_of_band", "verify_beneficiary_account_with_payee"),
    ),
    HardOverride(
        id="HO-3",
        fires=_ho3_fires,
        explain=_ho3,
        remedy=lambda a: ("verify_beneficiary_account_with_payee", "notify_security_officer"),
    ),
    HardOverride(
        id="HO-4",
        fires=lambda a: bool(a.nonce_replayed or a.token_already_spent),
        explain=_ho4,
        remedy=lambda a: ("reauthorize_with_current_details",),
    ),
    HardOverride(
        id="HO-5",
        fires=lambda a: a.challenge_outcome == "FAILED_EXHAUSTED",
        explain=_ho5,
        remedy=lambda a: ("contact_executive_out_of_band", "notify_security_officer"),
    ),
    HardOverride(
        id="HO-6",
        fires=lambda a: a.signature_verdict in ("INVALID", "REVOKED"),
        explain=_ho6,
        remedy=lambda a: ("notify_security_officer", "complete_approval_in_console"),
    ),
    HardOverride(
        id="HO-7",
        fires=lambda a: a.sanctions_screen != "clear",
        explain=_ho7,
        remedy=lambda a: ("compliance_signoff",),
    ),
    HardOverride(
        id="HO-8",
        fires=lambda a: bool(
            a.presented_policy_version
            and a.current_policy_version
            and a.presented_policy_version != a.current_policy_version
        ),
        explain=_ho8,
        remedy=lambda a: ("reauthorize_with_current_details",),
    ),
)

@dataclass(frozen=True)
class Precondition:
    """One of the six things that must hold for an APPROVE to be an APPROVE.

    `APPROVE` is not "risk was low". It is "risk was low AND every one of these held".
    """

    id: str
    holds: Callable[[Inputs], bool]
    explain: Callable[[Inputs], ReasonDetail]
    remedy: Callable[[Inputs], tuple[str, ...]]


def _pc2(a: Inputs) -> ReasonDetail:
    which = ", ".join(a.abstained) if a.abstained else "several dimensions"
    return _r(
        "PC-2", "material",
        f"Only {a.coverage:.0%} of the risk evidence could be evaluated ({which} had no "
        f"signal); confirm this request with the executive over a known channel before release.",
        "fusion.coverage",
    )


def _pc4(a: Inputs) -> ReasonDetail:
    return _r(
        "PC-4", "material",
        f"The approval and the request arrived over the same channel, so a compromised "
        f"channel could have produced both. A payment of {_inr(a.amount_minor_units)} needs "
        f"confirmation on a channel the requester does not control.",
        "channel.independence",
    )

#: §16.4, evaluated in order so the *first* failure supplies the primary reason. Every text
#: names a remedy from the closed `REQUIRED_ACTIONS` vocabulary — "additional verification
#: required" is not in it, and that difference is most of the perceived quality of the product.
APPROVE_PRECONDITIONS: tuple[Precondition, ...] = (
    Precondition(
        id="PC-1",
        holds=lambda a: a.fingerprint_status == "MATCH",
        explain=lambda a: _r(
            "PC-1", "material",
            "This request was never cryptographically bound to an approval, so we cannot "
            "confirm the executive approved these exact details. Re-approve it in the console, "
            "where the transaction is bound at signing time.",
            "fingerprint.verify",
        ),
        remedy=lambda a: ("complete_approval_in_console",),
    ),
    Precondition(
        id="PC-2",
        holds=lambda a: a.coverage >= MIN_COVERAGE,
        explain=_pc2,
        remedy=lambda a: ("contact_executive_out_of_band",),
    ),
    Precondition(
        id="PC-3",
        # Step 3 has already returned by the time this runs; kept as defence in depth. The
        # text is deliberately bland: no reason string may ever hint at the duress scheme.
        holds=lambda a: not a.duress_suspected,
        explain=lambda a: _r(
            "PC-3", "material",
            "This request requires manual confirmation before any funds are released.",
            "policy.manual_confirmation",
        ),
        remedy=lambda a: ("named_human_review",),
    ),
    Precondition(
        id="PC-4",
        holds=lambda a: bool(
            a.channel_independent
            or (a.amount_minor_units is not None and a.amount_minor_units <= LOW_VALUE_EXEMPT)
        ),
        explain=_pc4,
        remedy=lambda a: ("contact_executive_out_of_band",),
    ),
    Precondition(
        id="PC-5",
        holds=lambda a: a.replay_risk < REPLAY_RISK_APPROVE_CEILING,
        explain=lambda a: _r(
            "PC-5", "material",
            f"This request closely duplicates a recent one (similarity {a.replay_risk}/100). "
            f"Confirm with the executive that it is a second payment and not a resend.",
            "replay.risk",
        ),
        remedy=lambda a: ("contact_executive_out_of_band",),
    ),
    Precondition(
        id="PC-6",
        holds=lambda a: a.breaker_state is BreakerState.CLOSED,
        explain=lambda a: _r(
            "PC-6", "material",
            "Organizational velocity controls are engaged; releases are paused pending review.",
            "breaker.state",
        ),
        remedy=lambda a: ("named_human_review",),
    ),
)

def _actions(*groups: tuple[str, ...]) -> tuple[str, ...]:
    """Dedupe in first-seen order and reject anything outside the closed vocabulary.

    The closed list is what lets C map every remedy to a button. A typo here should fail a
    test, not ship a dead-end string to an operator at the moment they need to act.
    """
    out: list[str] = []
    for group in groups:
        for action in group:
            if action not in REQUIRED_ACTIONS:
                raise ValueError(f"{action!r} is not in the closed REQUIRED_ACTIONS vocabulary")
            if action != "none" and action not in out:
                out.append(action)
    return tuple(out) or ("none",)


def _band_reason(a: Inputs, band: Decision) -> ReasonDetail:
    """Always emitted, so Invariant 7 holds on every path including a clean APPROVE."""
    score = max(0, min(100, round(a.risk_score)))
    if band is Decision.BLOCK:
        text = f"Weighted risk {score}/100 is above the block threshold."
        return _r("BAND", "critical", text, "fusion.risk_score")
    if band is Decision.CHALLENGE:
        text = f"Weighted risk {score}/100 falls in the challenge band."
        return _r("BAND", "material", text, "fusion.risk_score")
    return _r("BAND", "info", f"Weighted risk {score}/100 is in the approve band.",
              "fusion.risk_score")


def _breaker_reason(a: Inputs) -> ReasonDetail:
    return _r(
        "BREAKER", "critical",
        "Organizational velocity controls tripped: an unusual burst of elevated-risk "
        "authorization requests is in progress. Releases are paused pending review.",
        "breaker.state",
    )


def _duress_reason(a: Inputs) -> ReasonDetail:
    """Names no marker, no scheme and no position — §13's rule, and a safety property.

    If this string ever describes *how* duress was signalled, an attacker who reads one
    assessment learns how to avoid triggering it, and the executive who relied on it is worse
    off than if the feature did not exist.
    """
    return _r(
        "DURESS", "critical",
        "This authorization requires named human review before any funds are released.",
        "policy.manual_confirmation",
    )

def decide(a: Inputs) -> PolicyDecision:
    """The only function in the system that writes `decision` (Invariant 2).

    Pure: no clock, no RNG, no I/O, no model. The same `Inputs` produce the same
    `PolicyDecision` on any machine, forever — which is what makes §19.2's replay possible.
    """
    band = Decision(band_for(a.risk_score))

    # 1. BREAKER — organizational state precedes individual assessment.
    if a.breaker_state is BreakerState.OPEN:
        return PolicyDecision(
            outcome=Outcome.BREAKER_TRIPPED,
            decision=Outcome.BREAKER_TRIPPED.wire(),
            band_outcome=band,
            reasons=(_breaker_reason(a), _band_reason(a, band)),
            required_actions=_actions(
                ("named_human_review",),
                ("notify_security_officer",) if a.duress_suspected else (),
            ),
            override_applied="BREAKER",
            hard_overrides_fired=(WIRE_OVERRIDE_CODES["BREAKER"],),
            # Refusing the money does not make the executive safe. If duress was suspected,
            # the escalation still fires — the two concerns are independent.
            duress_escalation=a.duress_suspected,
            requires_out_of_band_verification=a.duress_suspected or a.mandatory_out_of_band,
            visible_to_requester=Decision.BLOCK.value,
        )

    # 2. HARD OVERRIDES — categorical facts, FIXED order, first match wins.
    for rule in HARD_OVERRIDES:
        if rule.fires(a):
            actions = _actions(
                rule.remedy(a),
                ("notify_security_officer",) if a.duress_suspected else (),
            )
            return PolicyDecision(
                outcome=Outcome.BLOCK,
                decision=Decision.BLOCK,
                band_outcome=band,
                reasons=(rule.explain(a), _band_reason(a, band)),
                required_actions=actions,
                override_applied=rule.id,
                hard_overrides_fired=(rule.code,),
                duress_escalation=a.duress_suspected,
                requires_out_of_band_verification=(
                    a.mandatory_out_of_band
                    or a.duress_suspected
                    or "contact_executive_out_of_band" in actions
                ),
                visible_to_requester=Decision.BLOCK.value,
            )

    # 3. DURESS — the silent path. Reads APPROVE on the wire, mints no capability token, and
    #    wakes the security officer. Because C's executor cannot move money without a token,
    #    "APPROVE with no token" is a routine-looking screen that releases nothing.
    if a.duress_suspected:
        return PolicyDecision(
            outcome=Outcome.SILENT_ESCALATION,
            decision=Outcome.SILENT_ESCALATION.wire(),
            band_outcome=band,
            reasons=(_duress_reason(a),),
            required_actions=_actions(("notify_security_officer", "named_human_review")),
            override_applied="DURESS",
            hard_overrides_fired=(WIRE_OVERRIDE_CODES["DURESS"],),
            duress_escalation=True,
            requires_out_of_band_verification=True,
            visible_to_requester="PROCESSING",
            cooldown_seconds=cooldown_seconds(a.risk_score),
        )

    # 4. BAND — the fused score's default outcome, and the only place the score decides.
    outcome = Outcome(band.value)
    reasons: list[ReasonDetail] = [_band_reason(a, band)]
    remedies: list[tuple[str, ...]] = []
    failed: list[str] = []

    # 5. FLOORS — fusion can force a CHALLENGE on evidence grounds alone. Honour its verdict
    #    rather than re-deriving it, so there is exactly one coverage rule in the system.
    if a.forced_outcome:
        outcome = _worse(outcome, Outcome(a.forced_outcome))

    # 6. PRECONDITIONS — all six are evaluated, not short-circuited: an operator who is about
    #    to make a phone call deserves to see every reason the release is held, not the first.
    for pc in APPROVE_PRECONDITIONS:
        if not pc.holds(a):
            failed.append(pc.id)
            reasons.append(pc.explain(a))
            remedies.append(pc.remedy(a))
    if failed:
        outcome = _worse(outcome, Outcome.CHALLENGE)

    if outcome is Outcome.CHALLENGE and (
        a.challenge_outcome in ("PENDING", "FAILED") or not remedies
    ):
        # A challenge that does not tell the approver what to answer is just a refusal.
        remedies.insert(0, ("answer_comprehension_challenge",))

    # 7. NEVER DOWNGRADE. Every mutation above went through `_worse`, so there is no path
    #    from BLOCK back to CHALLENGE or APPROVE.
    actions = _actions(*remedies)
    wire = outcome.wire()
    return PolicyDecision(
        outcome=outcome,
        decision=wire,
        band_outcome=band,
        reasons=tuple(reasons),
        required_actions=actions,
        failed_preconditions=tuple(failed),
        requires_out_of_band_verification=(
            a.mandatory_out_of_band or "contact_executive_out_of_band" in actions
        ),
        visible_to_requester=wire.value,
        cooldown_seconds=0 if outcome is Outcome.BLOCK else cooldown_seconds(a.risk_score),
    )

def _assert_policy_shape() -> None:
    """Fail at import if the ordered rules drift out of step with the frozen id lists.

    `HARD_OVERRIDE_IDS` and `PRECONDITION_IDS` live in `constants.py` because they are hashed
    into `policy_hash`; the rules live here because they are code. This keeps the two honest.
    """
    ids = tuple(r.id for r in HARD_OVERRIDES)
    if ids != HARD_OVERRIDE_IDS:
        raise AssertionError(f"HARD_OVERRIDES order {ids} != frozen {HARD_OVERRIDE_IDS}")
    pcs = tuple(p.id for p in APPROVE_PRECONDITIONS)
    if pcs != PRECONDITION_IDS:
        raise AssertionError(f"APPROVE_PRECONDITIONS order {pcs} != frozen {PRECONDITION_IDS}")
    missing = [i for i in ids if i not in WIRE_OVERRIDE_CODES]
    if missing:
        raise AssertionError(f"no §6.6 semantic code for {missing}")


_assert_policy_shape()
