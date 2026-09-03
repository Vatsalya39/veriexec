"""The audit service. FastAPI on `127.0.0.1:8003`. §24.1

Eight routes, one of which does not exist unless you ask for it in the environment.

Three decisions worth reading before changing anything here:

**The tamper route is registered, not gated.** `demo_endpoints_enabled()` is read once at import and
decides whether `@app.post("/v1/audit/_tamper")` is ever evaluated. With the flag unset the path
returns 404 from FastAPI's router because nothing was mounted — not 403 from a handler that checked a
flag. §4.5.1 asks for absent, and the difference is real: a 403 confirms the capability exists.

**Loopback only.** `config.HOST` is a constant, not an environment variable. A conference network is
hostile and this service has no authentication, which is a deliberate scope cut documented in
`docs/THREAT_MODEL.md`. Binding it to `0.0.0.0` would turn a documented cut into a live one.

**Errors are typed.** §24.2 requires the console to be able to tell "no data" from "service broken"
from "bad request", because a dashboard that renders `0` for a missing value commits the exact
`unavailable ≠ clean` failure the project argues against. Every non-2xx body is an `ErrorResponse`
with a stable `error` code, including the ones FastAPI would otherwise shape itself.
"""

from __future__ import annotations

import json
import time
from typing import Any, Iterator

from fastapi import Body, FastAPI, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from . import chat, models
from .canonical import canonical
from .config import (DB_PATH, HEAD_PATH, MODE, SERVICE_VERSION, demo_endpoints_enabled,
                     llm_enabled)
from .db import AuditStore

store = AuditStore(DB_PATH, HEAD_PATH)

app = FastAPI(
    title="INTENTLOCK audit chain",
    version=SERVICE_VERSION,
    description="Tamper-evident hash-chained audit log, offline-verifiable export, and a retrieval "
                "chatbot that cites record numbers and refuses to make decisions.",
    openapi_tags=[
        {"name": "audit", "description": "The chain: append, head, verify, records, export."},
        {"name": "chat", "description": "§6 explainability. Retrieval first, arithmetic in Python."},
        {"name": "bench", "description": "§17 the adversarial benchmark harness."},
        {"name": "canary", "description": "§18 integrity probes and their history."},
        {"name": "demo", "description": "Present only when INTENTLOCK_DEMO_ENDPOINTS=1."},
        {"name": "ops", "description": "Health."},
    ],
)

