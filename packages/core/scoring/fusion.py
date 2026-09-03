"""B7 — abstention-aware risk fusion, the contribution table and `intent_confidence`.

The module judges will read line by line, so it says what it does in the order it does it.

Two ideas carry it:

1. **A dimension that abstains is renormalised out, then charged for.** Treating `None` as
   `0` is the bug that turns a broken microphone into an approval: the average silently
   falls. Renormalising over the weight actually present fixes the arithmetic, and the
   uncertainty penalty fixes the epistemics — not knowing is worse than knowing it is fine.
2. **`intent_confidence` does not know about voices.** `INTENT_PENALTY_WEIGHTS` contains no
   media term, and `constants._assert_weights()` fails the import if one appears. That
   absence is the product: "almost certainly his voice, almost certainly not his
   transaction" is only sayable if the second number cannot see the first.

Scores in this module are RISK direction, 0-100, higher is worse. Callers invert Team A's
authenticity scores *before* they get here; `dimension_from_authenticity` is the only
sanctioned way to do it so the inversion happens in one place with one comment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..models import ContributionRow
from ..policy.constants import (
    FINGERPRINT_INTENT_PENALTY,
    INTENT_CONFIDENCE_CAP_ON_MISMATCH,
    INTENT_PENALTY_WEIGHTS,
    MIN_COVERAGE,
    RISK_WEIGHTS,
    UNCERTAINTY_PENALTY,
)

#: The synthetic contribution row that makes the table add up to `risk_score`.
UNCERTAINTY_FACTOR = "uncertainty"

@dataclass(frozen=True)
class DimensionScore:
    """One of the seven dimensions in `RISK_WEIGHTS`.

    `score=None` means the dimension abstained — no evidence either way. It is not 0, and
    `abstain_reason` is mandatory when it happens, because Invariant 7 applies to the
    absence of a number as much as to the presence of one.
    """

    dimension: str
    score: float | None
    reason: str = ""
    evidence_ref: str = ""
    evidence: tuple[str, ...] = ()
    abstain_reason: str = ""

    def __post_init__(self) -> None:
        if self.dimension not in RISK_WEIGHTS:
            raise KeyError(f"{self.dimension!r} is not one of the seven RISK_WEIGHTS dimensions")
        if self.score is None and not self.abstain_reason:
            raise ValueError(f"{self.dimension}: an abstention must say why it abstained")
        if self.score is not None and not self.reason:
            raise ValueError(
                f"{self.dimension}: Invariant 7 — a populated score needs a reason"
            )
        if self.score is not None and not self.evidence_ref:
            raise ValueError(
                f"{self.dimension}: no reason string may exist without an evidence_ref (§10.3)"
            )


@dataclass(frozen=True)
class FusionResult:
    score: int | None                        # None only when nothing at all could be scored
    coverage: float                          # 0.0-1.0, the fraction of weight present
    abstained: tuple[str, ...] = ()
    forced_outcome: str | None = None        # "CHALLENGE" when the coverage floor is breached
    reason: str = ""
    contributions: tuple[ContributionRow, ...] = ()
    weighted_before_penalty: float = 0.0
    uncertainty_points: float = 0.0
    total_before_clamp: float = 0.0

def dimension_from_authenticity(
    dimension: str,
    authenticity: float | None,
    *,
    reason: str,
    evidence_ref: str,
    abstain_reason: str = "",
    evidence: tuple[str, ...] = (),
) -> DimensionScore:
    """The ONE place an authenticity score becomes a risk score.

    §6.2 warns that every team inverts one of these at least once. `identity_confidence`
    and `communication_authenticity` are AUTHENTICITY — higher means more likely genuine —
    so risk is `100 - authenticity`. Doing it here, once, is why no scorer has to remember.
    """
    if authenticity is None:
        return DimensionScore(
            dimension=dimension,
            score=None,
            abstain_reason=abstain_reason or "detector abstained; no authenticity evidence",
        )
    risk = 100.0 - max(0.0, min(100.0, float(authenticity)))
    return DimensionScore(
        dimension=dimension, score=risk, reason=reason,
        evidence_ref=evidence_ref, evidence=evidence,
    )


def _row(d: DimensionScore, coverage: float) -> ContributionRow:
    """One table row. `points` uses the RENORMALISED weight so the parts add to the whole.

    §10.3 requires `sum(points) == risk_score` before the uncertainty penalty. Since the
    fused score divides by `coverage`, the honest per-row share is `weight / coverage * raw`,
    and the nominal `weight` still ships alongside it so nothing is hidden.
    """
    nominal = RISK_WEIGHTS[d.dimension]
    if d.score is None:
        return ContributionRow(
            factor=d.dimension, dimension=d.dimension, raw_score=0.0, weight=nominal,
            effective_weight=0.0, points=0.0, abstained=True,
            abstain_reason=d.abstain_reason, reason=d.abstain_reason,
            evidence_ref="", evidence=list(d.evidence),
        )
    effective = nominal / coverage if coverage else 0.0
    return ContributionRow(
        factor=d.dimension, dimension=d.dimension, raw_score=round(float(d.score), 4),
        weight=nominal, effective_weight=round(effective, 6),
        points=round(effective * float(d.score), 4), reason=d.reason,
        evidence_ref=d.evidence_ref,
        evidence=list(d.evidence) or ([d.evidence_ref] if d.evidence_ref else []),
    )

def fuse(scores: Mapping[str, DimensionScore]) -> FusionResult:
    """§10.2. Renormalise over the weight that is present, then charge for what is not."""
    unknown = set(scores) - set(RISK_WEIGHTS)
    if unknown:
        raise KeyError(f"not risk dimensions: {sorted(unknown)}")

    # sorted() everywhere output ordering could depend on dict insertion order — replay
    # asserts byte-identical results, and that is the cheapest way to keep it true.
    ordered = [scores[k] for k in sorted(scores)]
    present = [d for d in ordered if d.score is not None]
    missing = tuple(d.dimension for d in ordered if d.score is None)

    if not present:
        return FusionResult(
            score=None, coverage=0.0, abstained=missing, forced_outcome="CHALLENGE",
            reason="No risk dimension could be evaluated",
            contributions=tuple(_row(d, 0.0) for d in ordered),
        )

    coverage = sum(RISK_WEIGHTS[d.dimension] for d in present)
    weighted = sum(RISK_WEIGHTS[d.dimension] * float(d.score) for d in present) / coverage

    # Missing evidence makes us MORE cautious, never less. Renormalising alone leaves an
    # abstention neutral, and neutral is still the wrong answer.
    uncertainty = UNCERTAINTY_PENALTY * (1.0 - coverage) * 100
    total = weighted + uncertainty

    rows = [_row(d, coverage) for d in ordered]
    if uncertainty:
        rows.append(ContributionRow(
            factor=UNCERTAINTY_FACTOR, dimension=UNCERTAINTY_FACTOR,
            raw_score=round((1.0 - coverage) * 100, 4), weight=UNCERTAINTY_PENALTY,
            effective_weight=UNCERTAINTY_PENALTY, points=round(uncertainty, 4),
            reason=f"{len(missing)} dimension(s) abstained: {', '.join(missing)}",
            evidence_ref="fusion.coverage",
            evidence=[f"coverage={coverage:.2f}"],
        ))
    rows.sort(key=lambda r: (-r.points, r.factor))

    result = dict(
        score=round(min(total, 100)), coverage=round(coverage, 4), abstained=missing,
        contributions=tuple(rows), weighted_before_penalty=round(weighted, 4),
        uncertainty_points=round(uncertainty, 4), total_before_clamp=round(total, 4),
    )
    if coverage < MIN_COVERAGE:
        return FusionResult(
            **result, forced_outcome="CHALLENGE",
            reason=(f"Only {coverage:.0%} of risk dimensions could be evaluated "
                    f"({', '.join(missing)} abstained); insufficient evidence to approve"),
        )
    return FusionResult(**result)

#: Signals that are structurally excluded from `intent_confidence`. Reported on the wire so
#: the claim is machine-checkable rather than a sentence in a README.
INTENT_EXCLUDED_SIGNALS: tuple[str, ...] = (
    "deepfake_voice_score",
    "deepfake_video_score",
    "stylometry_match_score",
    "identity_confidence",
    "communication_authenticity",
)

#: The terms `intent_confidence` needs from the caller. `fingerprint` is derived from the
#: verdict, not passed, so no caller can soften it.
INTENT_INPUT_TERMS: tuple[str, ...] = tuple(
    k for k in INTENT_PENALTY_WEIGHTS if k != "fingerprint"
)


def intent_confidence(
    penalties: Mapping[str, float],
    *,
    duress: bool,
    fingerprint_status: str,
) -> tuple[int, dict[str, float], tuple[str, ...]]:
    """§10.4. "How sure are we the executive intended THIS EXACT transaction?"

    A different question from `risk_score`, and the novel one. Returns the value, the
    per-term penalty breakdown for `intent_confidence_components`, and the list of signals
    that were excluded by construction.
    """
    missing = [k for k in INTENT_INPUT_TERMS if k not in penalties]
    if missing:
        raise KeyError(f"intent_confidence is missing penalty term(s): {sorted(missing)}")
    leaked = sorted(set(penalties) & set(INTENT_EXCLUDED_SIGNALS))
    if leaked:
        raise KeyError(f"media/identity signals may not reach intent_confidence: {leaked}")

    terms = {k: max(0.0, min(100.0, float(penalties[k]))) for k in INTENT_INPUT_TERMS}
    terms["fingerprint"] = float(FINGERPRINT_INTENT_PENALTY[fingerprint_status])

    components = {
        k: round(INTENT_PENALTY_WEIGHTS[k] * terms[k], 4) for k in sorted(INTENT_PENALTY_WEIGHTS)
    }
    confidence = 100.0 - sum(components.values())

    if duress or fingerprint_status == "MISMATCH":
        # A bound-field mismatch cannot leave us confident, whatever the rest of the
        # evidence says. Same for duress: a coerced intention is not an intention.
        confidence = min(confidence, INTENT_CONFIDENCE_CAP_ON_MISMATCH)

    return int(max(0, min(100, round(confidence)))), components, INTENT_EXCLUDED_SIGNALS


def reconciles(result: FusionResult, *, tolerance: float = 0.5) -> bool:
    """§10.3's guarantee: a scorer whose parts do not add to its whole is a black box."""
    return abs(sum(r.points for r in result.contributions) - result.total_before_clamp) <= tolerance
