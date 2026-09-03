"""The audit log never stores media — hashes and detector reports only. §25, Invariant 10."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from services.audit.app.db import AuditStore  # noqa: E402


def test_media_key_rejected(tmp_path: Path) -> None:
    store = AuditStore(tmp_path / "m.db")
    blob = base64.b64encode(b"x" * 4096).decode()
    with pytest.raises(ValueError, match="never media"):
        store.append(event_type="COMMUNICATION_RECEIVED", actor="system:core",
                     payload={"audio": blob})


def test_oversized_string_rejected(tmp_path: Path) -> None:
    store = AuditStore(tmp_path / "m.db")
    with pytest.raises(ValueError, match="bytes are refused"):
        store.append(event_type="COMMUNICATION_RECEIVED", actor="system:core",
                     payload={"note": "x" * 2048})


def test_nested_media_rejected(tmp_path: Path) -> None:
    store = AuditStore(tmp_path / "m.db")
    with pytest.raises(ValueError):
        store.append(event_type="COMMUNICATION_RECEIVED", actor="system:core",
                     payload={"meta": {"frames": ["abc"]}})


def test_media_in_list_rejected(tmp_path: Path) -> None:
    store = AuditStore(tmp_path / "m.db")
    with pytest.raises(ValueError):
        store.append(event_type="COMMUNICATION_RECEIVED", actor="system:core",
                     payload={"report": "fine", "clips": [{"video_b64": "AAAA"}]})


def test_detector_report_is_fine(tmp_path: Path) -> None:
    """A verdict plus a content hash is exactly what the log *should* hold."""
    store = AuditStore(tmp_path / "m.db")
    store.append(event_type="COMMUNICATION_RECEIVED", actor="system:core",
                 payload={"detectors": [{"name": "voice", "score": 96, "abstain": False}],
                         "content_sha256": "a" * 64})
    assert store.verify()["ok"] is True
