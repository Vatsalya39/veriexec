"""Configuration. Every knob is an `INTENTLOCK_`-prefixed environment variable with a safe default.

Two rules this module exists to enforce:

* **The default configuration is the safe one.** `INTENTLOCK_DEMO_ENDPOINTS` unset means the tamper
  route is never registered — not registered-and-refusing, absent (§4.5.1). Anything that has to be
  switched *off* for production is the wrong default.
* **Nothing binds beyond loopback.** `HOST` is not configurable from the environment on purpose. A
  conference network is a hostile network and `0.0.0.0` on one is a live demo of the wrong thing.
"""

from __future__ import annotations

import os
from datetime import timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30), "IST")

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "contracts"
GOLDEN = CONTRACTS / "golden"
VAR = REPO_ROOT / "var"

SERVICE_NAME = "intentlock-audit"
SERVICE_VERSION = "1.0.0"

# Loopback only, deliberately not read from the environment. §4.6.
HOST = "127.0.0.1"
PORT = int(os.environ.get("INTENTLOCK_AUDIT_PORT", "8003"))

# Team A and Team B, consumed over HTTP. Unreachable is a normal state, not an error: the console
# falls back to contracts/golden/ and labels it UPSTREAM_UNAVAILABLE (00_SHARED_CONTEXT §14).
SIGNAL_URL = (os.environ.get("INTENTLOCK_SIGNAL_URL") or os.environ.get("INTENTLOCK_A_URL")
              or "http://127.0.0.1:8001")
CORE_URL = (os.environ.get("INTENTLOCK_CORE_URL") or os.environ.get("INTENTLOCK_B_URL")
            or "http://127.0.0.1:8002")
UPSTREAM_TIMEOUT_S = float(os.environ.get("INTENTLOCK_UPSTREAM_TIMEOUT_S", "3.0"))

# `offline` never calls a language model: the chatbot uses its deterministic templates and every
# number still comes from SQL. It is the default because a demo that needs the network to render a
# sentence is a demo that fails on conference wifi.
MODE = os.environ.get("INTENTLOCK_MODE", "offline")

DB_PATH = Path(os.environ.get("INTENTLOCK_AUDIT_DB", str(VAR / "audit.db")))
HEAD_PATH = Path(os.environ.get("INTENTLOCK_AUDIT_HEAD", str(VAR / "audit_head.txt")))

GENESIS_PREV_HASH = "0" * 64

POLICY_VERSION = os.environ.get("INTENTLOCK_POLICY_VERSION", "1.1.0")


def _flag(name: str) -> bool:
    """Exactly `1` enables. Not `true`, not `yes`, not any non-empty string.

    A flag that turns on because someone exported `INTENTLOCK_DEMO_ENDPOINTS=0` to *disable* it is
    a footgun, and this particular flag registers a route that writes to the database.
    """
    return os.environ.get(name, "") == "1"


def demo_endpoints_enabled() -> bool:
    """Read at import time by `main.py` to decide whether `_tamper` exists at all. §4.5."""
    return _flag("INTENTLOCK_DEMO_ENDPOINTS")


def llm_enabled() -> bool:
    """The kill switch (§20). `offline` mode forces this false regardless of the flag."""
    return MODE != "offline" and _flag("INTENTLOCK_LLM")


def hmac_key() -> bytes:
    """Session salt for PII tokenization and challenge answer MACs.

    Read from the environment when present. Fallback to INTENTLOCK_HMAC_SECRET or a fixed
    development string so test vectors under `contracts/golden/` stay verifiable.
    """
    secret = (os.environ.get("INTENTLOCK_HMAC_KEY")
              or os.environ.get("INTENTLOCK_HMAC_SECRET")
              or "intentlock-dev-fixture-key-not-a-secret")
    return secret.encode()


def ensure_var() -> Path:
    VAR.mkdir(parents=True, exist_ok=True)
    return VAR
