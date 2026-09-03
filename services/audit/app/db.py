"""SQLite storage with serialized appends.

The one thing this module must get right is that **two appends never compute `prev_hash` from the
same head**. Two that do produce a fork, and a forked chain fails verification for a reason that has
nothing to do with tampering — which is the worst possible failure, because it makes the real signal
look unreliable. §4.3 requires a test with ten threads; `test_append_serialized.py` is it.

Two mechanisms, belt and braces, because this is cheap and a fork is not:

* A process-wide `threading.Lock` around read-head-then-write. Handles threads in one process,
  which is what uvicorn's default worker model actually gives us.
* `BEGIN IMMEDIATE` on the connection. Takes SQLite's write lock at statement one instead of at
  first write, so a second *process* blocks rather than interleaves.

Neither alone is enough: the lock does nothing across processes, and `BEGIN IMMEDIATE` alone still
lets two threads in one process read the same head before either writes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from . import chain
from .canonical import canonical, sha256_hex
from .config import GENESIS_PREV_HASH, IST, POLICY_VERSION, ensure_var

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_records (
    seq             INTEGER PRIMARY KEY,      -- monotonic, gapless, assigned here
    record_id       TEXT    NOT NULL UNIQUE,
    timestamp       TEXT    NOT NULL,         -- ISO-8601 with +05:30
    event_type      TEXT    NOT NULL,
    transaction_id  TEXT,
    actor           TEXT    NOT NULL,
    payload         TEXT    NOT NULL,         -- canonical JSON
    policy_version  TEXT    NOT NULL,
    policy_hash     TEXT    NOT NULL,
    prev_hash       TEXT    NOT NULL,
    record_hash     TEXT    NOT NULL,
    -- Demo affordance breadcrumbs (§4.5.2). Outside the hashed field set on purpose: writing them
    -- must not be able to repair the break the tamper route just created.
    tampered_at     TEXT,
    tampered_field  TEXT
);
CREATE INDEX IF NOT EXISTS ix_records_txn   ON audit_records(transaction_id);
CREATE INDEX IF NOT EXISTS ix_records_event ON audit_records(event_type);
CREATE INDEX IF NOT EXISTS ix_records_ts    ON audit_records(timestamp);
"""

_ROW_FIELDS = ("seq", "record_id", "timestamp", "event_type", "transaction_id", "actor",
               "payload", "policy_version", "policy_hash", "prev_hash", "record_hash",
               "tampered_at", "tampered_field")


