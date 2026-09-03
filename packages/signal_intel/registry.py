"""Loaders for the frozen contract registries (personas, beneficiaries, duress schemes).

`<TODAY>` / `<NOW-18min>` / `<NOW-2h>` placeholders in beneficiaries.json are resolved
against the injectable clock at load time, so the "modified 18 minutes ago" demo is
always true, whenever we present (shared context §8).
"""
import json
from datetime import timedelta
from functools import lru_cache

from .config import CONTRACTS_DIR, now


def _resolve_placeholder(value: str, ref) -> str:
    if value == "<TODAY>":
        return ref.strftime("%Y-%m-%d")
    if value == "<NOW-18min>":
        return (ref - timedelta(minutes=18)).isoformat()
    if value == "<NOW-2h>":
        return (ref - timedelta(hours=2)).isoformat()
    return value


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def personas() -> dict:
    return _load(CONTRACTS_DIR / "personas.json")


@lru_cache(maxsize=1)
def beneficiaries() -> list:
    data = _load(CONTRACTS_DIR / "beneficiaries.json")
    if isinstance(data, dict) and "beneficiaries" in data:
        return data["beneficiaries"]
    return data


def beneficiary_by_id(beneficiary_id: str):
    for b in beneficiaries():
        if b["beneficiary_id"] == beneficiary_id:
            return b
    return None


def account_for_beneficiary_name(name: str) -> str | None:
    """True registered account for a beneficiary name (after normalization)."""
    from .textnorm import ascii_fold
    target = ascii_fold(name or "")
    if not target:
        return None
    for b in beneficiaries():
        if ascii_fold(b["name"]) == target:
            return b["account"]
    return None


@lru_cache(maxsize=1)
def _duress_registry() -> list:
    return _load(CONTRACTS_DIR / "duress.json")


def duress_scheme_for(executive_id: str):
    """Duress scheme registration for a claimed executive, or None.

    Registry stores only HMAC digests — the plaintext marker is never in the repo.
    """
    for entry in _duress_registry():
        if entry["executive_id"] == executive_id:
            return entry
    return None


def resolve_beneficiary_dates() -> None:
    """Resolve <TODAY>/<NOW-...> placeholders once per run against the clock."""
    ref = now()
    for b in beneficiaries():
        b["first_seen"] = _resolve_placeholder(b["first_seen"], ref)
        b["last_modified"] = _resolve_placeholder(b["last_modified"], ref)


def executive_by_id(executive_id: str):
    for e in personas()["executives"]:
        if e["executive_id"] == executive_id:
            return e
    return None


def employee_by_id(employee_id: str):
    for e in personas()["employees"]:
        if e["employee_id"] == employee_id:
            return e
    return None
