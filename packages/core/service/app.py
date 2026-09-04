"""§23 — B's HTTP edge on `:8002`. The service that serves the rules it enforces.

Three properties this module owns and `assess()` deliberately does not:

  * **It decides nothing.** Every route is a translation layer — parse, call the pure core,
    serialise. `decision` is still written by `policy/decide.py` and by nothing else
    (Invariant 2); no handler here reads it, edits it, or has a branch on it.
  * **No failure becomes a payment.** A taxonomy error, a validation error and an unhandled
    exception all leave as the frozen §14 body carrying a `safe_outcome`, and `safe_outcome`
    is never `APPROVE`. §23 words the rule as *"a 500 from your service must not be
    convertible by a caller into a payment"*; `_fail()` is the single place that is true.
  * **It is the only place in `packages/core/` that reads the wall clock.** `clock.now()` is
    called here, at the edge, and injected downward — which is the whole reason §19.2's
    replay can be byte-identical.

One honest limitation, stated here because it changes how much the binding is worth today:
until B2's authorization store lands, `presented_fingerprint` and `context.reference_fields`
arrive **from the caller**. A caller cannot manufacture a `MATCH` that way — `verify()`
compares the presented hash against a locally recomputed one, and `reference_fields` only
ever explains a mismatch it cannot create — but the artefact's provenance is the caller's
word until B holds the record itself. `GET /v1/policy` publishes that in `degraded`.

`__main__.py` binds this to 127.0.0.1: nothing here should be reachable from another laptop
on a hackathon Wi-Fi network.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import Field, model_validator

from .. import __version__, clock
from ..assess import STUBBED_DIMENSIONS, UNVERIFIED_CLAIMS, assess, preimage_fields
from ..config import settings
from ..crypto.canonical import NonCanonicalValue
from ..crypto.fingerprint import (
    FIELD_SEVERITY,
    FINGERPRINT_FIELDS,
    fingerprint,
    preimage,
    verify,
)
from ..errors import IntentLockError, NotApproved, SchemaViolation
from ..models import (
    AssessInput,
    BreakerState,
    CapabilityToken,
    Inbound,
    RiskAssessment,
    SignalBundle,
    TransactionIntent,
)
from ..policy import constants as K
from ..policy.decide import APPROVE_PRECONDITIONS, HARD_OVERRIDES
from ..policy.version import POLICY_ARTEFACTS, missing_artefacts, policy_hash, policy_version
from ..scoring.fusion import INTENT_EXCLUDED_SIGNALS

log = logging.getLogger("intentlock.core.service")

SERVICE = "core"

#: §13 froze the port. Hard-coding it is what avoids an hour of integration pain.
HOST, PORT = "127.0.0.1", 8002

#: §13. The console and the two sibling services, and nothing else.
CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:8001", "http://127.0.0.1:8001",
    "http://localhost:8002", "http://127.0.0.1:8002",
    "http://localhost:8003", "http://127.0.0.1:8003",
)

#: Which of the two instants an assessment was computed at, published as a response header
#: rather than a body field so the frozen §6.3 contract stays exactly as C already reads it.
CLOCK_SOURCE_HEADER = "X-Assessed-At-Source"

# ------------------------------------------------------------------ request/response shapes

class AssessContext(Inbound):
    """The `context` object from §23's `{intent, signal_bundle, context}`.

    Everything here is an *injected fact about the world* rather than a claim about the
    transaction: the breaker is organizational, the reference pre-image is what was approved,
    and the instant is what makes replay possible.
    """

    reference_fields: dict[str, Any] | None = None
    breaker_state: BreakerState = BreakerState.CLOSED
    now_iso: str | None = None
    #: A caller may only move the clock when it says it is replaying. Time travel in either
    #: direction defeats any validity-window check — a past instant revives an expired
    #: authorization, a future one opens a window that has not opened — so gating on the
    #: *direction* would be theatre. Gating on the *claim* is not: a replay re-runs a stored
    #: record, and it is the record rather than the caller that supplies the instant.
    replay: bool = False
    #: Off by default: a measured duration in the body would make byte-comparison of the 22
    #: golden fixtures noisy for the one caller (C's bench) that most needs it to be exact.
    include_timings: bool = False


class AssessRequest(AssessInput):
    """§23's body: `AssessInput` plus the two key names A and C actually send.

    Accepting both `signal_bundle` (the frozen §6.2 contract name) and `signals` (B's
    internal name) is two lines here and saves a debugging session later. The subclass
    inherits every `AssessInput` field, so the two shapes cannot drift apart.
    """

    signal_bundle: SignalBundle | None = None
    context: AssessContext = Field(default_factory=AssessContext)

    @model_validator(mode="after")
    def _fold_signal_bundle(self) -> AssessRequest:
        if self.signals is None:
            self.signals = self.signal_bundle
        elif self.signal_bundle is not None and self.signal_bundle != self.signals:
            raise ValueError(
                "signals and signal_bundle both supplied and they disagree; send one."
            )
        return self


class FingerprintRequest(Inbound):
    """§23's `{fields}`, plus an `intent` convenience that exists to prevent a real bug.

    Projecting a `TransactionIntent` onto the twelve frozen pre-image fields is exactly the
    step another team would reimplement in TypeScript and get subtly wrong — a float amount,
    a missing key instead of an explicit null — and the symptom would be an intermittent
    `MISMATCH` on someone else's laptop. So B does the projection and publishes it.
    """

    fields: dict[str, Any] | None = None
    intent: TransactionIntent | None = None
    executive_id: str = ""
    nonce: str = ""
    validity_window_start_iso: str = ""
    validity_window_end_iso: str = ""


class VerifyRequest(Inbound):
    presented: str | None = None
    current_fields: dict[str, Any] = Field(default_factory=dict)
    reference_fields: dict[str, Any] | None = None

# ------------------------------------------------------------------------- failing safely

def _headers() -> dict[str, str]:
    """§23: both stamps on *every* response, including every error response."""
    return {"X-Policy-Version": policy_version(), "X-Policy-Hash": policy_hash()}


def _fail(exc: IntentLockError) -> JSONResponse:
    """The single door out of this service for a failure.

    `IntentLockError.__post_init__` already refuses to construct anything whose
    `safe_outcome` is APPROVE, so the guarantee is enforced twice: once at construction and
    once by `test_no_route_can_fail_into_an_approve` over every route.
    """
    return JSONResponse(status_code=exc.http_status, content=exc.body(), headers=_headers())


def _resolve_now(now_iso: str | None, *, replay: bool) -> tuple[datetime, str]:
    """The one wall-clock read in `packages/core/`, and the one judgement on caller time.

    Returns the instant and where it came from. §19.2's replay is only checkable if a stored
    record can be re-assessed at the instant it was first assessed, so caller time is
    supported — but only from a caller that admits it is replaying, because whoever controls
    `now` controls every validity window in both directions. `replay: true` is a claim B can
    at least publish (`X-Assessed-At-Source`) and audit; an unflagged timestamp on the live
    path is a silent authority over expiry, and B2's freshness check lands behind this edge.
    """
    if not now_iso:
        return clock.now(), "service"
    if not replay:
        raise SchemaViolation(
            "now_iso requires context.replay=true. The live path is assessed at the "
            "service's own clock; re-running a stored record is a replay."
        )
    try:
        return clock.parse_iso(now_iso), "caller"
    except ValueError as exc:
        raise SchemaViolation(f"now_iso is not ISO-8601: {exc}") from exc

# ---------------------------------------------------------------- GET /v1/policy, in full

def _degraded() -> dict[str, Any]:
    """What is not real yet, published rather than described.

    Derived from the same two frozensets `assess()` uses for `degraded_reason`, so a scorer
    landing removes its name from this endpoint with no edit here.
    """
    return {
        "degraded_mode": bool(STUBBED_DIMENSIONS or UNVERIFIED_CLAIMS),
        "stubbed_dimensions": sorted(STUBBED_DIMENSIONS),
        "stub_score": K.STUB_SCORE,
        "unverified_claims": sorted(UNVERIFIED_CLAIMS),
        "authorization_store": "caller-supplied until B2 lands; see the module docstring",
        "missing_policy_artefacts": missing_artefacts(),
    }


def _policy_document() -> dict[str, Any]:
    """§23's transparency feature. Open it in a browser tab during the demo.

    *"Here are the rules, served by the system that enforces them"* is more persuasive than a
    slide of the same numbers, and it makes the reproducibility claim checkable in ten
    seconds. Every value is read from `policy/constants.py` at call time — there is no second
    copy of a threshold in this file to fall out of date.
    """
    return {
        "policy_version": policy_version(),
        "policy_hash": policy_hash(),
        "hashed_artefacts": list(POLICY_ARTEFACTS),
        "weights": dict(K.RISK_WEIGHTS),
        "bands": [{"low": lo, "high": hi, "outcome": out} for lo, hi, out in K.BANDS],
        "overrides": [
            {"id": r.id, "wire_code": K.WIRE_OVERRIDE_CODES[r.id], "order": i + 1}
            for i, r in enumerate(HARD_OVERRIDES)
        ],
        "preconditions": [p.id for p in APPROVE_PRECONDITIONS],
        "ceilings_minor_units": {
            "absolute_single_transaction": K.ABSOLUTE_SINGLE_TXN_CEILING,
            "employee_routine": K.EMPLOYEE_ROUTINE_CEILING,
            "low_value_exempt": K.LOW_VALUE_EXEMPT,
            "relative_multiple": (
                f"{K.CEILING_MULTIPLE_NUMERATOR}/{K.CEILING_MULTIPLE_DENOMINATOR}"
            ),
        },
        "abstention": {
            "uncertainty_penalty": K.UNCERTAINTY_PENALTY,
            "min_coverage": K.MIN_COVERAGE,
        },
        "intent_confidence": {
            "weights": dict(K.INTENT_PENALTY_WEIGHTS),
            "excluded_signals": list(INTENT_EXCLUDED_SIGNALS),
            "fingerprint_penalty": dict(K.FINGERPRINT_INTENT_PENALTY),
            "cap_on_mismatch": K.INTENT_CONFIDENCE_CAP_ON_MISMATCH,
        },
        "cooldown": {
            "seconds_per_point": K.COOLDOWN_SECONDS_PER_POINT,
            "max_seconds": K.COOLDOWN_MAX_SECONDS,
        },
        "breaker": dict(K.BREAKER),
        "channel_penalties": dict(K.CHANNEL_PENALTIES),
        "signature_penalties": dict(K.SIGNATURE_PENALTIES),
        "challenge_attempts_allowed": K.CHALLENGE_ATTEMPTS_ALLOWED,
        "replay_risk_approve_ceiling": K.REPLAY_RISK_APPROVE_CEILING,
        "fingerprint_fields": list(FINGERPRINT_FIELDS),
        "field_severity": dict(FIELD_SEVERITY),
        "required_actions": list(K.REQUIRED_ACTIONS),
        "degraded": _degraded(),
    }

# --------------------------------------------------------------- request models (hoisted)

class ChallengeIssueRequest(Inbound):
    intent: TransactionIntent | None = None
    transaction_id: str = ""
    distractors: list[str] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=list)


class ChallengeValidateRequest(Inbound):
    challenge_id: str = ""
    answer: str = ""
    transaction_id: str = ""
    current_fingerprint: str = ""
    attempts_used: int = 0


class DeviceEnrolRequest(Inbound):
    device_id: str = ""
    public_key_spki_b64u: str = ""
    label: str = ""


class SignatureVerifyRequest(Inbound):
    device_id: str = ""
    fingerprint: str = ""
    signature_b64u: str = ""


class TokenMintRequest(Inbound):
    intent: TransactionIntent
    assessment: RiskAssessment


class TokenRedeemRequest(Inbound):
    token: dict[str, Any] = Field(default_factory=dict)
    execution_request: dict[str, Any] = Field(default_factory=dict)


class BreakerCloseRequest(Inbound):
    officer_id: str = ""
    justification: str = ""


class ModeRequest(Inbound):
    mode: str = ""


class RunStartRequest(Inbound):
    """`scenario_id` names a sample in A's corpus (`packages/signal_intel/samples`).

    Hoisted to module scope with the other request models: this module uses PEP 563
    annotations, and a class defined inside `_register_routes` cannot be resolved from
    its own annotation string, so FastAPI would read it as a query parameter.
    """
    scenario_id: str = ""

def _register_routes(app: FastAPI) -> None:
    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        """§13's frozen shape. `make demo` polls all three of these before opening a browser."""
        s = settings()
        return {
            "ok": True,
            "service": SERVICE,
            "version": __version__,
            "mode": f"{s.mode}+llm" if s.llm_available else ("offline" if s.offline else s.mode),
            "policy_version": policy_version(),
            "policy_hash": policy_hash(),
            "degraded_mode": _degraded()["degraded_mode"],
        }

    @app.get("/v1/policy")
    def get_policy() -> dict[str, Any]:
        return _policy_document()

    @app.post("/v1/assess", response_model=RiskAssessment, include_in_schema=False)
    @app.post("/v1/assess-risk", response_model=RiskAssessment)
    def assess_risk(body: AssessRequest, response: Response) -> RiskAssessment:
        """§23's main route: `{intent, signal_bundle, context}` ⇒ a full `RiskAssessment`.

        This handler does four things and none of them is a judgement: resolve the instant,
        call `assess()`, optionally attach its own timing, return. A hostile
        `context.reference_fields` cannot manufacture a `MATCH` — `verify()` recomputes the
        current hash locally and a reference pre-image only ever *explains* a mismatch — so
        the worst a bad reference achieves is a wrong delta list on an already-refused
        request.
        """
        now, source = _resolve_now(body.context.now_iso or body.now_iso,
                                   replay=body.context.replay)
        response.headers[CLOCK_SOURCE_HEADER] = source
        started = clock.now()
        out = assess(
            body,
            reference_fields=body.context.reference_fields,
            breaker_state=body.context.breaker_state,
            now=now,
        )
        if body.context.include_timings:
            elapsed = clock.seconds_between(started, clock.now()) * 1000.0
            out = out.model_copy(update={"latency_ms": {"assess_ms": round(elapsed, 3)}})
        return out

    @app.post("/v1/fingerprint")
    def post_fingerprint(body: FingerprintRequest) -> dict[str, Any]:
        """`{fields}` or `{intent, ...}` ⇒ `{fingerprint, canonical_form_preview}`.

        The preview is the exact string that was hashed, because a preview that is not the
        hashed bytes is useless for the one job it has. It therefore contains the destination
        account in clear: it goes back to the caller that supplied it and must never be
        logged, stored, or forwarded to a model.
        """
        if (body.fields is None) == (body.intent is None):
            raise SchemaViolation("send exactly one of `fields` or `intent`.")
        fields = body.fields
        if fields is None:
            fields = preimage_fields(
                body.intent, executive_id=body.executive_id, nonce=body.nonce,
                window_start=body.validity_window_start_iso,
                window_end=body.validity_window_end_iso,
            )
        try:
            return {
                "fingerprint": fingerprint(fields),
                "canonical_form_preview": preimage(fields),
                "fields": fields,
                "fingerprint_fields": list(FINGERPRINT_FIELDS),
            }
        except (NonCanonicalValue, KeyError) as exc:
            raise SchemaViolation(f"fields are not a canonical pre-image: {exc}") from exc

    @app.post("/v1/fingerprint/verify")
    def post_verify(body: VerifyRequest) -> dict[str, Any]:
        """`⇒ {verdict, deltas[]}`. UNVERIFIABLE when there is nothing to compare — never MATCH."""
        try:
            verdict, found = verify(body.presented, body.current_fields, body.reference_fields)
        except (NonCanonicalValue, KeyError) as exc:
            raise SchemaViolation(f"fields are not a canonical pre-image: {exc}") from exc
        return {
            "verdict": verdict.value,
            "fingerprint_status": verdict.wire(),
            "deltas": [
                {"field": d.field, "expected": d.expected, "presented": d.presented,
                 "severity": d.severity}
                for d in found
            ],
        }

    # ------------------------------------------------------------- B8 challenge endpoints

    _issued_challenges: dict[str, tuple[Any, str, Any]] = {}   # id -> (challenge, txn_fp, issued_at)

    @app.post("/v1/challenge/issue")
    def challenge_issue(body: ChallengeIssueRequest) -> dict[str, Any]:
        """§23. No plaintext answer ever leaves this handler — `expected_answer_hash` only."""
        from .. import challenge as challenge_mod
        from ..crypto.fingerprint import fingerprint as fp
        now = clock.now()
        intent = body.intent
        if intent is None:
            if not body.transaction_id:
                raise SchemaViolation("send an `intent` or a `transaction_id`.")
            intent = TransactionIntent(transaction_id=body.transaction_id)
        ch = challenge_mod.issue(
            intent, distractors=body.distractors, purposes=body.purposes, now=now
        )
        txn_fp = fp(preimage_fields(intent))
        _issued_challenges[ch.challenge_id] = (ch, txn_fp, now)
        from datetime import timedelta
        out = ch.wire()
        out["transaction_id"] = intent.transaction_id
        out["transaction_fingerprint"] = txn_fp
        out["issued_at"] = clock.iso(now)
        out["expires_at"] = clock.iso(now + timedelta(seconds=ch.ttl_seconds))
        out["attempts_used"] = 0
        out["requires_device_signature"] = True
        out.pop("expected_answer_hash", None)   # belt-and-braces: never echo the HMAC
        return out

    @app.post("/v1/challenge/validate")
    def challenge_validate(body: ChallengeValidateRequest) -> dict[str, Any]:
        """§11.4's five outcomes. FINGERPRINT_DRIFT closes the TOCTOU gap (S13)."""
        from .. import challenge as challenge_mod
        now = clock.now()
        stored = _issued_challenges.get(body.challenge_id)
        if stored is None:
            raise SchemaViolation(
                f"challenge {body.challenge_id!r} was not issued by this service"
            )
        ch, txn_fp, issued_at = stored
        from datetime import timedelta
        expires_at = issued_at + timedelta(seconds=ch.ttl_seconds)
        result, left = challenge_mod.validate(
            ch, body.answer, attempts_used=body.attempts_used,
            expires_at=expires_at, now=now,
            current_fingerprint=body.current_fingerprint or None,
            challenge_fingerprint=txn_fp if body.current_fingerprint else None,
        )
        return {"result": result, "attempts_left": left,
                "challenge_id": body.challenge_id,
                "decision": None if result in ("PASSED", "FAILED_RETRY", "EXPIRED") else "BLOCK"}

    # ------------------------------------------------------------- B9 device endpoints

    @app.post("/v1/device/enrol")
    def device_enrol(body: DeviceEnrolRequest) -> dict[str, Any]:
        """Public keys only. Private keys never leave the browser's CryptoKey."""
        if not body.device_id or not body.public_key_spki_b64u:
            raise SchemaViolation("device_id and public_key_spki_b64u are both required.")
        from ..crypto import device_sig
        return device_sig.enrol(body.device_id, body.public_key_spki_b64u, label=body.label)

    @app.post("/v1/signature/verify")
    def signature_verify(body: SignatureVerifyRequest) -> dict[str, Any]:
        """B9. A client-supplied `signature_verified: true` is treated as ABSENT — never valid."""
        from ..crypto import device_sig
        v = device_sig.verify_device_signature(
            device_id=body.device_id, fingerprint_hex=body.fingerprint,
            signature_b64u=body.signature_b64u, now=clock.now(),
        )
        return {"verdict": v.verdict, "reason": v.reason, "device_id": v.device_id}

    # ------------------------------------------------------------- B10 token endpoints

    @app.post("/v1/token/mint")
    def token_mint(body: TokenMintRequest) -> dict[str, Any]:
        """Internal only — the policy mints on APPROVE and refuses otherwise (Invariant 9)."""
        from ..tokens import capability
        try:
            token = capability.mint(body.assessment, body.intent, now=clock.now())
        except capability.TokenError as exc:
            raise NotApproved(exc.message) from exc
        return token.wire()

    @app.post("/v1/token/redeem")
    def token_redeem(body: TokenRedeemRequest) -> dict[str, Any]:
        """Seven named checks. Every attempt — success or failure — is auditable upstream."""
        from ..tokens import capability
        token = CapabilityToken(**body.token)
        try:
            spent, _ = capability.redeem(token, execution_request=body.execution_request,
                                         now=clock.now())
        except capability.TokenError as exc:
            return {"result": "REFUSED", "failure_code": exc.code, "message": exc.message}
        return {"result": "OK", "token": spent.wire()}

    # ------------------------------------------------------------- B12 breaker endpoints

    _breaker_state: dict[str, Any] = {"obj": None}

    def _breaker():
        from ..policy import breaker as breaker_mod
        if _breaker_state["obj"] is None:
            _breaker_state["obj"] = breaker_mod.Breaker()
        return _breaker_state["obj"]

    @app.get("/v1/breaker")
    def breaker_get() -> dict[str, Any]:
        b = _breaker()
        s = b.status
        return {"state": b.state(clock.now()).value, "window_events": len(s.window_events),
                "opens_until": s.opens_until, "trip_reason": s.trip_reason}

    @app.post("/v1/breaker/close")
    def breaker_close(body: BreakerCloseRequest) -> dict[str, Any]:
        """Force-close requires a NAMED officer; anonymous resets are refused."""
        if not body.officer_id.strip():
            raise SchemaViolation(
                "breaker force-close requires a named officer (officer_id); an anonymous "
                "reset is refused."
            )
        b = _breaker()
        note = b.force_close(body.officer_id, body.justification, clock.now())
        return {"state": b.status.state.value, "note": note, "officer_id": body.officer_id}

    # ------------------------------------------------------------- B21 mode + B16 replay

    @app.post("/v1/mode")
    def set_mode(body: ModeRequest) -> dict[str, Any]:
        """Server-side, audited as MODE_CHANGED. Powers C's kill switch (N25b)."""
        from .. import degraded
        try:
            mode = degraded.set_mode(body.mode)
        except ValueError as exc:
            raise SchemaViolation(
                f"mode must be FULL|NO_LLM|NO_DETECTORS|MINIMAL: {exc}"
            ) from exc
        state = degraded.ModeState(mode)
        return {"mode": mode.value, "banner": state.banner()}

    @app.get("/v1/explain/{transaction_id}")
    def explain(transaction_id: str) -> dict[str, Any]:
        """Stored contributions, counterfactuals, graph and summary for C's evidence drawer.

        # MOCKED — a store of issued assessments lands with B2's authorization store; the
        # demo build serves the deterministic re-derivation below for the current corpus.
        """
        return {"transaction_id": transaction_id,
                "note": "MOCKED: per-transaction explain store lands with the authorization "
                        "store; re-assess via /v1/assess-risk for the live contribution table."}

    # ------------------------------------------------------------- run orchestration

    @app.post("/v1/runs")
    def start_run(body: RunStartRequest) -> dict[str, Any]:
        """Start one verification run. The console's live mode drives this.

        Executes the real two-pass pipeline (A → B → C's audit events) in a worker thread
        and narrates each stage as it lands. Nothing here decides anything: the decision
        is whatever `assess()` returned, passed through untouched.
        """
        from pathlib import Path
        if not body.scenario_id:
            raise SchemaViolation("scenario_id is required.")
        sid = body.scenario_id.strip().upper()
        sample_path = (Path(__file__).resolve().parents[2] / "signal_intel"
                       / "samples" / f"{sid}.json")
        if not sample_path.exists():
            raise SchemaViolation(f"no such scenario: {sid}. A's corpus is S01..S22.")
        import json as _json
        sample = _json.loads(sample_path.read_text(encoding="utf-8"))
        from . import runs
        run = runs.start_run(sid, sample)
        return {"run_id": run["run_id"], "attempt": run["attempt"],
                "scenario_id": run["scenario_id"]}

    @app.get("/v1/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        """The whole snapshot in one request: events, status, and the assessment if any."""
        from . import runs
        run = runs.get_run(run_id)
        if run is None:
            raise SchemaViolation(f"no such run: {run_id}")
        return {
            "run_id": run["run_id"], "scenario_id": run["scenario_id"],
            "attempt": run["attempt"], "status": run["status"],
            "started_at": run["started_at"], "ended_at": run["ended_at"],
            "events": list(run["events"]),
            "assessment": run["assessment"],
        }

    @app.get("/v1/runs/{run_id}/events")
    def run_events(run_id: str) -> Any:
        """SSE. One event shape, the console's `WorkflowEvent` contract verbatim."""
        from . import runs
        from fastapi.responses import StreamingResponse
        return runs.sse_response(run_id)

    @app.delete("/v1/runs/{run_id}")
    def cancel_run(run_id: str) -> dict[str, Any]:
        """Stop a run in flight. Between stages is the honest granularity: the pipeline
        never leaves a half-written record, and the console sees `run_cancelled`."""
        from . import runs
        if runs.cancel_run(run_id):
            return {"cancelled": run_id}
        raise SchemaViolation(f"no such running run: {run_id}")


def create_app() -> FastAPI:
    """The app. Constructed rather than module-global so tests get a clean one each time."""
    app = FastAPI(
        title="INTENTLOCK core (Team B)",
        version=__version__,
        description="Risk fusion, transaction fingerprint and authorization. "
                    "Arithmetic and cryptography write the decision.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(CORS_ORIGINS),
        allow_credentials=False,
        # DELETE is the run-cancel verb (`DELETE /v1/runs/:id`); listing it is the cost of
        # the console's stop button, not a broadening of the write surface.
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Policy-Version", "X-Policy-Hash"],
    )

    @app.middleware("http")
    async def _stamp(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(_headers())
        return response

    @app.exception_handler(IntentLockError)
    async def _taxonomy(request: Request, exc: IntentLockError) -> JSONResponse:
        log.info("%s %s -> %s", request.method, request.url.path, exc.error_code)
        return _fail(exc)

    @app.exception_handler(RequestValidationError)
    async def _bad_body(request: Request, exc: RequestValidationError) -> JSONResponse:
        # A malformed body is a caller error, and a caller error still owes the caller a safe
        # direction. `errors()` is echoed because it names the field, not the value.
        return _fail(SchemaViolation(
            "Request body failed contract validation.",
            errors=[{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()[:8]],
        ))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # §23: a 500 must not be convertible by a caller into a payment. The message is
        # deliberately opaque — the traceback goes to the log, not to the network.
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return _fail(IntentLockError(
            error_code="INTERNAL",
            message="The core service failed to complete this assessment.",
            safe_outcome="CHALLENGE",
            http_status=500,
        ))

    _register_routes(app)
    return app


app = create_app()

