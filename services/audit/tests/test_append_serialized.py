"""★ Ten threads × 50 appends: the chain must not fork. §4.3, §25

Two concurrent appends that read the same head both write `prev_hash` pointing at it, and a
forked chain fails verification for a reason that has nothing to do with tampering.
"""

from __future__ import annotations

import sqlite3
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from services.audit.app.db import AuditStore  # noqa: E402

N_THREADS = 10
N_PER_THREAD = 50


def test_append_serialized_no_fork(tmp_path: Path) -> None:
    store = AuditStore(tmp_path / "fork.db", tmp_path / "head.txt")
    barrier = threading.Barrier(N_THREADS)
    errors: list[Exception] = []

    def worker(t: int) -> None:
        try:
            barrier.wait()
            for i in range(N_PER_THREAD):
                store.append(event_type="RISK_ASSESSED", actor=f"thread:{t}",
                             transaction_id=f"TXN-{t:02d}{i:03d}",
                             payload={"thread": t, "i": i})
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(N_THREADS)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert not errors, f"appends raised: {errors}"
    expected = N_THREADS * N_PER_THREAD
    verdict = store.verify()
    assert verdict["ok"] is True, verdict
    assert verdict["record_count"] == expected
    seqs = [r["seq"] for r in store.records(limit=5000)]
    assert seqs == list(range(1, expected + 1))


def test_two_processes_cannot_interleave_heads(tmp_path: Path) -> None:
    """`BEGIN IMMEDIATE` is the cross-process half of the guarantee; the lock is the in-process
    half. Two stores over one file is the cheapest honest model of two processes."""
    shared = tmp_path / "shared.db"
    a = AuditStore(shared, tmp_path / "head_a.txt")
    b = AuditStore(shared, tmp_path / "head_b.txt")

    for i in range(25):
        a.append(event_type="INTENT_CAPTURED", actor="proc:a", payload={"i": i})
        b.append(event_type="INTENT_CAPTURED", actor="proc:b", payload={"i": i})

    verdict = a.verify()
    assert verdict["ok"] is True and verdict["record_count"] == 50
    assert b.verify()["ok"] is True
