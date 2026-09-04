"""The run orchestrator: `/v1/runs`, the execution surface the console's live mode drives.

Wraps the two-pass pipeline (`scripts/run_pipeline.py`) in a run registry the console can
start, watch over SSE, poll and cancel. The run executes the *real* logical pipeline —
A's extraction and detectors, B's fusion and policy, the audit events — and reports each
stage as it lands, in the exact event shape `apps/console/src/workflow/contract.ts` defines:

    {seq, ts, type: run_started|stage_started|stage_completed|stage_failed|run_completed
     |run_failed|run_cancelled, stage?, label?, detail?, level?, latencyMs?, payload?}

Design rules, inherited from the service it lives in:

* **It decides nothing.** The decision comes out of `assess()` unchanged; this module only
  narrates progress. A listener that ignores every event except `run_completed` gets the
  same assessment the `/v1/assess-risk` route would have returned.
* **Unreachable is not clean.** If A or the world state cannot be read, the run *fails*
  with `stage_failed` + `run_failed` rather than quietly rendering a fixture as if the
  live pipeline had run (§ "unavailable ≠ clean").
* **LLM perks are live here.** With `INTENTLOCK_MODE=live` (or `cached`) and
  `INTENTLOCK_LLM=1`, A's Ollama enrichment runs on the extract stage, B's investigator
  paragraph on decide, and the kill switch (`/v1/mode`) still forces every one of them off
  with `NO_LLM` — the decision never moves because the model never wrote it.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any

from fastapi.responses import StreamingResponse

from .. import clock
from ..config import settings

#: The stage plan, in execution order. Mirrors the console's `contract.ts` blueprint, which
#: itself mirrors the six `timeline` stages every golden fixture carries. One source of truth
#: per side: this list must never disagree with `PIPELINE` in `contract.ts`.
STAGE_PLAN: tuple[tuple[str, str, str], ...] = (
    # (stage, label, detail-narration key)
    ("ingest", "Communication received", "Arrived on the request channel."),
    ("extract", "Intent extracted", "Deterministic parse, LLM enrichment, fingerprint fields."),
    ("detect", "Detectors scored", "Voice, video, stylometry, behaviour, beneficiary."),
    ("fuse", "Dimensions fused", "Weighted arithmetic with an explicit uncertainty penalty."),
    ("decide", "Policy applied", "Bands, floors, hard overrides — the frozen decision."),
    ("record", "Audited", "Events landed on the tamper-evident chain."),
)

_RUNS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _now_iso() -> str:
    return clock.now().isoformat(timespec="milliseconds")


class _ReuseBackend:
    """Feeds `run_sample` the A result this run already produced.

    The narration path calls A once (to report ingest/extract/detect as they happen);
    `run_sample` needs the same A output for its two assess passes. Replaying it here keeps
    the pipeline single-run — with the LLM on, that is one Ollama extraction instead of two,
    and the narrated `extraction_mode` is by construction the mode the assessment saw.
    """

    def __init__(self, produced: dict) -> None:
        self._produced = produced

    def process(self, request: dict) -> dict:
        return self._produced

    def project(self, intent: dict, *, executive_id: str, nonce: str,
                window: tuple[str, str]) -> tuple[dict, str]:
        from scripts.run_pipeline import Backend
        return Backend().project(intent, executive_id=executive_id, nonce=nonce,
                                 window=window)

    def assess(self, payload: dict, *, reference_fields: dict | None,
               breaker_state, now_iso: str) -> dict:
        from scripts.run_pipeline import Backend
        return Backend().assess(payload, reference_fields=reference_fields,
                                breaker_state=breaker_state, now_iso=now_iso)


def _emit(run: dict[str, Any], type_: str, **fields: Any) -> None:
    """Append one event under the run's lock. Everything a listener sees passes here."""
    ev = {"seq": len(run["events"]) + 1, "ts": _now_iso(), "type": type_, **fields}
    run["events"].append(ev)


def _stage_payload(sample: dict, produced: dict | None) -> dict[str, Any]:
    """Small, non-PII facts for the console's expandable rows."""
    if produced is None:
        return {}
    intent = produced.get("intent") or {}
    signals = produced.get("signals") or {}
    return {
        "transaction_id": intent.get("transaction_id"),
        "action": intent.get("action"),
        "extraction_mode": intent.get("extraction_mode"),
        "detector_reports": len(signals.get("detector_reports") or []),
    }


