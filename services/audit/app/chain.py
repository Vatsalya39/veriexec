"""The hash chain: record hashing, linking, and the verification walk. `[NOVEL-N23]`

Deliberately pure. Nothing here opens a database or a socket — it takes dicts and returns dicts, so
`scripts/verify_chain.py` can verify an exported NDJSON file with no service running and no import
from `app.db`. That separation is the difference between an audit trail and a database table: a third
party has to be able to check the log without trusting the thing that produced it.

The record shape is §4.1. `record_hash` covers every other field, including `prev_hash`, which is
what makes the chain a chain: editing record 47 breaks 47's own hash, and 48's `prev_hash` no longer
matches 47's recomputed hash, and so on to the head. Detection does not involve a backup.
"""

from __future__ import annotations

from typing import Any, Iterable

from .canonical import canonical, sha256_hex
from .config import GENESIS_PREV_HASH

# Frozen at G0 (§4.2). A and B write these codes; C stores them and refuses anything else, because
# a vocabulary that accepts free text stops being a vocabulary by hour 12.
EVENT_TYPES: frozenset[str] = frozenset({
    "COMMUNICATION_RECEIVED", "INTENT_CAPTURED", "FINGERPRINT_COMPUTED",
    "RISK_ASSESSED", "CHALLENGE_ISSUED", "CHALLENGE_ANSWERED",
    "SIGNATURE_VERIFIED", "TOKEN_MINTED", "TOKEN_REDEEMED",
    "TOKEN_REDEMPTION_FAILED", "DECISION_RENDERED", "COOLDOWN_STARTED",
    "COOLDOWN_CANCELLED", "BREAKER_TRIPPED", "BREAKER_CLOSED",
    "DURESS_ESCALATED", "CANARY_INJECTED", "CANARY_RESULT",
    "POLICY_REPLAYED", "OFFICER_OVERRIDE", "CHAIN_VERIFIED",
})

# Fields covered by `record_hash`, in the order §4.1 declares them. `record_hash` itself is excluded
# — a hash cannot cover its own output — and `payload_tampered_at` is excluded because the tamper
# route writes it *after* the fact and must not be able to repair the break it just created.
HASHED_FIELDS = ("seq", "record_id", "timestamp", "event_type", "transaction_id", "actor",
                 "payload", "policy_version", "policy_hash", "prev_hash")


def compute_record_hash(record: dict[str, Any]) -> str:
    """SHA-256 over the canonical form of every hashed field. §4.1."""
    missing = [f for f in HASHED_FIELDS if f not in record]
    if missing:
        raise KeyError(f"cannot hash a record missing {missing}")
    return sha256_hex({f: record[f] for f in HASHED_FIELDS})


def link(record: dict[str, Any], prev_hash: str) -> dict[str, Any]:
    """Return `record` with `prev_hash` set and `record_hash` computed. Does not mutate the input."""
    linked = {**record, "prev_hash": prev_hash}
    linked["record_hash"] = compute_record_hash(linked)
    return linked


def _tamper_marker(record: dict[str, Any]) -> tuple[str | None, str | None]:
    """Read the demo affordance's own breadcrumb, if the row carries one.

    A SHA-256 mismatch tells you a record changed. It cannot tell you *which field* changed — that
    information is destroyed by the hash, and any function claiming to recover it from the digest
    alone is guessing. So the field name in `broken_field` never comes from cryptography: it comes
    from `_tampered_field`, which `POST /v1/audit/_tamper` writes about itself (§4.5.2), and it is
    labelled `source: "demo_affordance"` so nobody mistakes one for the other.

    On a real tampered log there is no breadcrumb and `broken_field` is null. That is the correct
    answer. "Record 47's contents no longer match its hash, and 47 onward cannot be trusted" is the
    claim the chain actually supports, and it is already the strong claim.
    """
    field = record.get("_tampered_field")
    at = record.get("_tampered_at")
    return (field, at) if at else (None, None)


def verify(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Walk the chain and report the **first** broken link. §4.3.

    Reports, in order of what a reviewer needs: whether the chain is intact, how many records were
    checked, the first `seq` that failed, why it failed, and — only when the demo tamper route left
    a breadcrumb — which field it changed. Everything from `first_broken_seq` onward is
    untrustworthy, because a break is inherited rather than local, so the caller gets
    `untrusted_from` instead of having to work that out.
    """
    prev = GENESIS_PREV_HASH
    expected_seq = 1
    count = 0
    for record in records:
        count += 1
        seq = record.get("seq")

        if seq != expected_seq:
            # Gapless and monotonic. A deletion shows up here and nowhere else — the surviving
            # records all still hash correctly, which is exactly why deletion is the attack people
            # forget to test for.
            return _broken(count, seq, "seq", "chain_structure",
                           f"Expected record {expected_seq}, found {seq}: a record was deleted, "
                           f"reordered or inserted.")

        if record.get("prev_hash") != prev:
            return _broken(count, seq, "prev_hash", "chain_structure",
                           f"Record {seq} names a predecessor hash that record {seq - 1} does not "
                           f"have. The chain forks, or an earlier record changed.")

        try:
            recomputed = compute_record_hash(record)
        except KeyError as e:
            return _broken(count, seq, "structure", "chain_structure",
                           f"Record {seq} is not hashable: {e}")

        if recomputed != record.get("record_hash"):
            field, at = _tamper_marker(record)
            detail = (f"Record {seq} no longer hashes to its stored value: its contents were "
                      f"changed after it was written.")
            if field:
                detail += f" The demo tamper route recorded editing `{field}` at {at}."
            return _broken(count, seq, field, "demo_affordance" if field else "hash_mismatch",
                           detail)

        prev = record["record_hash"]
        expected_seq += 1

    return {"ok": True, "record_count": count, "first_broken_seq": None,
            "broken_field": None, "broken_field_source": None, "detail": None,
            "untrusted_from": None, "head_hash": prev if count else GENESIS_PREV_HASH}


def _broken(count: int, seq: Any, field: str | None, source: str, detail: str) -> dict[str, Any]:
    return {"ok": False, "record_count": count, "first_broken_seq": seq,
            "broken_field": field, "broken_field_source": source, "detail": detail,
            "untrusted_from": seq, "head_hash": None}
