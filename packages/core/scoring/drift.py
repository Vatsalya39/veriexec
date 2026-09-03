"""B5 — semantic drift scoring. [NOVEL-N3]

Compare what the executive *said* against what the system is *about to execute*, field by
field. Fingerprint mismatch is binary; drift is graded, so it catches the attack that
changed something the fingerprint does not bind, or that never had a reference at all.

The `40`-for-unresolved-amount rule is the most important number in this module: a channel
where the amount was never stated in a parseable way is not clean and not fully dirty. 40
puts it in the middle of the CHALLENGE band, which is the correct outcome: **ask**.
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
    score: float
    per_field: dict[str, float]
    narrative: str


def _norm_name(s: str | None) -> str:
    return (s or "").strip().casefold()


def _digits(s: str | None) -> str:
    return "".join(c for c in (s or "") if c.isdigit())


def _amount_distance(spoken: int | None, executed: int | None) -> float:
    if spoken is None and executed is None:
        return 0.0
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
        return "The instruction and the execution request agree on every bound field."
    return "Drift: " + "; ".join(parts) + "."


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
    `executed` is what is about to be paid. With no reference, the intent's own extraction
    is both sides — which measures extraction ambiguity (S22) rather than tampering."""
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

    per_field = {
        "amount": _amount_distance(spoken_amount, executed_amount),
        "account": _account_distance(spoken_account, executed_account),
        "beneficiary": _beneficiary_distance(spoken_beneficiary, executed_beneficiary),
        "action": _action_distance(spoken_action, executed_action),
        "currency": _currency_distance(spoken_currency, executed_currency),
    }
    total = sum(DRIFT_WEIGHTS[f] * per_field[f] for f in DRIFT_WEIGHTS)
    return DriftResult(score=round(total, 2), per_field=per_field,
                       narrative=_narrate(per_field, intent))


def dimension(result: DriftResult) -> DimensionScore:
    return DimensionScore(
        dimension="semantic_drift",
        score=result.score,
        reason=result.narrative,
        evidence_ref="scoring/drift.py#DRIFT_WEIGHTS",
        evidence=tuple(f"{k}={v:.0f}" for k, v in sorted(result.per_field.items()) if v > 0),
    )
