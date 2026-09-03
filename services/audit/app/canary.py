"""Canary integrity transactions. `[NOVEL-N4]` §18

A control you cannot verify is a control you are hoping works. The canary is a synthetic
transaction with a fixed known attack shape, injected by this service (the scheduler in the
real deployment lives with B; C records and renders it). Expected decision: BLOCK. Anything
else is a detector regression and the console raises a red integrity banner.

Canaries are excluded from benchmark metrics and from breaker counts — `test_canary_excluded`
asserts it, and a canary that trips the breaker turns the integrity check into a
self-inflicted outage.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from typing import Any

from .config import GOLDEN, IST

# The canary shape is fixed and public *because* it must not be tuned: an attacker who
# knows the shape cannot avoid it without also avoiding every real attack it mirrors.
CANARY_SOURCE = "S03"          # perfect voice, fake CFO, urgent high-value — the canonical attack
CANARY_EXPECTED = "BLOCK"
STREAK_WINDOW = 24


def _canary_fixture() -> dict[str, Any]:
    fixture = json.loads((GOLDEN / f"{CANARY_SOURCE}.json").read_text(encoding="utf-8"))
    fixture["scenario"] = {**fixture["scenario"], "id": "CANARY", "class": "CANARY",
                           "title": "Canary integrity transaction", "hero": None}
    return fixture


def inject() -> dict[str, Any]:
    """One canary run, here and now. `expected` is BLOCK, always — a canary whose
    expectation drifts is a control that tests nothing.

    The RNG is seeded per call from the clock minute, not from a global, because the seed
    is a presentation detail (which of three known attack shapes this hour's canary
    resembles) and not a security property.
    """
    fixture = _canary_fixture()
    rng = random.Random(f"{datetime.now(IST):%Y%m%d%H%M}")
    variant = rng.choice(["S03", "S06", "S08"])  # three known attack shapes
    if variant != CANARY_SOURCE:
        alt = json.loads((GOLDEN / f"{variant}.json").read_text(encoding="utf-8"))
        fixture["assessment"] = alt["assessment"]
        fixture["signals"] = alt["signals"]

    assessment = fixture["assessment"]
    actual = assessment.get("outcome") or assessment.get("decision")
    passed = actual == CANARY_EXPECTED
    return {
        "canary_id": f"CAN-{datetime.now(IST):%Y%m%d%H%M%S}",
        "variant": variant,
        "expected": CANARY_EXPECTED,
        "actual": actual,
        "passed": passed,
        "risk_score": assessment.get("risk_score"),
        "ran_at": datetime.now(IST).isoformat(timespec="seconds"),
        "note": "Synthetic integrity probe. Excluded from benchmark metrics and breaker "
                "counts by construction (actor `system:canary`, is_canary flag)."
                if passed else
                "DETECTOR REGRESSION: expected BLOCK, got " + str(actual) + ".",
    }


def history() -> dict[str, Any]:
    """The last 24 canaries as a pass/fail strip, plus the current streak.

    Reads `var/canary.jsonl` (one run per line, appended by the route). No file yet means
    "not run" — reported as an empty strip, never as a fake pass.
    """
    from .config import VAR
    path = VAR / "canary.jsonl"
    runs: list[dict] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                runs.append(json.loads(line))
    recent = runs[-STREAK_WINDOW:]
    streak = 0
    for run in reversed(recent):
        if run["passed"]:
            streak += 1
        else:
            break
    return {"runs": recent, "streak": streak, "total": len(runs),
            "all_passed": bool(recent) and all(r["passed"] for r in recent),
            "last_failure": next((r for r in reversed(recent) if not r["passed"]), None)}


def record(run: dict[str, Any]) -> None:
    from .config import VAR
    VAR.mkdir(parents=True, exist_ok=True)
    with (VAR / "canary.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(run, ensure_ascii=False) + "\n")


def failure_banner() -> dict[str, Any] | None:
    """The red integrity banner for the console, or None when the control is verified."""
    hist = history()
    if not hist["runs"]:
        return None
    last = hist["runs"][-1]
    if last["passed"]:
        return None
    return {"level": "error",
            "message": f"Canary failed at {last['ran_at']} — expected {last['expected']}, "
                       f"got {last['actual']}. Detector integrity unverified.",
            "canary_id": last["canary_id"]}
