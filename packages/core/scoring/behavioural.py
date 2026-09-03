"""B3 — behavioural baseline scoring.

Everything here is MOCKED baseline data (`contracts/behaviour_baselines.json`, generated
from the frozen persona registry). # MOCKED — replace with real ERP/treasury history in
production.

Six components, each 0-100, then a weighted mean — weights straight out of §6. Two guards
that stop this module being embarrassing:

* **Sparse baseline ⇒ abstain, do not assume clean.** `sample_count < MIN_SAMPLE_COUNT`
  returns `score=None` with `abstain_reason="insufficient_history"` — the fusion module
  renormalises the weight (B7). Returning 0 would mean "new executive ⇒ safest possible",
  which is precisely backwards.
* **Cap at 92.** Behavioural evidence alone can never reach the BLOCK band; blocking on
  behaviour alone is how real systems generate the false-challenge rate the organizers
  score. The cap is a named constant because it changes decisions and therefore policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .. import contracts_io
from ..policy.constants import BEHAVIOURAL_CAP
from .fusion import DimensionScore

#: Below this many observations a baseline is an opinion, not a statistic.
MIN_SAMPLE_COUNT = 20

#: §6 component weights — sums to 1.00. Frozen because they sit under `policy_hash` via
#: this file being a policy artefact in spirit; the fusion weights themselves are what
#: the contribution table publishes.
COMPONENT_WEIGHTS: dict[str, float] = {
    "amount_deviation": 0.30,     # most predictive single feature in real BEC data
    "time_anomaly": 0.15,         # attackers pick hours when nobody can phone the CEO
    "beneficiary_novelty": 0.20,   # novelty alone is normal; novelty + size is not
    "lead_time_compression": 0.15, # urgency is the one thing every BEC has
    "channel_atypicality": 0.10,   # kept separate from B11 so both stay auditable
    "velocity_anomaly": 0.10,      # catches campaigns that each look fine alone
}

_HOLIDAYS: tuple[str, ...] = ("01-26", "08-15", "10-02")   # Republic, Independence, Gandhi


@dataclass(frozen=True)
class BehaviourComponents:
    amount_deviation: float
    time_anomaly: float
    beneficiary_novelty: float
    lead_time_compression: float
    channel_atypicality: float
    velocity_anomaly: float


def _interpolate(x: float, lo: float, hi: float, y_lo: float, y_hi: float) -> float:
    """Linear ramp between two calibration points, clamped at both ends."""
    if x <= lo:
        return y_lo
    if x >= hi:
        return y_hi
    return y_lo + (y_hi - y_lo) * (x - lo) / (hi - lo)


def score(
    *,
    executive_id: str | None,
    amount_minor_units: int | None,
    beneficiary_id: str | None,
    channel: str,
    now: datetime,
    lead_time_minutes: float | None = None,
    requests_last_24h: int | None = None,
) -> DimensionScore | None:
    """One behavioural risk score, or None (abstain) when the baseline is too sparse.

    `None` returned here is the *component's* abstention; `DimensionScore.score=None`
    is what fusion sees. The caller decides which to publish — B7 renormalises either way.
    """
    if not executive_id:
        return DimensionScore(
            dimension="behavioural", score=None,
            abstain_reason="no registered executive matched the claimed requester, "
                           "so there is no behavioural baseline to compare against",
        )
    table = contracts_io.baselines(now).get("baselines", {})
    b = table.get(executive_id)
    if not b:
        return DimensionScore(
            dimension="behavioural", score=None,
            abstain_reason=f"no behavioural baseline exists for {executive_id}",
        )
    if int(b.get("sample_count", 0)) < MIN_SAMPLE_COUNT:
        return DimensionScore(
            dimension="behavioural", score=None,
            abstain_reason=f"insufficient_history: only {b.get('sample_count', 0)} samples "
                           f"for {executive_id}; fewer than {MIN_SAMPLE_COUNT} abstains",
        )

    reasons: list[str] = []

    # --- amount deviation: 0 at/below median, 40 at p95, 70 at 2x p95, 95 at 5x p95 -----
    median = int(b["median_amount_minor_units"])
    p95 = int(b["p95_amount_minor_units"])
    if amount_minor_units is None:
        amount_dev = 35.0
        reasons.append("the amount could not be read, so it cannot be compared with history")
    elif amount_minor_units <= median:
        amount_dev = 0.0
    elif amount_minor_units <= p95:
        amount_dev = _interpolate(amount_minor_units, median, p95, 0.0, 40.0)
    elif amount_minor_units <= 2 * p95:
        amount_dev = _interpolate(amount_minor_units, p95, 2 * p95, 40.0, 70.0)
    else:
        amount_dev = _interpolate(amount_minor_units, 2 * p95, 5 * p95, 70.0, 95.0)
    if amount_dev >= 40:
        reasons.append("amount is well above this person's usual range")

    # --- time anomaly: 0 in window, 35 within 2h, 65 outside, +15 on a public holiday ----
    local = now.astimezone()
    hour = local.hour + local.minute / 60.0
    lo, hi = b["typical_hours_ist"]
    in_window = lo <= hour <= hi
    weekday_ok = local.weekday() in b["typical_days"]
    time_dev = 0.0
    if not in_window:
        distance = min(abs(hour - lo), abs(hour - hi), abs(hour - lo - 24), abs(hour - hi + 24))
        time_dev = 35.0 if distance <= 2.0 else 65.0
    if not weekday_ok:
        time_dev = max(time_dev, 65.0)
    if local.strftime("%m-%d") in _HOLIDAYS:
        time_dev += 15.0
    time_dev = min(100.0, time_dev)
    if time_dev >= 35:
        reasons.append("request arrived outside this person's usual hours")

    # --- beneficiary novelty: 0 known, 55 first-ever, 75 first-ever AND > p95 -----------
    known = beneficiary_id in b.get("known_beneficiaries", [])
    big = amount_minor_units is not None and amount_minor_units > p95
    novelty = 0.0 if known else (75.0 if big else 55.0)
    if not known:
        reasons.append("this person has never paid this beneficiary before")

    # --- lead time compression: 0 at median, 50 at quarter, 85 under 30 minutes --------
    med_lead = float(b.get("median_lead_time_minutes", 0)) or None
    if lead_time_minutes is None:
        lead_dev = 25.0   # unknown lead time is mildly suspicious, not damning
        reasons.append("no deadline context, so compression cannot be scored")
    elif med_lead is None or lead_time_minutes >= med_lead:
        lead_dev = 0.0
    elif lead_time_minutes >= med_lead / 4:
        lead_dev = _interpolate(lead_time_minutes, med_lead / 4, med_lead, 50.0, 0.0)
    else:
        lead_dev = _interpolate(lead_time_minutes, 0.0, med_lead / 4, 85.0, 50.0)
    if lead_dev >= 50:
        reasons.append("deadline is far tighter than this person's normal lead time")

    # --- channel atypicality: 0 typical, 45 known-but-atypical, 70 never used ----------
    ch = channel.strip().lower() or "unknown"
    typical = {str(c).lower() for c in b.get("typical_channels", [])}
    if ch in typical:
        channel_dev = 0.0
    elif any(ch in t for t in typical):
        channel_dev = 45.0
    else:
        # fuzzy: "phone" ~ "voice_call", "chat" ~ "whatsapp_text", "teams_call" ~ "video"
        fuzzy = {"phone": {"voice_call", "telephony"}, "voice_call": {"phone", "telephony"},
                 "chat": {"whatsapp_text", "messaging"}, "video": {"teams_call", "zoom", "conferencing"},
                 "teams_call": {"video", "conferencing"}, "collab_platform": {"messaging"}}
        channel_dev = 45.0 if fuzzy.get(ch, set()) & typical else 70.0
    if channel_dev >= 45:
        reasons.append("request arrived on a channel this person rarely uses")

    # --- velocity: 0 at/below weekly median rate, 60 at 3x, 90 at 5x in 24h -----------
    if requests_last_24h is None:
        velocity_dev = 0.0
    else:
        per_day = float(b.get("median_approvals_per_week", 6)) / 7.0
        if requests_last_24h <= per_day:
            velocity_dev = 0.0
        elif requests_last_24h <= 3 * per_day:
            velocity_dev = _interpolate(requests_last_24h, per_day, 3 * per_day, 0.0, 60.0)
        else:
            velocity_dev = _interpolate(requests_last_24h, 3 * per_day, 5 * per_day, 60.0, 90.0)
        if velocity_dev >= 60:
            reasons.append("unusual burst of requests from this person in the last day")

    components = BehaviourComponents(
        amount_deviation=amount_dev, time_anomaly=time_dev,
        beneficiary_novelty=novelty, lead_time_compression=lead_dev,
        channel_atypicality=channel_dev, velocity_anomaly=velocity_dev,
    )
    raw = sum(getattr(components, k) * w for k, w in COMPONENT_WEIGHTS.items())
    capped = min(raw, BEHAVIOURAL_CAP)

    if raw > capped:
        reasons.append(f"behavioural evidence is capped at {int(BEHAVIOURAL_CAP)}; it never "
                       f"blocks alone")
    if not reasons:
        reasons.append("behaviour fits this person's established pattern")
    return DimensionScore(
        dimension="behavioural",
        score=round(capped, 2),
        reason="; ".join(reasons[:3]).capitalize() + ".",
        evidence_ref=f"contracts/behaviour_baselines.json#{executive_id}",
    )
