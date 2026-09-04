/**
 * ─────────────────────────────────────────────────────────────────────────────
 *  THE SWAP POINT
 *
 *  Every execution concern in the console enters through this module: starting a
 *  verification run, receiving its events, polling its state, cancelling and retrying.
 *  No component calls anything below it. Each function has exactly two branches — mock
 *  and live — and the live branch is already written against the intended core contract.
 *
 *  To go live: set `VITE_INTENTLOCK_MOCK=0`. To delete the simulator entirely: drop the
 *  `isMockMode()` branch from the six functions below, then delete `mockEngine.ts` and
 *  `mockRuns.ts`. Nothing visual changes — no component imports either file.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import * as api from "../api/client";
import type { ScenarioSummary } from "../api/client";
import { CORE_URL } from "../api/client";
import type { ScenarioEnvelope } from "../api/types";
import { deriveSnapshot } from "./deriveSnapshot";
import type { EndReason, FaultPoint, WorkflowEvent, WorkflowSnapshot } from "./contract";
import { isMockMode } from "./mode";

export type { EndReason, FaultPoint };

export interface StartedRun {
  runId: string;
  attempt: number;
  envelope: ScenarioEnvelope;
  source: "fixture" | "live";
}

/** The scenario list. Static fixture index in both modes — it is the demo's menu. */
export function listScenarios(): Promise<ScenarioSummary[]> {
  return api.listScenarios();
}

/**
 * Begin a run over one scenario.
 *
 * Both modes resolve the envelope through `api.loadScenario`, which already tries the live
 * signal service first and falls back to the golden fixture with a visible badge. Mock
 * mode then hands the envelope to the replay engine; live mode asks the core to execute it.
 */
export async function startWorkflow(scenarioId: string): Promise<StartedRun> {
  const { data, source } = await api.loadScenario(scenarioId);
  if (isMockMode()) {
    const { createRun } = await import("./mockRuns");
    const { runId, attempt } = createRun(data, source);
    return { runId, attempt, envelope: data, source };
  }
  const res = await fetch(`${CORE_URL}/v1/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario_id: scenarioId }),
  });
  if (!res.ok) throw { code: "HTTP_", detail: `POST /v1/runs failed (HTTP ${res.status})` };
  const body = (await res.json()) as { run_id: string; attempt?: number };
  return { runId: body.run_id, attempt: body.attempt ?? 1, envelope: data, source };
}

/** Live transport: SSE. One handler, because the engine emits one event shape. */
function subscribeLive(
  runId: string,
  onEvent: (ev: WorkflowEvent) => void,
  onEnd?: (reason: EndReason) => void,
): () => void {
  const source = new EventSource(`${CORE_URL}/v1/runs/${encodeURIComponent(runId)}/events`);
  let closed = false;

  const close = (reason: EndReason) => {
    if (closed) return;
    closed = true;
    source.close();
    onEnd?.(reason);
  };

  source.onmessage = (raw: MessageEvent) => {
    let ev: WorkflowEvent;
    try { ev = JSON.parse(raw.data as string) as WorkflowEvent; } catch { return; }
    onEvent(ev);
    if (ev.type === "run_completed") close("completed");
    else if (ev.type === "run_failed") close("failed");
    else if (ev.type === "run_cancelled") close("cancelled");
  };
  // Transport hiccups are the browser's to retry; only a terminal event closes.

  return () => {
    if (closed) return;
    closed = true;
    source.close();
  };
}

/**
 * Subscribe to a run's event stream. The returned function unsubscribes and is safe to
 * call more than once (React StrictMode mounts effects twice).
 */
export function subscribeWorkflow(
  runId: string,
  onEvent: (ev: WorkflowEvent) => void,
  onEnd?: (reason: EndReason) => void,
): () => void {
  if (!isMockMode()) return subscribeLive(runId, onEvent, onEnd);

  let stopped = false;
  let dispose: (() => void) | null = null;
  void import("./mockRuns").then(({ subscribeRun }) => {
    if (stopped) return;
    dispose = subscribeRun(runId, onEvent, onEnd);
  });

  return () => {
    stopped = true;
    dispose?.();
    dispose = null;
  };
}

/**
 * REST polling emulation: the whole snapshot in one request, for clients that cannot hold
 * a stream open. Live mode reads `GET /v1/runs/:id`, whose `events` array is the same one
 * the stream delivers.
 */
export async function pollWorkflow(runId: string): Promise<WorkflowSnapshot> {
  if (isMockMode()) {
    const { getRunState } = await import("./mockRuns");
    const state = getRunState(runId);
    if (!state) return deriveSnapshot([], { runId });
    return deriveSnapshot(state.events, {
      runId,
      scenarioId: state.scenarioId,
      attempt: state.attempt,
      cancelled: state.status === "CANCELLED",
      envelope: state.envelope,
      source: state.source,
    });
  }
  const res = await fetch(`${CORE_URL}/v1/runs/${encodeURIComponent(runId)}`);
  if (!res.ok) throw { code: "HTTP_", detail: `GET /v1/runs/${runId} failed (HTTP ${res.status})` };
  const body = (await res.json()) as {
    events?: WorkflowEvent[]; scenario_id?: string; attempt?: number; envelope?: ScenarioEnvelope;
  };
  return deriveSnapshot(body.events ?? [], {
    runId,
    scenarioId: body.scenario_id ?? null,
    attempt: body.attempt ?? 1,
    envelope: body.envelope ?? null,
    source: "live",
  });
}

/** Stop a run in flight. */
export async function cancelWorkflow(runId: string): Promise<boolean> {
  if (isMockMode()) {
    const { cancelRun } = await import("./mockRuns");
    return cancelRun(runId);
  }
  const res = await fetch(`${CORE_URL}/v1/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
  return res.ok;
}

/**
 * Retry a failed run. Mock mode replays the same envelope with the fault cleared; live
 * mode starts a fresh run, which is what a stateless core supports.
 */
export async function retryWorkflow(prior: { runId: string; scenarioId: string }): Promise<StartedRun> {
  if (isMockMode()) {
    const { retryRun, getRunState } = await import("./mockRuns");
    const next = retryRun(prior.runId);
    const state = next ? getRunState(next.runId) : null;
    if (!next || !state) throw { code: "UPSTREAM_UNAVAILABLE", detail: `run ${prior.runId} is not retryable` };
    return { runId: next.runId, attempt: next.attempt, envelope: state.envelope, source: state.source };
  }
  const started = await startWorkflow(prior.scenarioId);
  return { ...started, attempt: 2 };
}

export interface Simulation {
  /** 1 = designed pacing. Larger is faster. */
  speed: number;
  fault: FaultPoint;
}

/**
 * Simulation-only knobs. No-ops against a live core, which sets its own pace and does not
 * take instructions to fail.
 */
export async function setSimulation(next: Partial<Simulation>): Promise<void> {
  if (!isMockMode()) return;
  const { setEngineSettings } = await import("./mockRuns");
  setEngineSettings(next);
}

/** Discard mock run state. No-op in live mode. */
export async function resetWorkflows(): Promise<void> {
  if (!isMockMode()) return;
  const { resetRuns } = await import("./mockRuns");
  resetRuns();
}