def _llm_on() -> bool:
    """Whether A's Ollama enrichment is active for runs started now.

    The kill switch (`degraded`) is checked first so `NO_LLM`/`MINIMAL` wins over the env
    flag — that ordering is the whole N25b demo: flip the switch, the model path goes dark
    even in live mode, and the decision is byte-identical. A reads the same env contract
    (`INTENTLOCK_MODE` != offline) through its own config, so this is a narration hint,
    never a second source of truth.
    """
    from .. import degraded
    if not degraded.llm_enabled():
        return False
    return settings().mode != "offline"


def _execute(run: dict[str, Any], sample: dict) -> None:
    """Run the real two-pass pipeline, narrating as it goes. Runs on a worker thread.

    Stage boundaries are the pipeline's own seams: A (ingest+extract+detect), B (fuse+decide),
    C's events (record). No stage result is invented here — each narrates what the layer
    it just called actually returned.
    """
    from scripts import run_pipeline as rp
    from scripts import world_state as ws_mod

    run_id = run["run_id"]
    started = time.perf_counter()
    try:
        world = ws_mod.read(sample)
    except Exception as exc:
        _emit(run, "run_started", label="Run opened",
              detail=f"{run['scenario_id']} · {run['scenario_title']}")
        _emit(run, "stage_failed", stage="ingest", label="ingest failed",
              detail=f"the scenario's world state could not be read: {exc}", level="error",
              payload={"retryable": False})
        _emit(run, "run_failed", label="Run failed",
              detail="No decision was rendered — the scenario itself could not be read.",
              level="error")
        return

    _emit(run, "run_started", label="Run opened",
          detail=(f"{run['scenario_id']} · {run['scenario_title']} · "
                  f"policy {rp._policy_version()} · "
                  f"{'LLM live (extraction enrichment + investigation prose)' if _llm_on() else 'LLM off — deterministic core only'}"))

    # ---- Part 1: A (ingest, extract, detect) ----------------------------------------
    t0 = time.perf_counter()
    _emit(run, "stage_started", stage="ingest", label="Ingest communication — running",
          detail=STAGE_PLAN[0][2], level="info")
    try:
        produced = rp.Backend().process({
            "channel": sample["channel"],
            "raw_text_or_transcript": sample["raw_text_or_transcript"],
            "metadata": sample["metadata"],
            "sample_id": world.sample_id,
            "detector_script": sample.get("detector_script") or {},
            "freshness_token": None,
            "freshness_echoed": sample.get("freshness_echoed"),
        })
        intent, signals = produced["intent"], produced["signals"]
    except Exception as exc:
        _emit(run, "stage_failed", stage="ingest", label="ingest failed",
              detail=f"A did not answer: {exc}", level="error",
              payload={"retryable": True})
        _emit(run, "run_failed", label="Run failed",
              detail="No decision was rendered. The engine refused to score a dimension it "
                      "could not read, so the run stops rather than guessing.",
              level="error", payload={"failed_at": "ingest", "retryable": True})
        return
    run["transaction_id"] = str(produced["intent"].get("transaction_id") or "")
    _emit(run, "stage_completed", stage="ingest", label=STAGE_PLAN[0][1],
          detail=f"Arrived on {sample.get('channel', '?')}.",
          level="success", latencyMs=round((time.perf_counter() - t0) * 1000, 1),
          payload={"channel": sample.get("channel"), "sample_id": world.sample_id})

    if run["cancelled"]:
        _emit(run, "run_cancelled", label="Run cancelled",
              detail="Stopped by the reviewer before extraction.", level="warn")
        return

    # ---- extract --------------------------------------------------------------------
    t0 = time.perf_counter()
    _emit(run, "stage_started", stage="extract", label="Extract intent — running",
          detail=STAGE_PLAN[1][2], level="info")
    mode = str(intent.get("extraction_mode") or "deterministic")
    _emit(run, "stage_completed", stage="extract", label=STAGE_PLAN[1][1],
          detail=(f"Extraction mode {mode}"
                  + (" · deterministic parser is authoritative on money and accounts" if
                     mode in ("llm", "hybrid") else "")),
          level="success", latencyMs=round((time.perf_counter() - t0) * 1000, 1),
          payload=_stage_payload(sample, {"intent": intent, "signals": signals}))

    if run["cancelled"]:
        _emit(run, "run_cancelled", label="Run cancelled", level="warn",
              detail="Stopped by the reviewer before the detectors ran.")
        return

    # ---- detect ---------------------------------------------------------------------
    t0 = time.perf_counter()
    _emit(run, "stage_started", stage="detect", label="Score detectors — running",
          detail=STAGE_PLAN[2][2], level="info")
    n_det = len(signals.get("detector_reports") or [])
    abstains = [r["name"] for r in signals.get("detector_reports") or [] if r.get("abstain")]
    _emit(run, "stage_completed", stage="detect", label=STAGE_PLAN[2][1],
          detail=(f"{n_det} detector reports" + (f", {len(abstains)} abstaining" if abstains
                                                  else ", none abstaining")),
          level="success", latencyMs=round((time.perf_counter() - t0) * 1000, 1),
          payload={"detector_reports": n_det, "abstaining": abstains})

    if run["cancelled"]:
        _emit(run, "run_cancelled", label="Run cancelled", level="warn",
              detail="Stopped by the reviewer before fusion.")
        return

    # ---- Part 2: B (fuse, decide) ----------------------------------------------------
    t0 = time.perf_counter()
    _emit(run, "stage_started", stage="fuse", label="Fuse dimensions — running",
          detail=STAGE_PLAN[3][2], level="info")
    # `run_sample` performs both passes; the `_ReuseBackend` hands it the A result this
    # run already produced, so the live pipeline is executed exactly once — one Ollama
    # extraction call, one set of detector scores, no second opinion to disagree with.
    sample_run = rp.run_sample(sample, _ReuseBackend(produced))
    if sample_run.error:
        _emit(run, "stage_failed", stage="fuse", label="fuse failed",
              detail=f"the core did not assess: {sample_run.error}", level="error",
              payload={"retryable": True})
        _emit(run, "run_failed", label="Run failed",
              detail="No decision was rendered. Abstention is a result, not a gap.",
              level="error", payload={"failed_at": "fuse", "retryable": True})
        return
    assessment = sample_run.final
    coverage = assessment.get("coverage")
    _emit(run, "stage_completed", stage="fuse", label=STAGE_PLAN[3][1],
          detail=(f"risk {assessment.get('risk_score')}/100"
                  + (f" at coverage {coverage:.2f}" if isinstance(coverage, (int, float)) else "")),
          level="success", latencyMs=round((time.perf_counter() - t0) * 1000, 1),
          payload={"risk_score": assessment.get("risk_score"),
                   "coverage": coverage})

    if run["cancelled"]:
        _emit(run, "run_cancelled", label="Run cancelled", level="warn",
              detail="Stopped by the reviewer before policy.")
        return

    # ---- decide ---------------------------------------------------------------------
    t0 = time.perf_counter()
    _emit(run, "stage_started", stage="decide", label="Apply policy — running",
          detail=STAGE_PLAN[4][2], level="info")
    decision = str(assessment.get("decision") or "?")
    override = assessment.get("override_applied")
    _emit(run, "stage_completed", stage="decide", label=STAGE_PLAN[4][1],
          detail=(f"{decision}" + (f" · {override}" if override else "")
                  + f" at risk {assessment.get('risk_score')}/100"),
          level="success", latencyMs=round((time.perf_counter() - t0) * 1000, 1),
          payload={"decision": decision, "override_applied": override,
                   "passes": sample_run.passes})

    if run["cancelled"]:
        _emit(run, "run_cancelled", label="Run cancelled", level="warn",
              detail="Stopped by the reviewer before the chain write.")
        return

    # ---- Part 3: record ---------------------------------------------------------------
    t0 = time.perf_counter()
    _emit(run, "stage_started", stage="record", label="Record to chain — running",
          detail=STAGE_PLAN[5][2], level="info")
    events = rp._audit_events(sample_run)
    # Prefer the live audit service: the chain the console verifies is the chain this run
    # wrote to. The fallback keeps a run usable when C is down, clearly labelled.
    appended = _append_to_audit_service(events, run)
    _emit(run, "stage_completed", stage="record", label=STAGE_PLAN[5][1],
          detail=(f"{len(events)} events appended to the audit chain"
                  if appended else
                  f"{len(events)} events produced; the audit service on :8003 was not "
                  f"reachable, so this run's chain writes are not verifiable"),
          level="success" if appended else "warn",
          latencyMs=round((time.perf_counter() - t0) * 1000, 1),
          payload={"event_count": len(events), "appended_to_service": appended,
                   "event_types": [e[0] for e in events]})

    wall_ms = round((time.perf_counter() - started) * 1000, 1)
    _emit(run, "run_completed", label="Decision rendered",
          detail=(f"{decision} · risk {assessment.get('risk_score')} · "
                  f"policy {assessment.get('policy_version')}"),
          level="success", payload={
              "decision": decision,
              "risk_score": assessment.get("risk_score"),
              "assessment_id": assessment.get("assessment_id"),
              "passes": sample_run.passes,
              "wall_ms": wall_ms,
          })
    run["assessment"] = assessment
    run["intent"] = sample_run.intent


