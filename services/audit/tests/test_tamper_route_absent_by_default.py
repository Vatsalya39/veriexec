"""★ The tamper route is absent by default. §4.5.1, §25

With `INTENTLOCK_DEMO_ENDPOINTS` unset the path must 404 because nothing was mounted —
not 403, which would confirm the capability exists and is merely refused.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("INTENTLOCK_AUDIT_DB", str(Path("var") / "absent-default.db"))

from fastapi.testclient import TestClient  # noqa: E402

import services.audit.app.config as config  # noqa: E402


def _client_with(flag: str | None) -> TestClient:
    """Import `main` under a chosen flag value. `config` is reloaded first because `main`
    reads `demo_endpoints_enabled()` at import time; `main` is dropped from `sys.modules`
    so the route table is rebuilt rather than reused.
    """
    if flag is None:
        os.environ.pop("INTENTLOCK_DEMO_ENDPOINTS", None)
    else:
        os.environ["INTENTLOCK_DEMO_ENDPOINTS"] = flag
    sys.modules.pop("services.audit.app.main", None)
    importlib.reload(config)
    import services.audit.app.main as main
    importlib.reload(main)
    return TestClient(main.app)


def test_absent_by_default(tmp_path: Path) -> None:
    os.environ["INTENTLOCK_AUDIT_DB"] = str(tmp_path / "a.db")
    os.environ["INTENTLOCK_AUDIT_HEAD"] = str(tmp_path / "a_head.txt")
    client = _client_with(None)
    r = client.post("/v1/audit/_tamper", json={"seq": 1, "field": "actor", "value": "x"})
    assert r.status_code == 404, "the route must not exist when the flag is unset"
    # And it is not in the routing table at all.
    assert all(getattr(route, "path", "") != "/v1/audit/_tamper"
               for route in client.app.routes)


def test_zero_is_not_one(tmp_path: Path) -> None:
    """`INTENTLOCK_DEMO_ENDPOINTS=0` must NOT enable the route — a truthiness check on a
    non-empty string would turn 'disable it' into 'enable it'."""
    os.environ["INTENTLOCK_AUDIT_DB"] = str(tmp_path / "b.db")
    os.environ["INTENTLOCK_AUDIT_HEAD"] = str(tmp_path / "b_head.txt")
    client = _client_with("0")
    r = client.post("/v1/audit/_tamper", json={"seq": 1, "field": "actor", "value": "x"})
    assert r.status_code == 404


def test_present_only_when_exactly_one(tmp_path: Path) -> None:
    os.environ["INTENTLOCK_AUDIT_DB"] = str(tmp_path / "c.db")
    os.environ["INTENTLOCK_AUDIT_HEAD"] = str(tmp_path / "c_head.txt")
    client = _client_with("1")
    # The db is empty, so the route 404s with `no_such_record` — which proves the route
    # itself answered rather than being absent from the routing table.
    r = client.post("/v1/audit/_tamper", json={"seq": 1, "field": "actor", "value": "x"})
    assert r.status_code == 404
    assert r.json().get("error") == "no_such_record"
    mounted = [route.path for route in client.app.routes
               if getattr(route, "path", "") == "/v1/audit/_tamper"]
    assert mounted, "the route must be mounted when the flag is exactly 1"
    os.environ.pop("INTENTLOCK_DEMO_ENDPOINTS", None)


def test_flag_reader_requires_exactly_one() -> None:
    with patch.dict(os.environ, {"INTENTLOCK_DEMO_ENDPOINTS": "true"}):
        assert config.demo_endpoints_enabled() is False
