"""Export verifies offline with `scripts/verify_chain.py` — no service running. §4.3, §25

An exported log a third party can check without trusting the thing that produced it is the
difference between an audit trail and a database table.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from services.audit.app.db import AuditStore  # noqa: E402

SCRIPT = REPO_ROOT / "scripts" / "verify_chain.py"


def _seed(store: AuditStore, n: int = 30) -> None:
    for i in range(1, n + 1):
        store.append(event_type="RISK_ASSESSED", actor="system:core",
                     transaction_id=f"TXN-{i:04d}", payload={"risk_score": i})


def test_export_is_ndjson(tmp_path: Path) -> None:
    store = AuditStore(tmp_path / "x.db")
    _seed(store, 5)
    lines = [json.loads(line) for line in store.export_lines()]
    assert len(lines) == 5
    assert all(isinstance(r, dict) and "record_hash" in r for r in lines)


def test_exported_file_verifies_offline(tmp_path: Path) -> None:
    store = AuditStore(tmp_path / "x.db", tmp_path / "head.txt")
    _seed(store, 40)
    export_path = tmp_path / "chain.ndjson"
    export_path.write_text("\n".join(store.export_lines()) + "\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(export_path)],
        capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout and "40" in result.stdout


def test_exported_file_detects_offline_tamper(tmp_path: Path) -> None:
    store = AuditStore(tmp_path / "x.db")
    _seed(store, 40)
    export_path = tmp_path / "chain.ndjson"
    lines = store.export_lines()
    records = [json.loads(line) for line in lines]
    records[10]["payload"]["risk_score"] = 1  # edit after export
    export_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                           encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(export_path)],
        capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert result.returncode != 0
    assert "11" in result.stdout  # seq 11 is the first broken record
