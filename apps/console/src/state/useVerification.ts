/**
 * `state/useVerification.ts` — the single hook the pipeline screen talks to.
 *
 * It owns every piece of execution state — which scenario, which run, which attempt, the
 * simulation knobs, the clock — and hands components a finished `WorkflowSnapshot`.
 *
 * No component below this hook starts, times, advances or fails a run. Swapping the
 * backend means editing `workflow/verificationService.ts` — not this file, and not
 * anything it renders into.
 */

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { deriveSnapshot } from "../workflow/deriveSnapshot";
import type { WorkflowEvent, WorkflowLog, WorkflowSnapshot } from "../workflow/contract";
import type { ScenarioEnvelope } from "../api/types";
import {
  cancelWorkflow, retryWorkflow, setSimulation, startWorkflow, subscribeWorkflow,
  type EndReason, type FaultPoint,
} from "../workflow/verificationService";

/** Replay speeds offered by the simulation control. */
export const SPEED_OPTIONS = [
  { value: "0.5", label: "0.5×", speed: 0.5 },
  { value: "1", label: "1×", speed: 1 },
  { value: "2", label: "2×", speed: 2 },
  { value: "instant", label: "Instant", speed: Number.POSITIVE_INFINITY },
] as const;

/** Fault injection points, for exercising the failed state and retry on demand. */
export const FAULT_OPTIONS: Array<{ value: FaultPoint; label: string }> = [
  { value: "none", label: "No fault" },
  { value: "detect", label: "Fail in Part 2" },
  { value: "record", label: "Fail in Part 3" },
];

const MAX_CARRIED_LOGS = 200;

// ------------------------------------------------------------------ event fold

interface StreamState { events: WorkflowEvent[] }
type StreamAction = { kind: "reset" } | { kind: "event"; ev: WorkflowEvent };

function streamReducer(state: StreamState, action: StreamAction): StreamState {
  switch (action.kind) {
    case "reset": return { events: [] };
    case "event": {
      // The mock store replays its buffer on subscribe and StrictMode subscribes twice, so
      // the fold must be idempotent on `seq` rather than trusting arrival order.
      if (state.events.some((e) => e.seq === action.ev.seq)) return state;
      return { events: [...state.events, action.ev] };
    }
  }
}

// ------------------------------------------------------------------------ hook

export interface UseVerificationResult {
  snapshot: WorkflowSnapshot;
  scenarioId: string | null;
  runId: string | null;
  attempt: number;
  speed: string;
  fault: FaultPoint;
  /** The envelope this run resolved, once it has one. */
  envelope: ScenarioEnvelope | null;
  source: "fixture" | "live" | null;
  /** Wall time of the current (or last) run, in ms. */
  elapsedMs: number;
  /** A start/retry request is in flight. */
  busy: boolean;
  canRun: boolean;
  canCancel: boolean;
  canRetry: boolean;
  endReason: EndReason | null;
  error: string | null;
  selectScenario(scenarioId: string): void;
  setSpeed(value: string): void;
  setFault(fault: FaultPoint): void;
  run(): void;
  cancel(): void;
  retry(): void;
  reset(): void;
}

function speedValue(value: string): number {
  return SPEED_OPTIONS.find((o) => o.value === value)?.speed ?? 1;
}

function retryDivider(attempt: number, previousRunId: string | null): WorkflowLog {
  return {
    id: `retry:${attempt}:${previousRunId ?? "none"}`,
    seq: -1,
    ts: new Date().toISOString(),
    step: "part1",
    task: "ingest",
    label: "Retry",
    level: "warn",
    message: `Attempt ${attempt} — the transient condition cleared; the run restarts from ingest so nothing is inherited from the failure.`,
    attempt,
  };
}

