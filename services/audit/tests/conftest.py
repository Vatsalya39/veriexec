"""Test bootstrap. Imports `services.audit.app` as a package-relative application so the tests
never depend on a particular cwd, and provides the temporary store every test file wants."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def set_temp_db(tmp_path: Path, name: str = "audit.db") -> tuple[Path, Path]:
    """Point the audit service at a throwaway database before it is imported.

    `config.py` reads `INTENTLOCK_AUDIT_DB` at import time, so the environment must be set
    before the first import of `services.audit.app.main` — and, because a module is only
    imported once per process, every test that wants isolation must either run first or
    re-import. `fresh_app` below is the honest version of that dance.
    """
    db = tmp_path / name
    head = tmp_path / "audit_head.txt"
    os.environ["INTENTLOCK_AUDIT_DB"] = str(db)
    os.environ["INTENTLOCK_AUDIT_HEAD"] = str(head)
    return db, head
