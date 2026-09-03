"""Injectable clock. Trap #5 in 02_TEAM_B §26 is calling datetime.now() inside a
scoring function: it makes replay non-deterministic and DIVERGENT_SAME_POLICY is a bug.

Every module that needs the time takes `now: datetime` as an argument. Only the service
edge and the test harness ever call `Clock.now()`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

IST: tzinfo = ZoneInfo(os.environ.get("INTENTLOCK_TZ", "Asia/Kolkata"))


@dataclass
class Clock:
    """Wall clock, or a frozen one for tests and replay."""

    frozen_at: datetime | None = None
    _offset: timedelta = field(default=timedelta(0))

    def now(self) -> datetime:
        if self.frozen_at is not None:
            return self.frozen_at + self._offset
        return datetime.now(tz=IST)

    def today_ist(self):
        return self.now().astimezone(IST).date()

    def advance(self, **kw) -> None:
        """Test-only: move a frozen clock forward."""
        if self.frozen_at is None:
            raise RuntimeError("advance() requires a frozen clock")
        self._offset += timedelta(**kw)

    def freeze(self, at: datetime) -> None:
        self.frozen_at = _aware(at)
        self._offset = timedelta(0)


_CLOCK = Clock()


def clock() -> Clock:
    return _CLOCK


def now() -> datetime:
    """Only for the service edge / fixture loader. Never call from scoring or policy."""
    return _CLOCK.now()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=IST)


def iso(dt: datetime) -> str:
    """ISO-8601 with an explicit offset. The canonical form for every timestamp we hash."""
    return _aware(dt).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    """Tolerant ISO-8601 parse. Naive input is interpreted as IST (INTENTLOCK_TZ)."""
    v = value.strip()
    if v.endswith(("Z", "z")):
        v = v[:-1] + "+00:00"
    return _aware(datetime.fromisoformat(v))


def utc(dt: datetime) -> datetime:
    return _aware(dt).astimezone(timezone.utc)


def seconds_between(earlier: datetime, later: datetime) -> float:
    return (_aware(later) - _aware(earlier)).total_seconds()
