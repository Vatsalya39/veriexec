"""Canary transactions are excluded from benchmark metrics and breaker counts. §18, §25"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from services.audit.app import bench, canary  # noqa: E402
from services.audit.app.db import AuditStore  # noqa: E402


def test_bench_rows_never_include_canary() -> None:
    report = bench.run(live=False)
    for row in report["rows"]:
        assert row["is_canary"] is False
        assert row["class"] in ("ATTACK", "LEGIT")


def test_canary_result_is_marked() -> None:
    run = canary.inject()
    assert run["expected"] == "BLOCK"
    # The audit payload carries the flag the console filters on.
    assert "is_canary: true" in run["note"] or "is_canary" in run["note"]


def test_canary_expected_is_always_block() -> None:
    for _ in range(5):
        assert canary.inject()["expected"] == "BLOCK"


def test_canary_audit_record_is_flagged(tmp_path: Path) -> None:
    store = AuditStore(tmp_path / "c.db")
    run = canary.inject()
    store.append(event_type="CANARY_RESULT", actor="system:canary",
                 transaction_id=run["canary_id"],
                 payload={"expected": run["expected"], "actual": run["actual"],
                          "passed": run["passed"], "is_canary": True})
    rows = store.records(event_type="CANARY_RESULT", limit=10)
    assert rows and rows[0]["payload"]["is_canary"] is True
    assert rows[0]["actor"] == "system:canary"


def test_breaker_counts_ignore_canary(tmp_path: Path) -> None:
    """The breaker counts RISK_ASSESSED/BREAKER-worthy events; canaries are recorded under
    CANARY_RESULT, a different event type — so a velocity query over the breaker events
    cannot see them without joining on `is_canary`, which this test asserts is unnecessary."""
    store = AuditStore(tmp_path / "c.db")
    for i in range(5):
        store.append(event_type="RISK_ASSESSED", actor="system:core",
                     transaction_id=f"TXN-{i}", payload={"risk_score": 80 + i})
    run = canary.inject()
    store.append(event_type="CANARY_RESULT", actor="system:canary",
                 transaction_id=run["canary_id"],
                 payload={"passed": run["passed"], "is_canary": True})
    breaker_view = store.records(event_type="RISK_ASSESSED", limit=50)
    canary_view = store.records(event_type="CANARY_RESULT", limit=50)
    assert len(breaker_view) == 5 and len(canary_view) == 1
    assert not any(r["payload"].get("is_canary") for r in breaker_view)


def test_history_reads_empty_as_empty(tmp_path: Path) -> None:
    # Point VAR at a scratch dir via the module's own path conventions.
    from services.audit.app import config
    old = config.VAR
    config.VAR = tmp_path
    try:
        hist = canary.history()
        assert hist["runs"] == [] and hist["streak"] == 0
        assert canary.failure_banner() is None
    finally:
        config.VAR = old
