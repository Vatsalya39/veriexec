"""Configuration and the single injectable clock (shared-context rule 12: no scattered now())."""
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3] if Path(__file__).resolve().parents[3].name == "intentfake" else Path(__file__).resolve().parents[2]
CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts" if REPO_ROOT.name != "intentfake" else REPO_ROOT / "contracts"

IST = timezone(timedelta(hours=5, minutes=30))


def _env(key: str, default: str) -> str:
    v = os.environ.get(key, "")
    return v if v else default


@dataclass(frozen=True)
class Config:
    mode: str = _env("INTENTLOCK_MODE", "offline")          # offline | cached | live
    llm_provider: str = _env("INTENTLOCK_LLM_PROVIDER", "anthropic")
    llm_api_key: str = os.environ.get("INTENTLOCK_LLM_API_KEY", "")
    llm_model: str = _env("INTENTLOCK_LLM_MODEL", "")
    seed: int = int(_env("INTENTLOCK_SEED", "1337"))
    hmac_secret: str = _env("INTENTLOCK_HMAC_SECRET", "dev-only-not-a-secret")
    tz: str = _env("INTENTLOCK_TZ", "Asia/Kolkata")
    policy_version: str = _env("INTENTLOCK_POLICY_VERSION", "1.0.0")
    auth_ttl_seconds: int = int(_env("INTENTLOCK_AUTH_TTL_SECONDS", "600"))
    challenge_ttl_seconds: int = int(_env("INTENTLOCK_CHALLENGE_TTL_SECONDS", "120"))


CONFIG = Config()


# The single injectable clock. Every timestamp in this package comes from here —
# never datetime.now() inline (shared-context rule 12). Tests freeze it.
class _Clock:
    def __init__(self) -> None:
        self._frozen: datetime | None = None

    def now(self) -> datetime:
        if self._frozen is not None:
            return self._frozen
        return datetime.now(IST)

    def freeze(self, at: datetime) -> None:
        self._frozen = at.astimezone(IST)

    def unfreeze(self) -> None:
        self._frozen = None

    def iso(self) -> str:
        return self.now().isoformat()


CLOCK = _Clock()


def now() -> datetime:
    return CLOCK.now()
