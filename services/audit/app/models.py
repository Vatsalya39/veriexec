"""Request and response models for the audit API. §24.1

Two jobs, and the second is the one that matters.

**Shape the wire.** FastAPI turns these into the OpenAPI document that `apps/console/` generates its
TypeScript from (§7.1), so a field renamed here shows up as a compile error in the console rather
than as `undefined` on a screen during the demo.

**Refuse the requests that would corrupt the chain.** `event_type` is validated against the frozen
vocabulary here *and* in `db.append`. That duplication is deliberate: the model gives the caller a
422 naming the field, and the store gives anyone bypassing HTTP the same refusal. A rule enforced at
one layer is a rule that holds only for callers who use that layer.

What is deliberately *not* modelled: the `payload` of an audit record. A and B own those schemas and
C stores them opaquely. Declaring `payload: RiskAssessment` here would make C's service reject B's
output the first time B added a field — and B adding a field is a Tuesday, not an incident. The
payload is `dict[str, Any]`, hashed exactly as received.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import chain

# `extra="forbid"` on request bodies: a caller who sends `transactionId` instead of `transaction_id`
# gets a 422 naming the unexpected key, not a silently untagged record. Camel-case drift between a
# TypeScript client and a Python service is the most likely integration bug on this repo, and it is
# invisible if unknown keys are dropped.
_STRICT = ConfigDict(extra="forbid")


class AppendRequest(BaseModel):
    """`POST /v1/audit/append`. §4.1

    `timestamp`, `policy_version` and `policy_hash` are optional so the normal caller omits them and
    gets the service's clock and current policy. A and B may supply their own — a replay harness
    needs to — and the supplied value is what gets hashed.
    """

    model_config = _STRICT

    event_type: str = Field(..., description="One of the frozen §4.2 codes.")
    actor: str = Field(..., min_length=1, max_length=128,
                       description="Which component wrote this: `team_a`, `team_b`, "
                                   "`security_officer`, `auditor`.")
    payload: dict[str, Any] = Field(default_factory=dict,
                                    description="Opaque to C. Hashed exactly as received.")
    transaction_id: str | None = Field(None, max_length=128)
    policy_version: str | None = Field(None, max_length=32)
    policy_hash: str | None = Field(None, max_length=64)
    timestamp: str | None = Field(None, max_length=40,
                                  description="ISO-8601 with offset. Defaults to now in IST.")

    @field_validator("event_type")
    @classmethod
    def _known_event(cls, value: str) -> str:
        """Reject an unknown event type with the whole vocabulary in the message.

        Listing all 21 codes in the error is not verbosity. The caller is a teammate integrating at
        hour 18 who mistyped `DECISION_RENDER`, and the difference between a two-second fix and a
        ten-minute one is whether the answer is in the response body.
        """
        if value not in chain.EVENT_TYPES:
            raise ValueError(f"{value!r} is not in the frozen §4.2 event vocabulary. "
                             f"Known: {', '.join(sorted(chain.EVENT_TYPES))}")
        return value


class AppendResponse(BaseModel):
    """What the appender needs to prove its record landed and to chain the next one itself."""

    seq: int
    record_id: str
    timestamp: str
    prev_hash: str
    record_hash: str


class HeadResponse(BaseModel):
    """`GET /v1/audit/head`. Mirrors `var/audit_head.txt` (§4.4), which the console footer polls."""

    seq: int
    record_hash: str
    record_count: int
    verified_at: str


class VerifyResponse(BaseModel):
    """`GET /v1/audit/verify`. §4.3

    `broken_field` is nullable and `broken_field_source` says where the name came from. A SHA-256
    mismatch proves a record changed; it cannot say *which field* changed. When a field name appears
    it is because the demo tamper route wrote a breadcrumb about itself (`source: "demo_affordance"`),
    never because cryptography recovered it. On a genuinely tampered log the honest answer is
    `broken_field: null` with `first_broken_seq` set — which is already the strong claim.
    """

    ok: bool
    record_count: int
    first_broken_seq: int | None = None
    broken_field: str | None = None
    broken_field_source: Literal["chain_structure", "hash_mismatch", "demo_affordance"] | None = None
    detail: str | None = None
    untrusted_from: int | None = Field(
        None, description="Every record from here on is untrustworthy: a break is inherited.")
    head_hash: str | None = Field(None, description="Null when the chain is broken. There is no "
                                                    "meaningful head past a break.")
    elapsed_ms: float


class RecordOut(BaseModel):
    """One §4.1 record as served.

    `tampered_at`/`tampered_field` are `None` on every record the append path wrote. They are
    populated only by the demo route, sit outside `HASHED_FIELDS`, and are surfaced so the console
    can badge a row as a demo artefact instead of leaving a reviewer to wonder.
    """

    model_config = ConfigDict(extra="ignore")

    seq: int
    record_id: str
    timestamp: str
    event_type: str
    transaction_id: str | None = None
    actor: str
    payload: dict[str, Any]
    policy_version: str
    policy_hash: str
    prev_hash: str
    record_hash: str
    tampered_at: str | None = None
    tampered_field: str | None = None


class RecordsResponse(BaseModel):
    """`GET /v1/audit/records`.

    `count` is the number returned, not the number that exist. `truncated` says whether the limit
    cut the result — without it a console table showing 200 rows cannot tell "that is all of them"
    from "that is the first page", and the difference matters when the question is "how many were
    blocked today".
    """

    count: int
    limit: int
    truncated: bool
    records: list[RecordOut]


class AskRequest(BaseModel):
    """`POST /v1/audit/ask`. §6

    One free-text question, length-capped. The cap is not politeness: this string is the only
    untrusted input the audit service accepts, and §16.3 treats free text as a prompt-injection
    vector. `chat.classify` matches it against a fixed pattern table and never forwards it to a
    model — the model, when enabled at all, sees only the *derived facts* and a template draft, both
    already through `privacy.for_model`.
    """

    model_config = _STRICT

    question: str = Field(..., min_length=1, max_length=500)


class AskResponse(BaseModel):
    """The §6.3 answer contract.

    `record_seqs` is load-bearing, not decoration. `chat.answer` has exactly one non-refusal exit and
    it is unreachable with an empty citation list, so a populated `answer` and an empty `record_seqs`
    is a state this service cannot produce. The console renders each seq as a link into `/audit`.

    `computed_by` and `narrated_by` are published because Invariant 2 is a claim a reviewer should be
    able to check rather than take on trust: arithmetic is always `python`, and `narrated_by` says
    whether a model rephrased the sentence a template had already written.
    """

    answer: str
    record_seqs: list[int]
    facts: dict[str, Any] = Field(default_factory=dict,
                                  description="The numbers behind the prose, for the console to "
                                              "chart without re-parsing the sentence.")
    refused: bool = False
    refusal_kind: Literal["decision", "needs_transaction", "unclassified", "no_records"] | None = None
    intent: str
    computed_by: Literal["python"] = "python"
    narrated_by: Literal["template", "model"] = "template"
    suggestions: list[str] = Field(default_factory=list,
                                   description="The §6.2 menu, sent on a refusal the caller can "
                                               "recover from.")


class TamperRequest(BaseModel):
    """`POST /v1/audit/_tamper`. **Demo only** — §4.5.

    This model exists whether or not the route does; `main.py` decides registration from
    `demo_endpoints_enabled()` at import time, so with the flag unset the path 404s because nothing
    was ever mounted. Not 403 — a 403 tells a reader the capability is present and merely refused.
    """

    model_config = _STRICT

    seq: int = Field(..., ge=1)
    field: str = Field(..., min_length=1, max_length=128,
                       description="A hashed top-level field, or a dotted path like "
                                   "`payload.assessment.risk_score`.")
    value: Any = Field(..., description="The replacement. Typed loosely because the point is to "
                                       "write something the record did not say.")


class TamperResponse(BaseModel):
    seq: int
    field: str
    stored_record_hash: str = Field(..., description="The now-stale hash, so the console can show "
                                                     "stored-vs-recomputed side by side.")
    warning: str


class HealthResponse(BaseModel):
    """`GET /v1/health`. Identical shape across all three services (§24.1).

    `chain_ok` runs the full verify walk on every call. That is a real cost and it is the right
    trade: a health check that reports `ok` while the chain is broken is worse than no health check,
    and at demo scale the walk is milliseconds.
    """

    ok: bool
    chain_ok: bool
    record_count: int
    mode: str
    version: str


class ErrorResponse(BaseModel):
    """Every non-2xx body from this service. §24.2 requires a *typed* error state.

    `error` is a stable machine code the console switches on; `detail` is the sentence a
    human reads. The console must never render a partial result as complete, and it cannot
    honour that rule if failures arrive as untyped 500s.
    """

    error: str
    detail: str


# ------------------------------------------------------------------------ bench + canary


class BenchRunResponse(BaseModel):
    """`POST /v1/bench/run`. The §17 report — metrics with raw fractions, confusion matrix,
    threshold sweep, and the honesty note, so the console can render it without recomputing
    anything (the only arithmetic the console performs is the hash recompute button)."""

    ran_at: str
    mode: str
    policy_version: str
    block_threshold: int
    metrics: dict[str, Any]
    confusion: dict[str, Any]
    sweep: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    honesty: str


class CanaryRunResponse(BaseModel):
    """`POST /v1/canary/run`. One integrity probe, decided now."""

    canary_id: str
    variant: str
    expected: str
    actual: str
    passed: bool
    risk_score: int | None = None
    ran_at: str
    note: str


class CanaryHistoryResponse(BaseModel):
    """`GET /v1/canary/history` — the strip the /canary panel renders."""

    runs: list[dict[str, Any]]
    streak: int
    total: int
    all_passed: bool
    last_failure: dict[str, Any] | None = None
    banner: dict[str, Any] | None = Field(None, description="Present only on a failed canary.")
