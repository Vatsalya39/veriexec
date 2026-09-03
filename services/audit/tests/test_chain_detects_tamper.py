"""â˜… Tamper detection â€” the claim the demo is built on. Â§4.5, Â§25

Single-field edit, deletion, reordering. Every mutation is written directly to SQLite,
bypassing the append path exactly as an attacker with database access would.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from services.audit.app.db import AuditStore  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture()
def store(tmp_path: Path) -> AuditStore:
    return AuditStore(tmp_path / "tamper.db", tmp_path / "head.txt")


def _seed(store: AuditStore, n: int = 8) -> list[dict]:
    return [store.append(event_type="RISK_ASSESSED", actor="system:core",
                         transaction_id=f"TXN-{i:04d}",
                         payload={"risk_score": i * 10, "amount_minor_units": 1000000 + i})
            for i in range(1, n + 1)]


def _raw_write(store: AuditStore, sql: str, args: tuple = ()) -> None:
    """Talk to SQLite directly — the whole point is to bypass the append path."""
    with sqlite3.connect(store.path) as conn:
        conn.execute(sql, args)


def test_single_field_edit_detected(store: AuditStore) -> None:
    _seed(store)
    _raw_write(store, "UPDATE audit_records SET payload = ? WHERE seq = 4",
               ('{"amount_minor_units":42000000,"risk_score":"40"}',))
    verdict = store.verify()
    assert verdict["ok"] is False
    assert verdict["first_broken_seq"] == 4
    assert verdict["untrusted_from"] == 4
    # The surviving stored hash of record 4 no longer matches its contents.
    assert verdict["head_hash"] is None


def test_editing_a_top_level_field_detected(store: AuditStore) -> None:
    _seed(store)
    _raw_write(store, "UPDATE audit_records SET actor = 'user:attacker' WHERE seq = 2")
    verdict = store.verify()
    assert verdict["ok"] is False and verdict["first_broken_seq"] == 2


def test_record_deletion_detected(store: AuditStore) -> None:
    """Deletion is the attack people forget: the surviving records all still hash correctly."""
    _seed(store, n=10)
    _raw_write(store, "DELETE FROM audit_records WHERE seq = 6")
    verdict = store.verify()
    assert verdict["ok"] is False
    # Record 7 is the first one whose seq is wrong (expected 6, found 7).
    assert verdict["first_broken_seq"] == 7
    assert "deleted" in (verdict["detail"] or "")


def test_reorder_detected(store: AuditStore) -> None:
    _seed(store, n=6)
    _raw_write(store, "UPDATE audit_records SET seq = 60 WHERE seq = 3")
    verdict = store.verify()
    assert verdict["ok"] is False


def test_tamper_route_stamps_breadcrumb(store: AuditStore) -> None:
    _seed(store)
    result = store.tamper(3, "payload.risk_score", "1")
    assert result["warning"] == "This endpoint exists for demonstration and would not ship."
    rows = store.records(event_type="RISK_ASSESSED", limit=10)
    row3 = next(r for r in rows if r["seq"] == 3)
    assert row3["_tampered_field"] == "payload.risk_score"
    assert row3["_tampered_at"]


def test_tamper_leaves_chain_broken_not_repaired(store: AuditStore) -> None:
    """Stamping the breadcrumb must not be able to repair the break it just caused."""
    _seed(store)
    store.tamper(3, "payload.risk_score", "1")
    verdict = store.verify()
    assert verdict["ok"] is False and verdict["first_broken_seq"] == 3
    assert verdict["broken_field"] == "payload.risk_score"
    assert verdict["broken_field_source"] == "demo_affordance"


def test_tamper_rejects_unknown_seq(store: AuditStore) -> None:
    _seed(store, n=2)
    with pytest.raises(KeyError):
        store.tamper(99, "payload.risk_score", "1")


def test_tamper_rejects_seq_field(store: AuditStore) -> None:
    """`seq` is in HASHED_FIELDS but is the primary key â€” tampering it is not a demo, it is a
    structural edit, and the route refuses rather than fakes it."""
    _seed(store, n=2)
    with pytest.raises(ValueError):
        store.tamper(1, "seq", 99)
