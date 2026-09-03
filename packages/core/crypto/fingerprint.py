"""B1 — the transaction fingerprint. [NOVEL-N10a, second half]

Dynamic linking, PSD2/FIDO style: the authorization is cryptographically bound to the
*content* of the transaction, so an attacker who owns the channel still cannot change
the destination account after approval without invalidating the approval.

This is the project thesis in one function. `FINGERPRINT_FIELDS` is FROZEN at G0 —
adding, removing or reordering a field silently invalidates every stored authorization
and every golden fixture (Team B §26 trap #1).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum

from .canonical import canonical_bytes, canonical_str, project

#: FROZEN at G0. Order is part of the contract even though the serializer sorts keys:
#: the tuple is what `project()` demands be present, so changing it changes which
#: absent key is an error.
FINGERPRINT_FIELDS: tuple[str, ...] = (
    "transaction_id",
    "executive_id",
    "action",
    "amount_minor_units",  # integer paise — NEVER a float
    "currency",
    "beneficiary_id_or_name",
    "destination_account",
    "purpose",
    "deadline_iso",
    "validity_window_start_iso",
    "validity_window_end_iso",
    "nonce",
)

#: How much a change to each field matters. A `critical` delta is HO-1 and BLOCKs.
#: Everything not listed defaults to `material` — an unknown field is never cosmetic.
FIELD_SEVERITY: dict[str, str] = {
    "destination_account": "critical",
    "amount_minor_units": "critical",
    "beneficiary_id_or_name": "critical",
    "currency": "critical",
    "transaction_id": "critical",
    "executive_id": "critical",
    "action": "material",
    "deadline_iso": "material",
    "nonce": "material",
    "validity_window_start_iso": "material",
    "validity_window_end_iso": "material",
    "purpose": "cosmetic",
}

#: Fields whose values are redacted to their last four characters before they are put
#: in a delta, a log line, an audit event or an LLM prompt.
REDACTED_FIELDS = frozenset({"destination_account"})


class FingerprintVerdict(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    #: NOT a pass. Routes to CHALLENGE via PC-1, never to APPROVE.
    UNVERIFIABLE = "UNVERIFIABLE"

    def wire(self) -> str:
        """The frozen `RiskAssessment.fingerprint_status` vocabulary (§6.3)."""
        return "NOT_YET_VERIFIED" if self is FingerprintVerdict.UNVERIFIABLE else self.value


@dataclass(frozen=True)
class FieldDelta:
    field: str
    expected: str
    presented: str
    severity: str  # "critical" | "material" | "cosmetic"

    def as_dict(self) -> dict:
        return {
            "field": self.field,
            "expected": self.expected,
            "presented": self.presented,
            "severity": self.severity,
        }


def canonicalize(fields: dict) -> bytes:
    """The exact bytes that get hashed. Sorted keys, no whitespace, NFC, explicit nulls."""
    return canonical_bytes(project(fields, FINGERPRINT_FIELDS))


def preimage(fields: dict) -> str:
    """The canonical pre-image as text — for `/v1/fingerprint`, docs and debugging."""
    return canonical_str(project(fields, FINGERPRINT_FIELDS))


def fingerprint(fields: dict) -> str:
    """SHA-256 of the canonical pre-image, lower-case hex."""
    return hashlib.sha256(canonicalize(fields)).hexdigest()


def redact(field: str, value) -> str:
    """Account numbers never appear in full in a delta, a log, or an LLM prompt."""
    if value is None:
        return "(absent)"
    s = str(value)
    if field in REDACTED_FIELDS:
        tail = s[-4:] if len(s) >= 4 else s
        return "X" * max(6, len(s) - 4) + tail
    return s if len(s) <= 80 else s[:77] + "..."


def deltas(reference_fields: dict, current_fields: dict) -> list[FieldDelta]:
    """Field-by-field diff of two pre-images, ordered critical -> material -> cosmetic."""
    out: list[FieldDelta] = []
    for f in FINGERPRINT_FIELDS:
        ref = reference_fields.get(f)
        cur = current_fields.get(f)
        if ref == cur:
            continue
        out.append(
            FieldDelta(
                field=f,
                expected=redact(f, ref),
                presented=redact(f, cur),
                severity=FIELD_SEVERITY.get(f, "material"),
            )
        )
    return sorted(out, key=lambda d: (_SEVERITY_RANK[d.severity], d.field))


_SEVERITY_RANK = {"critical": 0, "material": 1, "cosmetic": 2}


def verify(
    presented: str | None,
    current_fields: dict,
    reference_fields: dict | None,
) -> tuple[FingerprintVerdict, list[FieldDelta]]:
    """Compare what the executive approved with what is about to be executed.

    `presented`        the fingerprint carried by the approval artefact.
    `current_fields`   the pre-image of the transaction as it stands now.
    `reference_fields` the pre-image as it stood when it was approved, if we kept it.

    Returns UNVERIFIABLE — never MATCH — when there is nothing to compare against.
    """
    current = fingerprint(current_fields)

    if not presented:
        return FingerprintVerdict.UNVERIFIABLE, []

    if _ct_eq(presented, current):
        return FingerprintVerdict.MATCH, []

    if reference_fields is None:
        # The hashes differ but we never stored what was approved, so we cannot say
        # *what* changed. Unverifiable, and PC-1 keeps it away from APPROVE.
        return FingerprintVerdict.UNVERIFIABLE, []

    found = deltas(reference_fields, current_fields)
    if not found:
        # Pre-images agree yet the hash does not: the presented value was not produced
        # by this canonicalization. Forged or stale — treat the artefact itself as the
        # critical delta.
        found = [
            FieldDelta(
                field="transaction_fingerprint",
                expected=presented[:12] + "...",
                presented=current[:12] + "...",
                severity="critical",
            )
        ]
    return FingerprintVerdict.MISMATCH, found


def has_critical(found: list[FieldDelta]) -> bool:
    """Selects HO-1's *reason and remedy*, not its outcome.

    Shared Invariant 4 is unconditional — a MISMATCH blocks whatever changed — so HO-1
    fires on any mismatch and this predicate only decides which sentence the operator
    reads: tampering language plus `notify_security_officer` when a critical field moved,
    a stale-authorization sentence plus `reauthorize_with_current_details` when it did not.
    """
    return any(d.severity == "critical" for d in found)


def _ct_eq(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a.strip().lower(), b.strip().lower())