def _append_to_audit_service(events: list[tuple[str, str, dict]], run: dict[str, Any]) -> bool:
    """POST the run's audit events to C on :8003. Best effort, clearly reported."""
    import os
    import urllib.request

    base = (os.environ.get("INTENTLOCK_C_URL") or os.environ.get("INTENTLOCK_AUDIT_URL")
            or "http://127.0.0.1:8003").rstrip("/")
    ok = True
    txn = run.get("transaction_id") or run["run_id"]
    for event_type, actor, payload in events:
        body = json.dumps({
            "event_type": event_type, "actor": actor, "payload": payload,
            "transaction_id": str(payload.get("transaction_id") or txn),
        }).encode("utf-8")
        req = urllib.request.Request(f"{base}/v1/audit/append", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if not (200 <= resp.status < 300):
                    ok = False
        except Exception:
            ok = False
    return ok


def start_run(scenario_id: str, sample: dict, envelope: dict | None = None) -> dict[str, Any]:
    """Register a run and launch the worker thread. Returns the run record."""
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    run = {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "scenario_title": str((sample.get("label") or scenario_id)),
        "status": "RUNNING",
        "events": [],
        "assessment": None,
        "intent": None,
        "cancelled": False,
        "transaction_id": None,
        "envelope": envelope,
        "attempt": 1,
        "started_at": _now_iso(),
        "ended_at": None,
    }
    with _LOCK:
        _RUNS[run_id] = run
    thread = threading.Thread(target=_execute_wrapper, args=(run, sample), daemon=True)
    thread.start()
    run["thread"] = thread
    return run


def _execute_wrapper(run: dict[str, Any], sample: dict) -> None:
    try:
        _execute(run, sample)
    except Exception as exc:  # the last resort: a failed run, never a hung one
        _emit(run, "run_failed", label="Run failed",
              detail=f"{type(exc).__name__}: {exc}", level="error")
    finally:
        run["status"] = "CANCELLED" if run["cancelled"] else (
            "FAILED" if any(e["type"] == "run_failed" for e in run["events"])
            else "COMPLETED")
        run["ended_at"] = _now_iso()


def get_run(run_id: str) -> dict[str, Any] | None:
    with _LOCK:
        return _RUNS.get(run_id)


def cancel_run(run_id: str) -> bool:
    """Mark cancelled. The worker checks between stages and emits `run_cancelled` itself."""
    with _LOCK:
        run = _RUNS.get(run_id)
    if run is None or run["status"] != "RUNNING":
        return False
    run["cancelled"] = True
    return True


def sse_response(run_id: str) -> StreamingResponse:
    """SSE over the run's event list, from the current head, closing on the terminal event."""
    run = get_run(run_id)
    if run is None:
        return StreamingResponse(iter(["event: error\ndata: {\"detail\": \"no such run\"}\n\n"]),
                                 media_type="text/event-stream", status_code=404)

    def stream():
        sent = 0
        while True:
            events = run["events"]
            while sent < len(events):
                ev = events[sent]
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev["type"] in ("run_completed", "run_failed", "run_cancelled"):
                    return
                sent += 1
            if run["status"] != "RUNNING":
                return
            time.sleep(0.05)

    return StreamingResponse(stream(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
