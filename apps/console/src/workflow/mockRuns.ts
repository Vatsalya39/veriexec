/**
 * `workflow/mockRuns.ts` — the in-memory run store behind mock mode.
 *
 * It is deliberately shaped like a server: runs are created, buffered, subscribed to,
 * cancelled and retried by id, and a subscriber that arrives late is replayed every event
 * the run has already emitted — the same guarantee `Last-Event-ID` gives on a real SSE
 * reconnect. React 19 mounts effects twice in StrictMode, so "subscribe cannot drop a
 * frame" is a correctness requirement, not a nicety.
 *
 * Nothing outside `verificationService.ts` imports this file.
 */

import type { ScenarioEnvelope } from "../api/types";
import { startEngine, type EngineHandle } from "./mockEngine";
import type { EndReason, FaultPoint, WorkflowEvent } from "./contract";

export interface RunState {
  runId: string;
  scenarioId: string;
  envelope: ScenarioEnvelope;
  source: "fixture" | "live";
  attempt: number;
  events: WorkflowEvent[];
  status: "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  /** Logs already earned by earlier attempts, so a retry does not erase history. */
  handle: EngineHandle | null;
}

type Subscriber = { onEvent: (ev: WorkflowEvent) => void; onEnd?: (reason: EndReason) => void };

const runs = new Map<string, RunState>();
const subscribers = new Map<string, Set<Subscriber>>();

let settings: { speed: number; fault: FaultPoint } = { speed: 1, fault: "none" };

export function setEngineSettings(next: Partial<{ speed: number; fault: FaultPoint }>): void {
  settings = { ...settings, ...next };
}

export function engineSettings(): { speed: number; fault: FaultPoint } {
  return settings;
}

let counter = 0;

function newRunId(scenarioId: string): string {
  counter += 1;
  return `run-${scenarioId.toLowerCase()}-${Date.now().toString(36)}-${counter}`;
}

function fanout(runId: string, ev: WorkflowEvent): void {
  const state = runs.get(runId);
  state?.events.push(ev);
  subscribers.get(runId)?.forEach((s) => s.onEvent(ev));
}

function end(runId: string, reason: EndReason): void {
  const state = runs.get(runId);
  if (state) {
    state.status = reason === "completed" ? "COMPLETED" : reason === "failed" ? "FAILED" : "CANCELLED";
    state.handle = null;
  }
  subscribers.get(runId)?.forEach((s) => s.onEnd?.(reason));
}

/** Create a run and start its replay. Returns the id before the first event lands. */
export function createRun(
  envelope: ScenarioEnvelope,
  source: "fixture" | "live",
): { runId: string; attempt: number } {
  const runId = newRunId(envelope.scenario.id);
  const state: RunState = {
    runId,
    scenarioId: envelope.scenario.id,
    envelope,
    source,
    attempt: 1,
    events: [],
    status: "RUNNING",
    handle: null,
  };
  runs.set(runId, state);
  state.handle = startEngine({
    runId,
    envelope,
    speed: settings.speed,
    fault: settings.fault,
    onEvent: (ev) => fanout(runId, ev),
    onEnd: (reason) => end(runId, reason),
  });
  return { runId, attempt: 1 };
}

export function getRunState(runId: string): RunState | null {
  return runs.get(runId) ?? null;
}

/**
 * Subscribe to a run. Buffered events are replayed synchronously, then live ones stream.
 * The returned unsubscribe is safe to call more than once.
 */
export function subscribeRun(
  runId: string,
  onEvent: (ev: WorkflowEvent) => void,
  onEnd?: (reason: EndReason) => void,
): () => void {
  const sub: Subscriber = { onEvent, onEnd };
  const set = subscribers.get(runId) ?? new Set<Subscriber>();
  set.add(sub);
  subscribers.set(runId, set);

  const state = runs.get(runId);
  if (state) {
    for (const ev of state.events) onEvent(ev);
    if (state.status !== "RUNNING") {
      onEnd?.(state.status === "COMPLETED" ? "completed" : state.status === "FAILED" ? "failed" : "cancelled");
    }
  }

  let disposed = false;
  return () => {
    if (disposed) return;
    disposed = true;
    subscribers.get(runId)?.delete(sub);
  };
}

export function cancelRun(runId: string): boolean {
  const state = runs.get(runId);
  if (!state || state.status !== "RUNNING") return false;
  state.handle?.cancel();
  return true;
}

/**
 * Retry a failed run: a *new* run id over the same envelope, carrying the attempt counter
 * forward. The old run's state is kept so the console can still show what it said — a
 * retry that erases the failure it recovered from is a worse audit trail than no retry.
 */
export function retryRun(runId: string): { runId: string; attempt: number } | null {
  const prior = runs.get(runId);
  if (!prior) return null;
  const nextId = newRunId(prior.scenarioId);
  const attempt = prior.attempt + 1;
  const state: RunState = {
    runId: nextId,
    scenarioId: prior.scenarioId,
    envelope: prior.envelope,
    source: prior.source,
    attempt,
    events: [],
    status: "RUNNING",
    handle: null,
  };
  runs.set(nextId, state);
  // A retry clears the injected fault: the point of retrying is that the transient
  // condition is gone. Leaving it armed would make the button a lie.
  state.handle = startEngine({
    runId: nextId,
    envelope: prior.envelope,
    speed: settings.speed,
    fault: "none",
    onEvent: (ev) => fanout(nextId, ev),
    onEnd: (reason) => end(nextId, reason),
  });
  return { runId: nextId, attempt };
}

/** Drop every run. Used by tests and the console's reset control. */
export function resetRuns(): void {
  for (const state of runs.values()) state.handle?.cancel();
  runs.clear();
  subscribers.clear();
}
