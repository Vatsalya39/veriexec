"""B5 — semantic drift scoring. [NOVEL-N3]

Compare what the executive *said* against what the system is *about to execute*, field by
field. Fingerprint mismatch is binary; drift is graded, so it catches the attack that
changed something the fingerprint does not bind, or that never had a reference at all.

The `40`-for-unresolved-amount rule is the most important number in this module: a channel
where the amount was never stated in a parseable way is not clean and not fully dirty. 40
puts it in the middle of the CHALLENGE band, which is the correct outcome: **ask**.

Drift is a *comparison*, so it can only be scored where two statements actually exist. That
sounds obvious and it was silently false: with no reference pre-image and no second
extraction, `spoken` and `executed` were both filled from the same intent, every distance
came out 0, and the dimension published "The instruction and the execution request agree on
every bound field" — an exculpatory claim derived from one reading compared with a copy of
itself. It carried 0.15 of the fusion weight and, because it never abstained, coverage still
read 1.00, so the uncertainty penalty that exists for exactly this case never fired.
`fusion.py` opens by naming the failure: "Treating `None` as `0` is the bug that turns a
broken microphone into an approval."

So each field now reports whether it was *measurable*, `DRIFT_WEIGHTS` is renormalised over
the fields that were, and when none were the dimension abstains. Two things make a field
measurable: a reference pre-image (an independent, earlier, human-approved statement), or a
second extraction to disagree with — `extraction_mode` in {`llm`, `hybrid`} with a populated
`deterministic_intent`. Absence of a *needed* field is measurable on its own, which is what
keeps §8's 40 alive for an unreadable amount; absence of an account nobody stated is not
drift, because no statement exists to disagree with.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import TransactionIntent, DeterministicIntent
from ..policy.constants import DRIFT_WEIGHTS
from .fusion import DimensionScore

#: The distance for "we could not read the spoken value at all" (§8).
UNRESOLVED_AMOUNT_DISTANCE = 40.0


@dataclass(frozen=True)
class DriftResult:
    #: `None` means *unmeasurable*, never "no drift". See the module docstring.
    score: float | None
    per_field: dict[str, float]
    narrative: str
    #: The fields that were actually comparable; `DRIFT_WEIGHTS` is renormalised over these.
    measured: tuple[str, ...] = ()
    abstain_reason: str = ""


def _norm_name(s: str | None) -> str:
    return (s or "").strip().casefold()


def _digits(s: str | None) -> str:
    return "".join(c for c in (s or "") if c.isdigit())


def _amount_distance(spoken: int | None, executed: int | None) -> float:
    # Both sides missing is the §8 case in its purest form: nobody ever stated a readable
    # amount. Returning 0.0 here read that as "the amounts agree", which is a statement about
    # two numbers that do not exist — and it zeroed the one field that stays measurable when
    # there is no reference at all (S17, S22).
    if spoken is None and executed is None:
        return UNRESOLVED_AMOUNT_DISTANCE
    if spoken is None or executed is None:
        return UNRESOLVED_AMOUNT_DISTANCE
    if spoken == executed:
        return 0.0
    return min(100.0, 100.0 * abs(spoken - executed) / max(spoken, executed, 1))


def _account_distance(spoken: str | None, executed: str | None) -> float:
    s, e = _digits(spoken), _digits(executed)
    if not s and not e:
        return 0.0
    if not s or not e:
        return UNRESOLVED_AMOUNT_DISTANCE
    if s == e:
        return 0.0
    # IFSC-only difference: same digits after stripping, or last-10 identical
    if spoken and executed and s[-10:] == e[-10:]:
        return 60.0
    return 100.0


def _beneficiary_distance(spoken: str | None, executed: str | None) -> float:
    s, e = _norm_name(spoken), _norm_name(executed)
    if not s and not e:
        return 0.0
    if not s or not e:
        return UNRESOLVED_AMOUNT_DISTANCE
    if s == e:
        return 0.0
    return 100.0


def _action_distance(spoken, executed) -> float:
    s = getattr(spoken, "value", spoken)
    e = getattr(executed, "value", executed)
    if s is None and e is None:
        return 0.0
    if s is None or e is None:
        return UNRESOLVED_AMOUNT_DISTANCE
    return 0.0 if str(s).strip().casefold() == str(e).strip().casefold() else 100.0


def _currency_distance(spoken, executed) -> float:
    s = (spoken or "").strip().upper()
    e = (executed or "").strip().upper()
    if not s:
        s = "INR"   # §9: INR is the default currency
    if not e:
        e = "INR"
    return 0.0 if s == e else 100.0


def _narrate(per_field: dict[str, float], intent: TransactionIntent) -> str:
    """Deterministic template, not a model call — it feeds intent_confidence (§8)."""
    parts: list[str] = []
    if per_field.get("amount", 0) >= UNRESOLVED_AMOUNT_DISTANCE:
        parts.append("the amount stated in the communication could not be read exactly")
    elif per_field.get("amount", 0) > 0:
        parts.append("the executed amount differs from what was stated")
    if per_field.get("account", 0) >= 60:
        parts.append("the destination account in the request is not the account of record")
    if per_field.get("beneficiary", 0) > 0:
        parts.append("the beneficiary named does not match the payee of record")
    if per_field.get("action", 0) > 0:
        parts.append("the requested action differs from the authorized action")
    if per_field.get("currency", 0) > 0:
        parts.append("the currency differs")
    if not parts:
        # Only reachable when at least one field was genuinely compared, so this now says
        # what it always claimed to say. `score()` returns an abstention instead when
        # nothing was comparable, rather than letting this sentence stand on no evidence.
        compared = ", ".join(sorted(per_field)) or "no field"
        return (f"The instruction and the execution request agree on every bound field that "
                f"could be compared ({compared}).")
    return "Drift: " + "; ".join(parts) + "."


#: Which fields a single-source extraction can still say something about. §8's 40 is a claim
#: about the *request* ("the amount was never stated in a parseable way"), not about a
#: disagreement between two statements, so it survives with no reference. The other four
#: cannot: an account nobody stated is not an account that changed, which is the same rule
#: the HO-2 wiring in `assess.py` applies at the override layer.
_SELF_MEASURABLE: frozenset[str] = frozenset({"amount"})


def _has_second_reading(intent: TransactionIntent) -> bool:
    """Is `deterministic_intent` an independent reading, or the same one under another name?

    A `hybrid` extraction mode says two parsers ran. It does **not** say B was handed two
    statements: A's merge policy resolves every compared field to the deterministic twin —
    deterministic wins where it spoke, and where it found nothing the merged intent falls
    back to the value the merge itself produced. So `spoken` and `executed` are equal by
    construction and every distance is 0 — which this module's own docstring calls "an
    exculpatory claim derived from one reading compared with a copy of itself". That was
    invisible while the LLM client was a `NullClient` (the mode was never `hybrid`); the
    first live model made it the default outcome for every scenario without a reference
    pre-image, and S08's BLOCK quietly became a CHALLENGE.

    Until A publishes the model's raw, unmerged reading as its own twin — a field B could
    compare the deterministic one against, rather than a flag that says a second parser
    existed somewhere — there is no second statement here. Drift abstains rather than
    fabricate agreement; the reference pre-image path above is a real, independent
    statement and is untouched.
    """
    return False


def score(
    intent: TransactionIntent,
    *,
    reference_fields: dict | None = None,
    executed_amount_minor_units: int | None = None,
    executed_account: str | None = None,
    executed_beneficiary: str | None = None,
    executed_action=None,
    executed_currency: str | None = None,
) -> DriftResult:
    """`spoken` is what the executive approved (the reference pre-image when one exists);
    `executed` is what is about to be paid.

    Returns a `DriftResult` whose `score` is `None` when neither a pre-image nor a second
    extraction exists and the request resolved every field it needed — there is nothing to
    compare, and saying "no drift" then would be a claim about evidence that was never
    gathered. `measured` names the fields the score is actually built from.
    """
    from ..assess import minor_units as _to_paise  # local import: circular otherwise

    spoken_amount = _to_paise(intent)
    det: DeterministicIntent | None = intent.deterministic_intent
    det_amount = None
    if det is not None and det.amount is not None:
        try:
            det_amount = _to_paise(det)
        except Exception:
            det_amount = None

    # The executed side defaults to the intent (the request B is assessing); the spoken
    # side is the approved reference when there is one.
    executed_amount = executed_amount_minor_units if executed_amount_minor_units is not None else spoken_amount
    executed_account = executed_account if executed_account is not None else intent.destination_account
    executed_beneficiary = executed_beneficiary if executed_beneficiary is not None else intent.beneficiary
    executed_action = executed_action if executed_action is not None else intent.action
    executed_currency = executed_currency if executed_currency is not None else intent.currency

    if reference_fields is not None:
        ref_amount = reference_fields.get("amount_minor_units")
        ref_account = reference_fields.get("destination_account")
        ref_beneficiary = reference_fields.get("beneficiary_id_or_name")
        ref_action = reference_fields.get("action")
        ref_currency = reference_fields.get("currency")
        spoken_amount = ref_amount if ref_amount is not None else spoken_amount
        spoken_account = ref_account or intent.destination_account
        spoken_beneficiary = ref_beneficiary or intent.beneficiary
        spoken_action = ref_action or intent.action
        spoken_currency = ref_currency or intent.currency
    else:
        spoken_account = (det.destination_account if det else None) or intent.destination_account
        spoken_beneficiary = (det.beneficiary if det else None) or intent.beneficiary
        spoken_action = (getattr(det, "action", None) if det else None) or intent.action
        spoken_currency = intent.currency
        if det_amount is not None:
            spoken_amount = det_amount

    all_fields = {
        "amount": _amount_distance(spoken_amount, executed_amount),
        "account": _account_distance(spoken_account, executed_account),
        "beneficiary": _beneficiary_distance(spoken_beneficiary, executed_beneficiary),
        "action": _action_distance(spoken_action, executed_action),
        "currency": _currency_distance(spoken_currency, executed_currency),
    }

    # Which of those five were comparisons rather than self-comparisons. A reference
    # pre-image makes all of them real; without one, only the fields that can speak about
    # the request alone survive, and only when the request actually left them unresolved.
    if reference_fields is not None or _has_second_reading(intent):
        measured = tuple(sorted(all_fields))
    else:
        measured = tuple(sorted(
            f for f in all_fields if f in _SELF_MEASURABLE and all_fields[f] > 0
        ))

    if not measured:
        return DriftResult(
            score=None, per_field={}, measured=(),
            narrative="",
            abstain_reason=(
                "no approved pre-image and a single-source extraction, so there is no second "
                "statement to compare this request against; drift is unmeasured, not absent"
            ),
        )

    per_field = {f: all_fields[f] for f in measured}
    # Renormalise over the weight actually present, exactly as `fuse()` does one level up:
    # a field that could not be compared must not dilute the fields that could.
    present = sum(DRIFT_WEIGHTS[f] for f in measured)
    total = sum(DRIFT_WEIGHTS[f] * per_field[f] for f in measured) / present
    return DriftResult(score=round(total, 2), per_field=per_field, measured=measured,
                       narrative=_narrate(per_field, intent))


def dimension(result: DriftResult) -> DimensionScore:
    if result.score is None:
        return DimensionScore(
            dimension="semantic_drift", score=None,
            abstain_reason=result.abstain_reason or "semantic drift could not be measured",
        )
    return DimensionScore(
        dimension="semantic_drift",
        score=result.score,
        reason=result.narrative,
        evidence_ref="scoring/drift.py#DRIFT_WEIGHTS",
        evidence=tuple(f"{k}={v:.0f}" for k, v in sorted(result.per_field.items()) if v > 0),
    )
