"""Environment contract (00_SHARED_CONTEXT.md §13) plus the two startup guards.

Guards, both from §13 and the Team B security rules:
  * mode=production with the dev HMAC secret still in place  -> refuse to start.
  * dev HMAC secret in any other mode                        -> log a WARNING, continue.
  * INTENTLOCK_DEMO_ENDPOINTS unset -> demo routes must 404 (not 403).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("intentlock.core")

DEV_HMAC_SECRET = "dev-only-not-a-secret"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _int_env(key: str, default: int) -> int:
    raw = _env(key)
    try:
        return int(raw) if raw else default
    except ValueError:
        log.warning("%s=%r is not an integer; using %d", key, raw, default)
        return default


def _float_env(key: str, default: float) -> float:
    raw = _env(key)
    try:
        return float(raw) if raw else default
    except ValueError:
        log.warning("%s=%r is not a float; using %s", key, raw, default)
        return default


@dataclass(frozen=True)
class Settings:
    mode: str
    llm_provider: str
    llm_api_key: str
    seed: int
    hmac_secret: str
    demo_endpoints: bool
    auth_ttl_seconds: int
    challenge_ttl_seconds: int
    policy_version: str
    a_url: str
    b_url: str
    c_url: str
    tz: str
    demo_time_scale: float
    db_path: Path
    contracts_dir: Path

    @property
    def llm_available(self) -> bool:
        """No key => silently fall back to offline. Never crash (§13)."""
        return bool(self.llm_api_key) and self.mode in ("live", "production")

    @property
    def offline(self) -> bool:
        return not self.llm_available


def _read_policy_version(contracts_dir: Path) -> str:
    """contracts/POLICY_VERSION is the source of truth; the env var is the override."""
    env_value = _env("INTENTLOCK_POLICY_VERSION")
    if env_value:
        return env_value
    f = contracts_dir / "POLICY_VERSION"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    return "0.0.0"


def load_settings() -> Settings:
    contracts_dir = Path(_env("INTENTLOCK_CONTRACTS_DIR") or (REPO_ROOT / "contracts"))
    mode = (_env("INTENTLOCK_MODE") or "offline").lower()
    secret = _env("INTENTLOCK_HMAC_SECRET") or DEV_HMAC_SECRET

    if secret == DEV_HMAC_SECRET:
        if mode == "production":
            raise SystemExit(
                "FATAL: INTENTLOCK_MODE=production with the development HMAC secret. "
                "Set INTENTLOCK_HMAC_SECRET to a real secret and restart."
            )
        log.warning("WARNING: using the development HMAC secret")

    db_path = Path(_env("INTENTLOCK_DB_PATH") or (REPO_ROOT / "var" / "intentlock_core.sqlite"))
    return Settings(
        mode=mode,
        llm_provider=(_env("INTENTLOCK_LLM_PROVIDER") or "anthropic").lower(),
        llm_api_key=_env("INTENTLOCK_LLM_API_KEY"),
        seed=_int_env("INTENTLOCK_SEED", 1337),
        hmac_secret=secret,
        demo_endpoints=_env("INTENTLOCK_DEMO_ENDPOINTS") not in ("", "0", "false", "no"),
        auth_ttl_seconds=_int_env("INTENTLOCK_AUTH_TTL_SECONDS", 600),
        challenge_ttl_seconds=_int_env("INTENTLOCK_CHALLENGE_TTL_SECONDS", 120),
        policy_version=_read_policy_version(contracts_dir),
        a_url=_env("INTENTLOCK_A_URL") or "http://127.0.0.1:8001",
        b_url=_env("INTENTLOCK_B_URL") or "http://127.0.0.1:8002",
        c_url=_env("INTENTLOCK_C_URL") or "http://127.0.0.1:8003",
        tz=_env("INTENTLOCK_TZ") or "Asia/Kolkata",
        demo_time_scale=_float_env("INTENTLOCK_DEMO_TIME_SCALE", 1.0),
        db_path=db_path,
        contracts_dir=contracts_dir,
    )


_SETTINGS: Settings | None = None


def settings() -> Settings:
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = load_settings()
    return _SETTINGS


def reload_settings() -> Settings:
    """Test-only: re-read the environment."""
    global _SETTINGS
    _SETTINGS = None
    return settings()


def hmac_key() -> bytes:
    """Token minting refuses to run without a secret (Team B §13 security rules)."""
    s = settings().hmac_secret
    if not s:
        raise SystemExit("FATAL: INTENTLOCK_HMAC_SECRET is unset; refusing to mint tokens.")
    return s.encode("utf-8")
