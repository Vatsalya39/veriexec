"""B16 — policy identity. `policy_version` says which rules; `policy_hash` proves it.

Every `RiskAssessment`, `CapabilityToken`, challenge and audit record carries both. Together
they are what lets an auditor ask "would you catch this today?" and get an answer with two
hashes behind it (§19.2's time-travel audit).
"""

from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from pathlib import Path

from ..config import REPO_ROOT, settings

log = logging.getLogger("intentlock.policy")

#: §19.1 — every file whose contents can change a decision, in FIXED order.
#: Not a glob: directory ordering differs across filesystems, and a hash that depends on
#: the filesystem is not reproducible on the judge's laptop.
#: The two data files are the non-obvious inclusions and the correct ones — changing a
#: payee's trust tier changes decisions, so that data is policy.
POLICY_ARTEFACTS: tuple[str, ...] = (
    "packages/core/policy/decide.py",
    "packages/core/scoring/fusion.py",
    "packages/core/policy/constants.py",
    "contracts/behaviour_baselines.json",
    "contracts/beneficiary_master.json",
)

#: Stands in for an artefact that has not landed yet, so `policy_hash()` is always total.
#: `missing_artefacts()` is asserted empty by the conformance suite.
_ABSENT = b"\x00ABSENT\x00"


def policy_version() -> str:
    """Semver from `contracts/POLICY_VERSION`, bumped by hand (§19.1)."""
    return settings().policy_version


def missing_artefacts() -> list[str]:
    return [p for p in POLICY_ARTEFACTS if not (REPO_ROOT / p).is_file()]


@lru_cache(maxsize=1)
def policy_hash() -> str:
    """SHA-256 over the artefact list, truncated to 16 hex chars for readability."""
    h = hashlib.sha256()
    for rel in POLICY_ARTEFACTS:
        h.update(rel.encode())
        h.update(b"\x00")
        p: Path = REPO_ROOT / rel
        h.update(hashlib.sha256(p.read_bytes()).digest() if p.is_file() else _ABSENT)
    digest = h.hexdigest()[:16]
    absent = missing_artefacts()
    if absent:
        log.warning("policy_hash computed with %d artefact(s) absent: %s",
                    len(absent), ", ".join(absent))
    return digest


def clear_cache() -> None:
    """Tests and `devtools` edit artefacts in-process; the hash must not go stale."""
    policy_hash.cache_clear()


def stamp() -> dict[str, str]:
    """The two fields that go on every artefact B emits."""
    return {"policy_version": policy_version(), "policy_hash": policy_hash()}
