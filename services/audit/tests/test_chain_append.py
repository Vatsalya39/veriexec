"""Chain construction: linkage, monotonicity, genesis, hash exclusion. §25

These are the properties that must hold on a healthy log so that the tamper tests have
something meaningful to subtract from.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from services.audit.app.config import GENESIS_PREV_HASH as GENESIS  # noqa: E402
from services.audit.app.chain import HASHED_FIELDS, compute_record_hash  # noqa: E402
from services.audit.app.db import AuditStore  # noqa: E402


@pytest.fixture()
def store(tmp_path: Path) -> AuditStore:
    return AuditStore(tmp_path / "chain.db", tmp_path / "head.txt")


def _append(store: AuditStore, i: int) -> dict:
    return store.append(event_type="INTENT_CAPTURED", actor="system:core",
                       transaction_id=f"TXN-{i:04d}", payload={"n": i})


def test_prev_hash_links_each_pair(store: AuditStore) -> None:
    a = _append(store, 1)
    b = _append(store, 2)
    c = _append(store, 3)
    assert a["prev_hash"] == GENESIS
    assert b["prev_hash"] == a["record_hash"]
    assert c["prev_hash"] == b["record_hash"]


def test_seq_monotonic_and_gapless(store: AuditStore) -> None:
    for i in range(10):
        _append(store, i)
    seqs = [r["seq"] for r in store.records(limit=100)]
    assert seqs == list(range(1, 11))


def test_genesis_prev_hash_is_64_zeros(store: AuditStore) -> None:
    first = _append(store, 1)
    assert first["prev_hash"] == "0" * 64


def test_hash_excludes_record_hash_field() -> None:
    """`compute_record_hash` must ignore the field it produces — a hash cannot cover itself."""
    record = {"seq": 1, "record_id": "r", "timestamp": "t", "event_type": "INTENT_CAPTURED",
              "transaction_id": None, "actor": "a", "payload": {"k": 1},
              "policy_version": "1.0.0", "policy_hash": "h", "prev_hash": "0" * 64}
    h1 = compute_record_hash(record)
    record_with_stale_self = {**record, "record_hash": "f" * 64}
    h2 = compute_record_hash(record_with_stale_self)
    assert h1 == h2
    assert "record_hash" not in HASHED_FIELDS


def test_hash_covers_every_declared_field() -> None:
    """Changing any hashed field, including prev_hash, must change the hash."""
    base = {"seq": 1, "record_id": "r", "timestamp": "t", "event_type": "INTENT_CAPTURED",
            "transaction_id": None, "actor": "a", "payload": {"k": 1},
            "policy_version": "1.0.0", "policy_hash": "h", "prev_hash": "0" * 64}
    reference = compute_record_hash(base)
    replacements: dict[str, object] = {
        "seq": 2, "record_id": "r2", "timestamp": "t2", "event_type": "RISK_ASSESSED",
        "transaction_id": "TXN-1", "actor": "b", "payload": {"k": 2},
        "policy_version": "1.0.1", "policy_hash": "h2", "prev_hash": "1" * 64,
    }
    for field in HASHED_FIELDS:
        mutated = dict(base)
        mutated[field] = replacements[field]
        assert compute_record_hash(mutated) != reference, f"hash insensitive to {field}"


def test_missing_field_raises_keyerror() -> None:
    record = {"seq": 1}
    with pytest.raises(KeyError):
        compute_record_hash(record)


def test_head_publishes_after_append(store: AuditStore) -> None:
    _append(store, 1)
    head = store.head()
    assert head["seq"] == 1 and head["record_count"] == 1
    content = (tmp_head := store.head_path).read_text(encoding="utf-8").strip()
    assert content.startswith(head["record_hash"])