export function useVerification(initialScenarioId: string | null = null): UseVerificationResult {
  const [scenarioId, setScenarioId] = useState<string | null>(initialScenarioId);
  const [runId, setRunId] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(1);
  const [speed, setSpeedState] = useState<string>("1");
  const [fault, setFaultState] = useState<FaultPoint>("none");
  const [busy, setBusy] = useState(false);
  const [cancelled, setCancelled] = useState(false);
  const [endReason, setEndReason] = useState<EndReason | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [envelope, setEnvelope] = useState<ScenarioEnvelope | null>(null);
  const [source, setSource] = useState<"fixture" | "live" | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const [stream, dispatch] = useReducer(streamReducer, { events: [] });

  /** Console lines from earlier attempts, so a retry does not erase the history. */
  const carried = useRef<WorkflowLog[]>([]);
  /** Guards the double-click: one run per request, even before state settles. */
  const starting = useRef(false);

  // Subscribe to whatever transport the service hands us. This effect is the only place
  // the console touches a stream, and it never learns whether it is SSE or the engine.
  useEffect(() => {
    dispatch({ kind: "reset" });
    if (!runId) return;
    const dispose = subscribeWorkflow(
      runId,
      (ev) => dispatch({ kind: "event", ev }),
      (reason) => setEndReason(reason),
    );
    return dispose;
  }, [runId]);

  const snapshot = useMemo(
    () => deriveSnapshot(stream.events, {
      runId, scenarioId, attempt, cancelled, error,
      priorLogs: carried.current, envelope, source,
    }),
    // `carried.current` only ever changes together with `attempt`.
    [stream.events, runId, scenarioId, attempt, cancelled, error, envelope, source],
  );

  // One interval while a run is live; the clock is derived, never stored.
  useEffect(() => {
    if (snapshot.status !== "RUNNING") return;
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [snapshot.status]);

  const elapsedMs = useMemo(() => {
    if (!snapshot.startedAt) return 0;
    const from = Date.parse(snapshot.startedAt);
    if (Number.isNaN(from)) return 0;
    const to = snapshot.endedAt ? Date.parse(snapshot.endedAt) : now;
    return Math.max(0, to - from);
  }, [snapshot.startedAt, snapshot.endedAt, now]);

  const selectScenario = useCallback((next: string) => {
    setScenarioId(next);
    setRunId(null);
    setAttempt(1);
    setCancelled(false);
    setEndReason(null);
    setError(null);
    setEnvelope(null);
    setSource(null);
    carried.current = [];
  }, []);

  const run = useCallback(() => {
    if (!scenarioId || starting.current) return;
    starting.current = true;
    setBusy(true);
    setError(null);
    setCancelled(false);
    setEndReason(null);
    setAttempt(1);
    carried.current = [];
    void (async () => {
      try {
        await setSimulation({ speed: speedValue(speed), fault });
        const started = await startWorkflow(scenarioId);
        setEnvelope(started.envelope);
        setSource(started.source);
        setRunId(started.runId);
      } catch (e) {
        setError(errorText(e, "could not start the run"));
      } finally {
        starting.current = false;
        setBusy(false);
      }
    })();
  }, [fault, scenarioId, speed]);

  const cancel = useCallback(() => {
    if (!runId) return;
    setCancelled(true);
    void cancelWorkflow(runId);
  }, [runId]);

  const retry = useCallback(() => {
    if (!runId || !scenarioId || starting.current) return;
    starting.current = true;
    setBusy(true);
    setError(null);
    setCancelled(false);
    setEndReason(null);
    const next = attempt + 1;
    carried.current = [...snapshot.logs.slice(-MAX_CARRIED_LOGS), retryDivider(next, runId)];
    void (async () => {
      try {
        // A retry always disarms the fault — the point of retrying is that the transient
        // condition is gone, so re-arming it would make the button a lie.
        await setSimulation({ speed: speedValue(speed), fault: "none" });
        const started = await retryWorkflow({ runId, scenarioId });
        setEnvelope(started.envelope);
        setSource(started.source);
        setAttempt(started.attempt ?? next);
        setRunId(started.runId);
      } catch (e) {
        setError(errorText(e, "could not retry the run"));
      } finally {
        starting.current = false;
        setBusy(false);
      }
    })();
  }, [attempt, runId, scenarioId, snapshot.logs, speed]);

  const reset = useCallback(() => {
    setRunId(null);
    setAttempt(1);
    setCancelled(false);
    setEndReason(null);
    setError(null);
    setEnvelope(null);
    setSource(null);
    carried.current = [];
  }, []);

  const setSpeed = useCallback((value: string) => {
    setSpeedState(value);
    void setSimulation({ speed: speedValue(value) });
  }, []);

  const setFault = useCallback((next: FaultPoint) => {
    setFaultState(next);
    void setSimulation({ fault: next });
  }, []);

  const live = snapshot.status === "RUNNING";

  return {
    snapshot,
    scenarioId,
    runId,
    attempt,
    speed,
    fault,
    envelope,
    source,
    elapsedMs,
    busy,
    canRun: Boolean(scenarioId) && !live && !busy,
    canCancel: live,
    canRetry: snapshot.status === "FAILED" || snapshot.status === "CANCELLED",
    endReason,
    error: snapshot.error,
    selectScenario,
    setSpeed,
    setFault,
    run,
    cancel,
    retry,
    reset,
  };
}

/** The api client throws `{ code, detail }`, not `Error`. Both must read well. */
function errorText(e: unknown, fallback: string): string {
  if (e instanceof Error) return e.message;
  const api = e as { detail?: string; code?: string } | null;
  if (api?.detail) return api.detail;
  return fallback;
}
