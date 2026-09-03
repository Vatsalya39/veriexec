"""B6 — extraction-divergence scoring. [NOVEL-N15b]

Team A runs two independent extractors — deterministic and LLM — and hands B both results.
Disagreement between them is a security signal, not an engineering embarrassment: where a
prompt injection succeeds, it moves the LLM and leaves the regex untouched. That gap is
the injection's footprint.

The rule that makes this trustworthy: on any money-or-account disagreement the
DETERMINISTIC value is used, and if the deterministic path found nothing, B abstains
rather than falling back to the LLM — a model is structurally not allowed to be the
source of a number (§9).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import TransactionIntent

#: §9's scoring table.
SCORES: dict[str, float] = {
    "all_agree": 0.0,
    "prose_disagree": 15.0,       # purpose/deadline paraphrase legitimately
    "beneficiary_disagree": 65.0, # names should be copied, not interpreted
    "amount_disagree": 85.0,     # a number is a number; one path was steered
    "account_disagree": 95.0,    # digits cannot be paraphrased
    "llm_hallucinated": 90.0,    # field exists in LLM output, nowhere in the text
    "llm_dropped": 50.0,         # deterministic found it, LLM dropped it
    "injection_flag_floor": 88.0,
}

#: Fields where the deterministic path is authoritative or B abstains (§9).
HARD_FIELDS: tuple[str, ...] = ("amount_minor_units", "destination_account", "currency")


class ExtractionUnavailable(Exception):
    """The deterministic parser could not read a hard field; the LLM's reading is not
    authoritative for money. Surfaces as CHALLENGE with a reason, never as a 500."""


def _paise(v) -> int | None:
    from ..assess import minor_units as _to_paise
    from ..models import TransactionIntent as TI
    if v is None:
        return None
    probe = TI(transaction_id="probe", amount=v)
    try:
        return _to_paise(probe)
    except Exception:
        return None


@dataclass(frozen=True)
class DivergenceResult:
    score: float
    disagree: tuple[str, ...]
    reasons: tuple[str, ...]


def score(intent: TransactionIntent) -> DivergenceResult:
    """Compare the LLM intent against the deterministic twin, A's flags included."""
    det = intent.deterministic_intent
    injection = bool(intent.injection_flags)

    if det is None:
        # A never ran the second path. Not agreement — it is absence of the cross-check,
        # which is worth a mild, honest penalty rather than a free pass.
        if injection:
            return DivergenceResult(
                score=SCORES["injection_flag_floor"], disagree=(),
                reasons=("instruction-like content was found in the transcript; extraction "
                         "was restricted to the deterministic path",),
            )
        return DivergenceResult(
            score=12.0, disagree=(),
            reasons=("the dual-path extraction cross-check did not run, so extraction "
                     "could not be independently confirmed",),
        )

    reasons: list[str] = []
    worst = 0.0
    disagree: list[str] = []

    pairs = (
        ("amount", det.amount, intent.amount, SCORES["amount_disagree"],
         "the two extraction paths read different amounts"),
        ("destination_account", det.destination_account, intent.destination_account,
         SCORES["account_disagree"], "the two extraction paths read different accounts"),
        ("beneficiary", det.beneficiary, intent.beneficiary,
         SCORES["beneficiary_disagree"], "the two extraction paths read different payees"),
    )
    for name, dval, ival, weight, why in pairs:
        d_none = dval is None or (isinstance(dval, str) and not dval.strip())
        i_none = ival is None or (isinstance(ival, str) and not str(ival).strip())
        if d_none and not i_none:
            worst = max(worst, SCORES["llm_hallucinated"])
            disagree.append(name)
            reasons.append(why + " (the model supplied a value the parser could not find)")
        elif not d_none and i_none:
            worst = max(worst, SCORES["llm_dropped"])
            disagree.append(name)
            reasons.append(f"the deterministic parser read a {name} the model path dropped")
        elif not d_none and not i_none:
            dv, iv = (dval, ival) if name != "amount" else (_paise(dval), _paise(ival))
            if name == "amount" and (dv is None or iv is None):
                dv, iv = dval, ival
            if str(dv).strip() != str(iv).strip():
                worst = max(worst, weight)
                disagree.append(name)
                reasons.append(why)

    # prose fields: cheap disagreement, expected and priced small. `DeterministicIntent`
    # carries only `deadline` as its prose field — `purpose` is LLM-only territory and
    # has no deterministic twin to disagree with.
    ds, is_ = (det.deadline or "").strip(), (intent.deadline or "").strip()
    if bool(ds) != bool(is_):
        worst = max(worst, SCORES["prose_disagree"])
        disagree.append("deadline")
        reasons.append("the two paths disagree about the deadline")

    if intent.extraction_divergence:
        for f in intent.extraction_divergence:
            if f not in disagree:
                disagree.append(f)

    out = worst if not injection else max(worst, SCORES["injection_flag_floor"])
    if injection and not reasons:
        reasons.append("instruction-like content was found in the transcript")
    if not reasons:
        reasons.append("both extraction paths agree on every critical field")
    return DivergenceResult(score=min(100.0, out), disagree=tuple(disagree),
                            reasons=tuple(reasons))


def resolve(det_value, llm_value, field: str):
    """§9's guard: hard fields come from the deterministic path or not at all."""
    if field in HARD_FIELDS:
        if det_value is None or (isinstance(det_value, str) and not det_value.strip()):
            raise ExtractionUnavailable(
                f"{field} could not be read by the deterministic parser; the model's "
                f"reading is not authoritative for money"
            )
        return det_value
    return det_value if det_value not in (None, "") else llm_value


def penalty(intent: TransactionIntent) -> float:
    """The §6.6 `extraction_divergence_penalty` — points added on top of the fused score."""
    if intent.deterministic_intent:
        return round(score(intent).score * 0.15, 2)
    if intent.injection_flags:
        return round(SCORES["injection_flag_floor"] * 0.15, 2)
    return 0.0
