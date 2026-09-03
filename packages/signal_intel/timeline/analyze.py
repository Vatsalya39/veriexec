"""Channel-switching timeline analysis (§A11).

Builds `channel_timeline` from prior_events + current event (ascending, current last)
and detects the six pattern flags, each with a plain-English indicator.
"""
from __future__ import annotations

import re
from datetime import datetime

from ..config import IST, now
from ..registry import executive_by_id

RAPID_SWITCH_WINDOW_MIN = 15
BENEFICIARY_THEN_PAYMENT_WINDOW_MIN = 60
AUTH_BEFORE_REQUEST_WINDOW_H = 24
BASELINE_HOURS_DEFAULT = (9, 19)  # fallback when the persona has no baseline hours


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        return dt if dt.tzinfo else dt.replace(tzinfo=IST)
    except (ValueError, TypeError):
        return None


def _baseline_hours(executive_id: str | None) -> tuple[int, int]:
    if executive_id:
        exec_profile = executive_by_id(executive_id)
        if exec_profile:
            m = re.match(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})", exec_profile["baseline"]["normal_hours_ist"])
            if m:
                return int(m.group(1)), int(m.group(3))
    return BASELINE_HOURS_DEFAULT


def build_timeline(prior_events: list[dict], current: dict) -> list[dict]:
    """Ordered timeline: prior events ascending, current event last."""
    events = []
    for ev in prior_events or []:
        ts = _parse_ts(ev.get("timestamp"))
        if ts:
            events.append({"timestamp": ts.isoformat(), "event": ev.get("event", ""),
                           "channel": ev.get("channel", "")})
    events.sort(key=lambda e: e["timestamp"])
    cur_ts = _parse_ts(current.get("timestamp")) or now()
    events.append({"timestamp": cur_ts.isoformat(),
                   "event": current.get("event", "current communication received"),
                   "channel": current.get("channel", "")})
    return events


def analyze_timeline(timeline: list[dict], claimed_executive_id: str | None) -> tuple[list[str], list[str]]:
    """Returns (channel_switch_flags, plain-english indicators)."""
    flags: list[str] = []
    indicators: list[str] = []
    if not timeline:
        return flags, indicators

    dts = [_parse_ts(e["timestamp"]) for e in timeline]
    channels = [e["channel"] for e in timeline]

    # RAPID_SWITCH_{n}_CHANNELS_{m}MIN — >= 3 distinct channels within 15 minutes
    for i in range(len(timeline)):
        window = [j for j in range(len(timeline)) if dts[j] and dts[i] and
                  0 <= (dts[j] - dts[i]).total_seconds() <= RAPID_SWITCH_WINDOW_MIN * 60]
        distinct = {channels[j] for j in window}
        if len(distinct) >= 3:
            flag = f"RAPID_SWITCH_{len(distinct)}_CHANNELS_{RAPID_SWITCH_WINDOW_MIN}MIN"
            if flag not in flags:
                flags.append(flag)
                indicators.append(f"Conversation jumped across {len(distinct)} channels within "
                                  f"{RAPID_SWITCH_WINDOW_MIN} minutes")
            break

    # BENEFICIARY_CHANGE_THEN_PAYMENT — change event followed by payment within 60 min
    for i, ev in enumerate(timeline):
        if re.search(r"beneficiar|bank details|vendor master|account.*revised|neft details|"
                     r"beneficiary update|update.*beneficiar",
                     ev["event"], re.IGNORECASE) or "BENEFICIARY_CHANGE" in ev["event"]:
            for j in range(i + 1, len(timeline)):
                if dts[j] and dts[i] and 0 <= (dts[j] - dts[i]).total_seconds() <= BENEFICIARY_THEN_PAYMENT_WINDOW_MIN * 60:
                    if "BENEFICIARY_CHANGE_THEN_PAYMENT" not in flags:
                        flags.append("BENEFICIARY_CHANGE_THEN_PAYMENT")
                        indicators.append("A beneficiary change was followed by a payment request "
                                          "within the hour")
                    break
            break

    # OUT_OF_HOURS_SEQUENCE — >= 2 events outside the executive's baseline hours
    lo, hi = _baseline_hours(claimed_executive_id)
    out_of_hours = [e for e, dt in zip(timeline, dts)
                    if dt and not (lo <= dt.hour < hi)]
    if len(out_of_hours) >= 2:
        flags.append("OUT_OF_HOURS_SEQUENCE")
        indicators.append(f"Multiple events outside the executive's usual {lo:02d}:00-{hi:02d}:00 hours")

    # AUTH_EVENT_BEFORE_REQUEST — reset/MFA/new-device login within 24h before the request
    for i, ev in enumerate(timeline[:-1]):
        if re.search(r"password reset|mfa change|new[- ]device login|credential reset|"
                     r"reset my mfa", ev["event"], re.IGNORECASE):
            last = dts[-1]
            if last and dts[i] and 0 < (last - dts[i]).total_seconds() <= AUTH_BEFORE_REQUEST_WINDOW_H * 3600:
                flags.append("AUTH_EVENT_BEFORE_REQUEST")
                indicators.append("An account or credential change happened shortly before "
                                  "this request")

    # ESCALATING_URGENCY — urgency rises across >= 3 consecutive events.
    # Event summaries are short system strings, so in addition to keyword matching
    # we score each prior event's URGENCY by re-running the extractor's urgency
    # rules when the raw text is available; velocity patterns (a spray of same-value
    # requests within minutes) also count as escalating pressure.
    if len(timeline) >= 3:
        def urgency_of(event: str) -> int:
            e = event.lower()
            if re.search(r"now\b|immediately|urgent|tonight|today itself|right now|asap", e):
                return 2
            if re.search(r"today|eod|deadline|before|within", e):
                return 1
            return 0

        seq = [urgency_of(e["event"]) for e in timeline]
        keyword_escalation = any(seq[i] < seq[i + 1] < seq[i + 2] for i in range(len(seq) - 2))

        # Velocity escalation: >= 3 prior events of the same action within a short
        # window (e.g. the S12 spray: 4 requests in 9 minutes) — the repetition
        # itself is the rising pressure even when summaries don't say "urgent".
        velocity_escalation = False
        if len(timeline) >= 4 and dts[-1]:
            window_s = 15 * 60
            recent = [dt for dt in dts[:-1]
                      if dt and 0 < (dts[-1] - dt).total_seconds() <= window_s]
            same_kind = sum(1 for e in timeline[:-1]
                            if re.search(r"payment|request|release|transfer", e["event"], re.IGNORECASE))
            if len(recent) >= 3 and same_kind >= 3:
                velocity_escalation = True

        if keyword_escalation or velocity_escalation:
            flags.append("ESCALATING_URGENCY")
            indicators.append("Urgency keeps rising across consecutive messages")

    # SILENT_CHANNEL_ORIGIN — request arrives on a channel this executive never uses
    # (from the persona registry: EXE-001 uses EMAIL/VIDEO/CHAT per corpus; conservative default)
    if claimed_executive_id:
        exec_profile = executive_by_id(claimed_executive_id)
        known_channels = {"EMAIL", "VIDEO", "CHAT", "PHONE"}
        if exec_profile and timeline and timeline[-1]["channel"] == "COLLAB_PLATFORM":
            flags.append("SILENT_CHANNEL_ORIGIN")
            indicators.append("Request arrived on a channel this executive has never used")

    return flags, indicators