# The console is a separate origin in development (Vite on :5173). Origins are listed explicitly
# rather than `["*"]`: this service has no authentication, and a wildcard would let any page the
# browser happens to have open read the audit log.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173",
                   "http://127.0.0.1:4173", "http://localhost:4173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def _error(code: int, error: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"error": error, "detail": detail})


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Reshape FastAPI's 422 into `ErrorResponse` so the console has one error shape, not two.

    The first error's message is promoted into `detail` because that is the one a human needs; the
    field path is included because "invalid request" without a field name costs an integration
    partner ten minutes.
    """
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(p) for p in first.get("loc", ()) if p != "body") or "body"
    return _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_request",
                  f"{where}: {first.get('msg', 'failed validation')}")


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    """Last resort. Returns the exception type, never a traceback.

    A traceback in an HTTP body is a disclosure, and on a projector it is a disclosure with an
    audience. The type name is enough to route the bug; the detail is in the server log.
    """
    return _error(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error",
                  f"{type(exc).__name__}. See the service log.")


# ------------------------------------------------------------------------------ chain

@app.post("/v1/audit/append", response_model=models.AppendResponse, tags=["audit"],
          responses={422: {"model": models.ErrorResponse}})
def append_record(body: models.AppendRequest) -> Any:
    """Append one record and return its position and hashes. Serialized against every other append.

    The response carries `prev_hash` as well as `record_hash` so a caller writing several records can
    check the linkage it expects without a second round trip.
    """
    try:
        linked = store.append(
            event_type=body.event_type, actor=body.actor, payload=body.payload,
            transaction_id=body.transaction_id, policy_version=body.policy_version,
            policy_hash=body.policy_hash, timestamp=body.timestamp)
    except ValueError as exc:
        # `db.append` raises on an unknown event type and on media in the payload. Both are the
        # caller's problem and both name the offending field, so the message goes through verbatim.
        return _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "rejected_payload", str(exc))
    return models.AppendResponse(
        seq=linked["seq"], record_id=linked["record_id"], timestamp=linked["timestamp"],
        prev_hash=linked["prev_hash"], record_hash=linked["record_hash"])


@app.get("/v1/audit/head", response_model=models.HeadResponse, tags=["audit"])
def head() -> Any:
    """The current head. Cheap — two indexed queries, no chain walk.

    The console footer polls this; `GET /v1/audit/verify` is the expensive one and is called on
    demand and on a slower timer.
    """
    return models.HeadResponse(**store.head())


@app.get("/v1/audit/verify", response_model=models.VerifyResponse, tags=["audit"])
def verify() -> Any:
    """Walk every record and report the first broken link, with timing. §4.3

    `elapsed_ms` is published because "we verified 12,000 records in 41 ms" is the sentence that
    makes a hash chain feel like an operational control rather than a demo prop.

    Returns 200 even when the chain is broken. A broken chain is a *finding*, not a service failure —
    reporting it as 5xx would make the console's error state swallow the one answer it exists to show.
    """
    started = time.perf_counter()
    result = store.verify()
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return models.VerifyResponse(**result)


@app.get("/v1/audit/records", response_model=models.RecordsResponse, tags=["audit"])
def records(transaction_id: str | None = Query(None, max_length=128),
            event_type: str | None = Query(None, max_length=64),
            since: str | None = Query(None, max_length=40,
                                      description="ISO-8601. Records at or after this timestamp."),
            limit: int = Query(200, ge=1, le=5000),
            order: str = Query("asc", pattern="^(asc|desc)$")) -> Any:
    """Filtered records. §24.1

    `truncated` compares the returned count against the limit so the console can say "showing the
    first 200" instead of implying it showed everything.
    """
    rows = store.records(transaction_id=transaction_id, event_type=event_type, since=since,
                         limit=limit, order=order)
    return models.RecordsResponse(
        count=len(rows), limit=limit, truncated=len(rows) >= limit,
        records=[models.RecordOut(**_flatten(r)) for r in rows])


def _flatten(record: dict[str, Any]) -> dict[str, Any]:
    """`_tampered_*` -> `tampered_*`.

    `db._row_to_record` underscore-prefixes those keys because they are not part of the §4.1 record
    contract. `RecordOut` publishes them without the prefix because on the wire they are ordinary
    optional fields. The rename lives here so neither side has to know about the other's convention.
    """
    out = {k: v for k, v in record.items() if not k.startswith("_")}
    if record.get("_tampered_at"):
        out["tampered_at"] = record["_tampered_at"]
        out["tampered_field"] = record.get("_tampered_field")
    return out


@app.get("/v1/audit/export", tags=["audit"],
         responses={200: {"content": {"application/x-ndjson": {}},
                          "description": "One canonical JSON record per line."}})
def export() -> StreamingResponse:
    """The whole chain as NDJSON, streamed. §24.1

    Each line is the **canonical** form of the record — the same bytes the hash was computed over, so
    `scripts/verify_chain.py` recomputes digests from the file without knowing anything about this
    service. That is the property that makes this an audit trail rather than a database dump: a third
    party can check the log without trusting the thing that produced it.

    Streamed rather than assembled because this is the one endpoint whose response grows without
    bound, and a 200 MB list comprehension is not how the demo should end.
    """
    def lines() -> Iterator[bytes]:
        for line in store.export_lines():
            yield (line + "\n").encode("utf-8")

    return StreamingResponse(
        lines(), media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="intentlock_audit_chain.ndjson"'})


# ------------------------------------------------------------------------------- chat

@app.post("/v1/audit/ask", response_model=models.AskResponse, tags=["chat"])
def ask(body: models.AskRequest) -> Any:
    """Answer a question from the chain, citing record numbers. §6

    Always 200, including for refusals. A refusal is a correct answer with `refused: true` and a
    reason kind — modelling it as 4xx would push it into the console's error branch, and "I can
    explain decisions, I cannot make them" is content, not a failure.

    `narrator=None` keeps this deterministic: `chat.answer` only reaches for a model when it is handed
    one *and* `llm_enabled()`, and the wiring for that lives behind the §20 kill switch rather than
    here. Offline mode never calls out, and every number comes from SQL either way.
    """
    result = chat.answer(store, body.question)
    return models.AskResponse(
        answer=result.prose, record_seqs=result.record_seqs, facts=result.facts,
        refused=result.refused, refusal_kind=result.refusal_kind, intent=result.intent,
        computed_by=result.computed_by, narrated_by=result.narrated_by,
        suggestions=list(chat.QUESTION_MENU) if result.refusal_kind == "unclassified" else [])


# ------------------------------------------------------------------------------ bench

@app.post("/v1/bench/run", response_model=models.BenchRunResponse, tags=["bench"])
def bench_run(live: bool = Query(False, description="Call B's /v1/assess instead of the fixtures.")) -> Any:
    """Run all 22 scenarios and compute the five organizer metrics. `[NOVEL-N13]` §17

    Fixture mode is the default because it is the honest smoke test and needs nothing
    upstream. `live=true` switches to B on :8002 and stamps the mode on every row, so a
    printed number always says what produced it. Results land in `var/bench_latest.json`
    regardless of mode so the console has a stable artifact to read.
    """
    from . import bench
    report = bench.run(live=live)
    print(bench.format_table(report))  # the operator running this by hand gets the table
    return models.BenchRunResponse(**report)


# ---------------------------------------------------------------------------- canary

@app.post("/v1/canary/run", response_model=models.CanaryRunResponse, tags=["canary"])
def canary_run() -> Any:
    """Inject one canary integrity transaction and judge it. `[NOVEL-N4]` §18

    The result is appended to the audit chain under actor `system:canary` with
    `is_canary: true`, and recorded to `var/canary.jsonl` for the strip. Both writes are
    the point: the probe and its verdict are themselves audit records.
    """
    from . import canary
    run = canary.inject()
    canary.record(run)
    store.append(event_type="CANARY_RESULT", actor="system:canary",
                 transaction_id=run["canary_id"],
                 payload={"expected": run["expected"], "actual": run["actual"],
                          "passed": run["passed"], "variant": run["variant"],
                          "risk_score": run["risk_score"], "is_canary": True})
    return models.CanaryRunResponse(**run)


@app.get("/v1/canary/history", response_model=models.CanaryHistoryResponse, tags=["canary"])
def canary_history() -> Any:
    """The last 24 canaries, the current streak, and the failure banner if one exists."""
    from . import canary
    hist = canary.history()
    return models.CanaryHistoryResponse(**hist, banner=canary.failure_banner())


# ------------------------------------------------------------------------------- ops

@app.get("/v1/health", response_model=models.HealthResponse, tags=["ops"])
def health() -> Any:
    """`{ok, chain_ok, record_count, mode, version}` — the same shape all three services serve.

    `ok` is about the service; `chain_ok` is about the data. They are separate fields because they
    fail independently, and a demo needs to be able to say "the service is up and the chain is
    broken, deliberately, watch" without that reading as an outage.
    """
    result = store.verify()
    return models.HealthResponse(
        ok=True, chain_ok=result["ok"], record_count=result["record_count"],
        mode=f"{MODE}{'+llm' if llm_enabled() else ''}", version=SERVICE_VERSION)


# ------------------------------------------------------------------- demo affordance

# Registered only when the flag is set. Read once, at import: with the flag unset the decorator below
# never runs, the path is not in the routing table, and the response is FastAPI's own 404. §4.5.1
# asks for the route to be *absent*, and a handler that returns 403 would instead confirm it exists.
if demo_endpoints_enabled():

    @app.post("/v1/audit/_tamper", response_model=models.TamperResponse, tags=["demo"],
              responses={404: {"model": models.ErrorResponse},
                         422: {"model": models.ErrorResponse}},
              summary="Edit a stored record in place. Demonstration only.")
    def tamper(body: models.TamperRequest = Body(...)) -> Any:
        """Write directly to a row, bypassing the append path, so `verify` can catch it. §4.5

        This is the forty seconds that beats any slide: edit record 47's amount, press Verify, watch
        the chain name 47 and mark everything after it untrusted. It is also a route that mutates the
        audit log, which is why it is absent by default, stamps every row it touches, and returns its
        own warning string.
        """
        try:
            return models.TamperResponse(**store.tamper(body.seq, body.field, body.value))
        except KeyError as exc:
            return _error(status.HTTP_404_NOT_FOUND, "no_such_record", str(exc))
        except ValueError as exc:
            return _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "not_tamperable", str(exc))


@app.get("/", include_in_schema=False)
def root() -> dict[str, Any]:
    """A pointer, not a landing page. Lists what is actually mounted in this process."""
    return {"service": "intentlock-audit", "version": SERVICE_VERSION, "docs": "/docs",
            "demo_endpoints": demo_endpoints_enabled(),
            "routes": sorted({r.path for r in app.routes if getattr(r, "path", "").startswith("/v1")})}


def _print_banner() -> None:
    """Say out loud which mode this process is in, because both modes look identical otherwise."""
    print(f"  intentlock-audit {SERVICE_VERSION}  db={DB_PATH}")
    print(f"  mode={MODE}  llm={'on' if llm_enabled() else 'off'}  "
          f"demo_endpoints={'ON' if demo_endpoints_enabled() else 'off'}")
    if demo_endpoints_enabled():
        print("  WARNING: /v1/audit/_tamper is mounted. Demonstration only.")


def main() -> None:
    """`python -m app.main`. Loopback only — `HOST` is a constant, not a setting."""
    import uvicorn

    from .config import HOST, PORT
    _print_banner()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