class AuditStore:
    """One store per database file. Safe to share across threads."""

    def __init__(self, path: Path, head_path: Path | None = None) -> None:
        self.path = Path(path)
        self.head_path = head_path
        self._lock = threading.Lock()
        if self.path.parent != Path("."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        # WAL lets the verify walk read while an append is in flight, which matters because verify
        # touches every record and the UI calls it on a timer.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ---------------------------------------------------------------- reads

    def head(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT seq, record_hash FROM audit_records ORDER BY seq DESC LIMIT 1").fetchone()
            count = conn.execute("SELECT COUNT(*) AS n FROM audit_records").fetchone()["n"]
        return {"seq": row["seq"] if row else 0,
                "record_hash": row["record_hash"] if row else GENESIS_PREV_HASH,
                "record_count": count,
                "verified_at": datetime.now(IST).isoformat(timespec="milliseconds")}

    def records(self, transaction_id: str | None = None, event_type: str | None = None,
                since: str | None = None, limit: int = 200,
                order: str = "asc") -> list[dict[str, Any]]:
        where, args = [], []
        if transaction_id:
            where.append("transaction_id = ?")
            args.append(transaction_id)
        if event_type:
            where.append("event_type = ?")
            args.append(event_type)
        if since:
            where.append("timestamp >= ?")
            args.append(since)
        sql = "SELECT * FROM audit_records"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY seq {'DESC' if order == 'desc' else 'ASC'} LIMIT ?"
        args.append(max(1, min(int(limit), 5000)))
        with self._connect() as conn:
            return [_row_to_record(r) for r in conn.execute(sql, args)]

    def iter_all(self) -> Iterator[dict[str, Any]]:
        """Every record in `seq` order. Used by verify and export; streams rather than materializes."""
        with self._connect() as conn:
            for row in conn.execute("SELECT * FROM audit_records ORDER BY seq ASC"):
                yield _row_to_record(row)

    def verify(self) -> dict[str, Any]:
        return chain.verify(self.iter_all())

    def export_lines(self) -> list[str]:
        """The export payload as canonical JSON lines — the bytes each hash covers.

        Kept as a method so tests and the HTTP route share one serialization; the NDJSON
        file is exactly these lines joined with newlines.
        """
        return [canonical(record) for record in self.iter_all()]

    # --------------------------------------------------------------- appends

    def append(self, event_type: str, actor: str, payload: dict[str, Any],
               transaction_id: str | None = None, policy_version: str | None = None,
               policy_hash: str | None = None, timestamp: str | None = None) -> dict[str, Any]:
        """Append one record. Serialized against every other append. §4.3.

        Raises `ValueError` on an event type outside the frozen vocabulary. Free-text event types
        would make every `GROUP BY event_type` in the chatbot silently incomplete.

        Floats in `payload` are normalized to fixed-decimal strings before hashing — see
        `_decimalize`. The record returned reflects what was stored, not what was passed in, because
        the stored form is the one the hash covers and therefore the only one that means anything.
        """
        if event_type not in chain.EVENT_TYPES:
            raise ValueError(f"{event_type!r} is not in the frozen event vocabulary (§4.2). "
                             f"Adding one is a G0 decision, not a runtime one.")
        _reject_media(payload)
        payload = _decimalize(payload)

        record = {
            "record_id": str(uuid.uuid4()),
            "timestamp": timestamp or datetime.now(IST).isoformat(timespec="milliseconds"),
            "event_type": event_type,
            "transaction_id": transaction_id,
            "actor": actor,
            "payload": payload,
            "policy_version": policy_version or POLICY_VERSION,
            "policy_hash": policy_hash or sha256_hex({"policy_version":
                                                      policy_version or POLICY_VERSION}),
        }

        with self._lock:
            with self._connect() as conn:
                # BEGIN IMMEDIATE: take the write lock now, not at the first INSERT. Without it a
                # second *process* can read the same head this one just read.
                conn.execute("BEGIN IMMEDIATE")
                try:
                    row = conn.execute("SELECT seq, record_hash FROM audit_records "
                                       "ORDER BY seq DESC LIMIT 1").fetchone()
                    record["seq"] = (row["seq"] + 1) if row else 1
                    linked = chain.link(record, row["record_hash"] if row else GENESIS_PREV_HASH)
                    conn.execute(
                        "INSERT INTO audit_records (seq, record_id, timestamp, event_type, "
                        "transaction_id, actor, payload, policy_version, policy_hash, prev_hash, "
                        "record_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (linked["seq"], linked["record_id"], linked["timestamp"],
                         linked["event_type"], linked["transaction_id"], linked["actor"],
                         canonical(linked["payload"]), linked["policy_version"],
                         linked["policy_hash"], linked["prev_hash"], linked["record_hash"]))
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
            self._publish_head(linked["seq"], linked["record_hash"])
        return linked

    def _publish_head(self, seq: int, record_hash: str) -> None:
        """Write the head hash to `var/audit_head.txt` after every append. §4.4.

        Best-effort: a filesystem that will not take this file is not a reason to fail an append
        that already committed. The database is the record; this file is a convenience for the
        console footer and for anyone who wants to diff the head without an HTTP call.
        """
        if not self.head_path:
            return
        try:
            ensure_var()
            Path(self.head_path).write_text(f"{record_hash}\t{seq}\n", encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------- demo affordance

    def tamper(self, seq: int, field: str, value: Any) -> dict[str, Any]:
        """Write directly to a row, bypassing the append path. **Demo only** — §4.5.

        Registered by `main.py` only when `INTENTLOCK_DEMO_ENDPOINTS=1`; the route does not exist
        otherwise. Every tamper stamps `tampered_at`/`tampered_field` so a reviewer can tell a demo
        artefact from a real record, and those columns sit outside the hashed field set so stamping
        them cannot repair the break.

        `field` is either a top-level hashed field or a dotted path into `payload`.
        """
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT * FROM audit_records WHERE seq = ?", (seq,)).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    raise KeyError(f"no record at seq {seq}")
                before = _row_to_record(row)

                if field.startswith("payload."):
                    payload = json.loads(row["payload"])
                    _set_path(payload, field.split(".")[1:], value)
                    conn.execute("UPDATE audit_records SET payload = ?, tampered_at = ?, "
                                 "tampered_field = ? WHERE seq = ?",
                                 (canonical(payload),
                                  datetime.now(IST).isoformat(timespec="milliseconds"),
                                  field, seq))
                elif field in chain.HASHED_FIELDS and field != "seq":
                    conn.execute(f"UPDATE audit_records SET {field} = ?, tampered_at = ?, "
                                 f"tampered_field = ? WHERE seq = ?",
                                 (value, datetime.now(IST).isoformat(timespec="milliseconds"),
                                  field, seq))
                else:
                    conn.execute("ROLLBACK")
                    raise ValueError(f"{field!r} is not a tamperable field")
                conn.execute("COMMIT")
            except BaseException:
                # A ROLLBACK inside the try (explicit refusal paths) ends the transaction; a
                # bare second ROLLBACK would raise "no transaction is active" and mask the
                # error the caller was meant to see.
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    pass
                raise
        return {"seq": seq, "field": field,
                "stored_record_hash": before["record_hash"],
                "warning": "This endpoint exists for demonstration and would not ship."}


def _set_path(obj: dict[str, Any], path: list[str], value: Any) -> None:
    for key in path[:-1]:
        obj = obj.setdefault(key, {})
    obj[path[-1]] = value


# Rule 6 of the canonical form is "a float anywhere raises, never coerces", and it is a *shared*
# frozen rule — B's copy of `canonical.py` raises too, and `CANONICAL_JSON_VECTORS.json` is the
# contract between the two. It is the right rule: the fingerprint field set is money and identifiers,
# and a fingerprint computed over a float fails to verify on a different CPU.
#
# But a risk assessment is not a fingerprint. `weight: 0.15` and `points: 19.8` are real fractional
# quantities, and B publishes them as JSON numbers. So the audit envelope — which C owns — carries
# non-integers as **fixed-decimal strings**: `0.15` becomes `"0.15"`. Exact, byte-identical in every
# language, and hash-stable, which is the whole point. The console parses them back for charting.
#
# Recorded as C-10 in docs/CHANGES.md. The alternative — widening `canonical.py` — would have made
# C's copy disagree with B's, and the two disagreeing is the failure the vector file exists to catch.
def _decimalize(obj: Any) -> Any:
    """Convert every float to its exact fixed-decimal string form. Recursive, type-preserving else.

    `Decimal(str(x))` rather than `Decimal(x)`: the former reads the shortest round-trip repr Python
    already guarantees, so `0.15` becomes `"0.15"` and not `"0.1499999999999999944488848768742172"`.
    """
    from decimal import Decimal
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return format(Decimal(str(obj)), "f")
    if isinstance(obj, dict):
        return {k: _decimalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_decimalize(v) for v in obj]
    return obj


def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
    """One SQLite row -> the §4.1 record shape, payload parsed back to a dict.

    `_tampered_*` keys are prefixed with an underscore because they are *not* part of the record
    contract — they are demo metadata that `chain.verify` reads for its breadcrumb and that the
    export carries so an offline verifier sees the same thing the service does.
    """
    record = {
        "seq": row["seq"], "record_id": row["record_id"], "timestamp": row["timestamp"],
        "event_type": row["event_type"], "transaction_id": row["transaction_id"],
        "actor": row["actor"], "payload": json.loads(row["payload"]),
        "policy_version": row["policy_version"], "policy_hash": row["policy_hash"],
        "prev_hash": row["prev_hash"], "record_hash": row["record_hash"],
    }
    if row["tampered_at"]:
        record["_tampered_at"] = row["tampered_at"]
        record["_tampered_field"] = row["tampered_field"]
    return record


# Invariant: no raw biometric or media bytes in the audit log. Detector reports and hashes only.
_MEDIA_KEYS = frozenset({"audio", "video", "frame", "frames", "waveform", "spectrogram",
                         "image", "media", "audio_b64", "video_b64", "raw_audio", "raw_video"})
_MAX_STRING_BYTES = 1024


def _reject_media(payload: dict[str, Any], path: str = "payload") -> None:
    """Refuse to store media. Enforced here rather than trusted from callers.

    `test_audit_never_stores_media.py` asserts this, but the assertion is only as good as the code
    path it exercises. A and B write to this log; a rule that lives in a test they do not run is not
    a rule. Any string over 1 kB is refused too — that is what a base64 blob looks like arriving
    under an innocent key name.
    """
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k.lower() in _MEDIA_KEYS:
                raise ValueError(
                    f"{path}.{k}: the audit log stores detector reports and hashes, never media. "
                    f"Append the detector's verdict and a content hash instead.")
            _reject_media(v, f"{path}.{k}")
    elif isinstance(payload, (list, tuple)):
        for i, v in enumerate(payload):
            _reject_media(v, f"{path}[{i}]")
    elif isinstance(payload, str) and len(payload.encode("utf-8")) > _MAX_STRING_BYTES:
        raise ValueError(f"{path}: {len(payload)} characters. Strings over {_MAX_STRING_BYTES} "
                         f"bytes are refused — that is the shape of an encoded media blob.")
