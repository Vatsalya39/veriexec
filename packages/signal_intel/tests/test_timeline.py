import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.signal_intel.timeline.analyze import analyze_timeline, build_timeline  # noqa: E402


def _ev(ts, ev, ch):
    return {"timestamp": ts, "event": ev, "channel": ch}


CUR = {"timestamp": "2026-09-03T12:31:00+05:30", "event": "payment request received", "channel": "CHAT"}


def test_rapid_switch():
    evs = [_ev("2026-09-03T10:00:00+05:30", "first contact", "EMAIL"),
          _ev("2026-09-03T10:05:00+05:30", "moved to chat", "CHAT"),
          _ev("2026-09-03T10:10:00+05:30", "now on phone", "PHONE")]
    tl = build_timeline(evs, {**CUR, "timestamp": "2026-09-03T10:12:00+05:30"})
    flags, _ = analyze_timeline(tl, "EXE-001")
    assert any(f.startswith("RAPID_SWITCH_3_CHANNELS") for f in flags)


def test_beneficiary_change_then_payment():
    evs = [_ev("2026-09-03T12:13:00+05:30", "vendor master update: beneficiary account revised", "CHAT")]
    tl = build_timeline(evs, CUR)
    flags, _ = analyze_timeline(tl, "EXE-001")
    assert "BENEFICIARY_CHANGE_THEN_PAYMENT" in flags


def test_out_of_hours():
    evs = [_ev("2026-09-03T21:34:00+05:30", "request 1", "CHAT"),
           _ev("2026-09-03T21:37:00+05:30", "request 2", "CHAT"),
           _ev("2026-09-03T21:40:00+05:30", "request 3", "CHAT")]
    tl = build_timeline(evs, {**CUR, "timestamp": "2026-09-03T21:43:00+05:30"})
    flags, _ = analyze_timeline(tl, "EXE-001")
    assert "OUT_OF_HOURS_SEQUENCE" in flags  # CFO hours are 09-19


def test_auth_event_before_request():
    evs = [_ev("2026-09-03T09:00:00+05:30", "password reset performed", "PORTAL")]
    tl = build_timeline(evs, {**CUR, "timestamp": "2026-09-03T10:00:00+05:30"})
    flags, _ = analyze_timeline(tl, "EXE-001")
    assert "AUTH_EVENT_BEFORE_REQUEST" in flags


def test_escalating_urgency():
    evs = [_ev("2026-09-03T09:00:00+05:30", "when you get a chance", "CHAT"),
           _ev("2026-09-03T10:00:00+05:30", "today please", "CHAT"),
           _ev("2026-09-03T11:00:00+05:30", "right now, urgent", "CHAT")]
    tl = build_timeline(evs, {**CUR, "timestamp": "2026-09-03T11:05:00+05:30"})
    flags, _ = analyze_timeline(tl, "EXE-001")
    assert "ESCALATING_URGENCY" in flags


def test_silent_channel_origin():
    tl = build_timeline([], {"timestamp": "2026-09-03T14:00:00+05:30",
                             "event": "request on collab platform", "channel": "COLLAB_PLATFORM"})
    flags, _ = analyze_timeline(tl, "EXE-001")
    assert "SILENT_CHANNEL_ORIGIN" in flags


def test_timeline_sorted_current_last():
    evs = [_ev("2026-09-03T10:00:00+05:30", "later event", "CHAT"),
           _ev("2026-09-03T09:00:00+05:30", "earlier event", "CHAT")]
    tl = build_timeline(evs, CUR)
    assert tl[-1]["event"] == "payment request received"
    assert tl[0]["event"] == "earlier event"
