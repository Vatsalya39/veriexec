"""B12 — the organization-level velocity circuit breaker. [NOVEL-N19, second half]

Per-transaction scoring is blind to campaigns. Five requests that each score 55 look like
five ordinary busy-Friday payments; together they are an attack in progress. The breaker
sees the aggregate. The multi-employee condition is the cheapest genuinely-novel
detection in the project: an attacker who fails against the finance manager tries the
assistant treasurer twelve minutes later, and nothing in a per-request scorer connects
those two events.

While OPEN: no APPROVE for ANY executive; already-minted un-redeemed tokens are FROZEN,
not revoked (revoking them would punish legitimate in-flight payments for someone
else's attack); a named human can force-close, and that override is audited.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..clock import iso, parse_iso, seconds_between
from ..policy.constants import BREAKER
from ..models import BreakerState


@dataclass(frozen=True)
class WindowEvent:
    at: str                    # ISO
    executive_id: str
    risk_score: float
    beneficiary_id: str = ""
    is_canary: bool = False    # canaries never count toward the breaker


@dataclass
class BreakerStatus:
    state: BreakerState = BreakerState.CLOSED
    opened_at: str | None = None
    opens_until: str | None = None
    trip_reason: str = ""
    window_events: tuple[WindowEvent, ...] = ()
    probe_used: bool = False


@dataclass
class Breaker:
    """Rolling-window state machine. `now` is injected everywhere — replay depends on it."""

    status: BreakerStatus = field(default_factory=BreakerStatus)

    def observe(self, event: WindowEvent, now: datetime) -> BreakerState:
        """Record one assessment outcome, then re-trip if the window says so."""
        s = self.status
        if event.is_canary:
            return s.state    # canaries must never trip the breaker (C14's rule)

        window = timedelta(seconds=BREAKER["window_seconds"])
        events = [e for e in s.window_events
                  if seconds_between(parse_iso(e.at), now) <= BREAKER["window_seconds"]]
        events.append(event)
        s.window_events = tuple(sorted(events, key=lambda e: e.at))

        if s.state is BreakerState.CLOSED:
            trip = self._trip_reason(events)
            if trip:
                s.state = BreakerState.OPEN
                s.opened_at = iso(now)
                s.opens_until = iso(now + timedelta(seconds=BREAKER["open_seconds"]))
                s.trip_reason = trip
        return s.state

    @staticmethod
    def _trip_reason(events: list[WindowEvent]) -> str:
        elevated = [e for e in events if e.risk_score >= BREAKER["trip_elevated_threshold"]]
        if len(elevated) >= BREAKER["trip_elevated_count"]:
            ids = sorted({e.executive_id for e in elevated})
            return (f"{len(elevated)} elevated-risk authorization attempts in the last "
                    f"{BREAKER['window_seconds'] // 60} minutes across {len(ids)} "
                    f"requester(s) ({', '.join(ids)})")
        by_exec = [e for e in events if e.risk_score >= BREAKER["trip_multi_employee_threshold"]]
        distinct = {e.executive_id for e in by_exec}
        if len(by_exec) >= BREAKER["trip_multi_employee_count"] and len(distinct) >= 2:
            return (f"Elevated-risk attempts against {len(distinct)} different requesters "
                    f"({', '.join(sorted(distinct))}) inside the window")
        by_ben: dict[str, int] = {}
        for e in events:
            if e.beneficiary_id:
                by_ben[e.beneficiary_id] = by_ben.get(e.beneficiary_id, 0) + 1
        hot = sorted(b for b, n in by_ben.items() if n >= BREAKER["trip_same_beneficiary_count"])
        if hot:
            return (f"Multiple requests to the same new payee ({', '.join(hot)}) inside "
                    f"the window")
        return ""

    def state(self, now: datetime) -> BreakerState:
        """The state at `now`, honouring the open window and the single half-open probe."""
        s = self.status
        if s.state is BreakerState.OPEN:
            if s.opens_until and parse_iso(s.opens_until) <= now:
                s.state = BreakerState.HALF_OPEN
                s.probe_used = False
        return s.state

    def admit_probe(self, now: datetime) -> bool:
        """HALF_OPEN admits exactly one probe. Several probes is not a breaker."""
        if self.status.state is BreakerState.HALF_OPEN and not self.status.probe_used:
            self.status.probe_used = True
            return True
        return False

    def probe_passed(self, now: datetime) -> None:
        self.status.state = BreakerState.CLOSED
        self.status.trip_reason = ""
        self.status.opened_at = None
        self.status.opens_until = None
        self.status.probe_used = False

    def probe_failed(self, now: datetime) -> None:
        s = self.status
        s.state = BreakerState.OPEN
        s.opens_until = iso(now + timedelta(seconds=BREAKER["open_seconds"]))
        s.trip_reason = s.trip_reason or "half-open probe failed"
        s.probe_used = False

    def force_close(self, officer_id: str, justification: str, now: datetime) -> str:
        """A named human may force-close. Anonymous resets are refused."""
        if not officer_id or not officer_id.strip():
            raise ValueError("force_close requires a named officer; anonymous reset refused.")
        s = self.status
        s.state = BreakerState.CLOSED
        s.trip_reason = ""
        s.opened_at = None
        s.opens_until = None
        s.probe_used = False
        return (f"Breaker force-closed by {officer_id} at {iso(now)}: "
                f"{justification or 'no justification supplied'}")

    def frozen_tokens(self) -> bool:
        """While OPEN, un-redeemed tokens are frozen (not revoked) and thaw on re-close."""
        return self.status.state is BreakerState.OPEN
