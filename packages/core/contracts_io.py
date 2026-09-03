"""Reader for `contracts/`.

Two jobs:

1. Resolve the shared relative-date token grammar. `00_SHARED_CONTEXT.md §8` writes
   `<TODAY>`, `<NOW-18min>`, `<NOW-2h>` instead of dates so the demo never goes stale.
   Resolution takes the injected `now`, so replay is deterministic.
2. Never mutate anything under `contracts/` — it is shared-ownership (§4). This module
   is read-only by construction.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from .clock import IST, iso
from .config import settings

_TOKEN = re.compile(r"^<(TODAY|NOW)(?:([+-])(\d+)(s|min|h|d))?>$")
_UNIT = {"s": "seconds", "min": "minutes", "h": "hours", "d": "days"}


class ContractMissing(FileNotFoundError):
    """A shared contract file B depends on has not landed yet."""


def contracts_dir() -> Path:
    return settings().contracts_dir


@lru_cache(maxsize=64)
def _raw(name: str) -> Any:
    p = contracts_dir() / name
    if not p.exists():
        raise ContractMissing(
            f"contracts/{name} is missing. It is shared-ownership (00_SHARED_CONTEXT.md §4); "
            "Team B reads it and never writes it."
        )
    return json.loads(p.read_text(encoding="utf-8"))


def clear_cache() -> None:
    _raw.cache_clear()


def resolve_token(value: str, now: datetime) -> str:
    """`<TODAY-1490d>` -> an ISO date; `<NOW-18min>` -> an ISO datetime with offset."""
    m = _TOKEN.match(value)
    if not m:
        return value
    kind, sign, qty, unit = m.groups()
    delta = timedelta(0)
    if qty:
        delta = timedelta(**{_UNIT[unit]: int(qty)})
        if sign == "-":
            delta = -delta
    if kind == "TODAY":
        return (now.astimezone(IST) + delta).date().isoformat()
    return iso(now + delta)


def resolve(obj: Any, now: datetime) -> Any:
    """Deep-resolve every date token in a loaded contract document."""
    if isinstance(obj, str):
        return resolve_token(obj, now)
    if isinstance(obj, list):
        return [resolve(v, now) for v in obj]
    if isinstance(obj, dict):
        return {k: resolve(v, now) for k, v in obj.items()}
    return obj


def load(name: str, now: datetime) -> Any:
    return resolve(_raw(name), now)


# --------------------------------------------------------------------- typed accessors

def personas(now: datetime) -> dict:
    return load("personas.json", now)


def executives(now: datetime) -> dict[str, dict]:
    return {e["executive_id"]: e for e in personas(now)["executives"]}


def employees(now: datetime) -> dict[str, dict]:
    return {e["employee_id"]: e for e in personas(now)["employees"]}


def actors(now: datetime) -> dict[str, dict]:
    """Executives and employees under one id space — decide() treats both as requesters."""
    out: dict[str, dict] = {}
    for e in personas(now)["executives"]:
        out[e["executive_id"]] = {**e, "actor_id": e["executive_id"], "is_executive": True}
    for e in personas(now)["employees"]:
        out[e["employee_id"]] = {**e, "actor_id": e["employee_id"], "is_executive": False}
    return out


def beneficiaries(now: datetime) -> dict[str, dict]:
    return {b["beneficiary_id"]: b for b in load("beneficiaries.json", now)["beneficiaries"]}


def beneficiary_master(now: datetime) -> dict[str, dict]:
    return {b["id"]: b for b in load("beneficiary_master.json", now)["beneficiaries"]}


def baselines(now: datetime) -> dict:
    return load("behaviour_baselines.json", now)


def device_keys(now: datetime) -> dict[str, dict]:
    return {d["device_id"]: d for d in load("device_keys.json", now)["devices"]}


def golden(scenario_id: str, now: datetime) -> dict:
    p = contracts_dir() / "golden" / f"{scenario_id}.json"
    if not p.exists():
        raise ContractMissing(f"contracts/golden/{scenario_id}.json is missing")
    return resolve(json.loads(p.read_text(encoding="utf-8")), now)


def golden_ids() -> list[str]:
    d = contracts_dir() / "golden"
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("S*.json"))


def as_date(value: str | None) -> date | None:
    """Parse a resolved token back to a date. Accepts a date or a datetime string."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
