/**
 * `workflow/deriveSnapshot.ts` — the one pure function that turns an event stream into
 * the pipeline snapshot.
 *
 * Pure on purpose: the same `WorkflowEvent[]` produces the same snapshot whether the
 * events came from the mock engine, a live EventSource, or a REST poll. Nothing here
 * knows which. Every visual component reads only the snapshot, so swapping the transport
 * cannot change what is drawn — and this file has no React import, so it is testable
 * without a DOM.
 */

import type { ScenarioEnvelope } from "../api/types";
import {
  PIPELINE, idleSnapshot, ownerOf, stepIndex,
  type RunStatus, type StepStatus, type WorkflowEvent, type WorkflowLog,
  type WorkflowOutput, type WorkflowSnapshot, type WorkflowStep, type WorkflowTask,
} from "./contract";

export interface DeriveOptions {
  runId?: string | null;
  scenarioId?: string | null;
  /** 1-based attempt counter; > 1 after a retry. */
  attempt?: number;
  /** Set by the caller when the transport, not the run, ended the stream. */
  cancelled?: boolean;
  /** Transport-level error, e.g. a dropped connection. */
  error?: string | null;
  /** Log lines carried over from earlier attempts, oldest first. */
  priorLogs?: readonly WorkflowLog[];
  /** The envelope the run resolved, needed to build `output`. */
  envelope?: ScenarioEnvelope | null;
  source?: "fixture" | "live" | null;
}

interface Acc {
  count: number;
  first: string | null;
  last: string | null;
  detail: string | null;
  /** Sum of the stage's own reported latency — measured, not inferred from clocks. */
  latencyMs: number | null;
  done: boolean;
}

const emptyAcc = (): Acc => ({ count: 0, first: null, last: null, detail: null, latencyMs: null, done: false });

function ms(from: string | null, to: string | null): number | null {
  if (!from || !to) return null;
  const a = Date.parse(from);
  const b = Date.parse(to);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return Math.max(0, b - a);
}

/** Fold an event stream into the three-part pipeline snapshot. */
export function deriveSnapshot(
  events: readonly WorkflowEvent[],
  opts: DeriveOptions = {},
): WorkflowSnapshot {
  if (events.length === 0 && !(opts.priorLogs?.length)) {
    const base = idleSnapshot();
    return {
      ...base,
      runId: opts.runId ?? null,
      scenarioId: opts.scenarioId ?? null,
      attempt: opts.attempt ?? 1,
      error: opts.error ?? null,
      source: opts.source ?? null,
      status: opts.cancelled ? "CANCELLED" : opts.error ? "FAILED" : "IDLE",
    };
  }

  const attempt = opts.attempt ?? 1;
  const taskAcc = new Map<string, Acc>();
  const stepAcc = new Map<string, Acc>();
  const logs: WorkflowLog[] = [...(opts.priorLogs ?? [])];

  let pointer = 0;
  let currentTask: string | null = null;
  let failedStep: string | null = null;
  let failedTask: string | null = null;
  let failure: string | null = null;
  let completed = false;
  let cancelledByRun = false;
  const stageLatency: Record<string, number> = {};

  for (const ev of events) {
    const owner = ownerOf(ev);
    // Run-level events (`run_started`, `run_failed`) have no blueprint owner but still
    // belong in the console. They are attributed to whatever part is in flight rather
    // than dropped, so nothing the engine says can vanish from the log.
    const stepId = owner?.step ?? PIPELINE[Math.max(0, pointer - 1)]?.id ?? PIPELINE[0].id;
    const taskId = owner?.task ?? currentTask ?? PIPELINE[0].tasks[0].id;
    const key = `${stepId}:${taskId}`;

    const tAcc = taskAcc.get(key) ?? emptyAcc();
    tAcc.count += 1;
    tAcc.first = tAcc.first ?? ev.ts;
    tAcc.last = ev.ts;
    if (ev.detail) tAcc.detail = ev.detail;
    if (typeof ev.latencyMs === "number") tAcc.latencyMs = (tAcc.latencyMs ?? 0) + ev.latencyMs;
    if (ev.type === "stage_completed") tAcc.done = true;
    taskAcc.set(key, tAcc);

    const sAcc = stepAcc.get(stepId) ?? emptyAcc();
    sAcc.count += 1;
    sAcc.first = sAcc.first ?? ev.ts;
    sAcc.last = ev.ts;
    if (typeof ev.latencyMs === "number") sAcc.latencyMs = (sAcc.latencyMs ?? 0) + ev.latencyMs;
    stepAcc.set(stepId, sAcc);

    if (owner) {
      const idx = stepIndex(owner.step);
      // Monotonic: a late event must never drag the pipeline back to an earlier part.
      if (idx >= pointer) { pointer = idx; currentTask = owner.task; }
    }

    logs.push({
      id: `${opts.runId ?? "run"}:${attempt}:${ev.seq}`,
      seq: ev.seq,
      ts: ev.ts,
      step: stepId,
      task: taskId,
      label: ev.label ?? ev.type,
      level: ev.level ?? defaultLevel(ev.type),
      message: ev.detail || ev.label || ev.type,
      attempt,
      payload: ev.payload,
    });

    switch (ev.type) {
      case "stage_completed":
        if (ev.stage && typeof ev.latencyMs === "number") stageLatency[ev.stage] = ev.latencyMs;
        break;
      case "stage_failed":
      case "run_failed":
        failedStep = stepId;
        failedTask = taskId;
        failure = ev.detail || ev.label || "The run failed.";
        break;
      case "run_completed":
        completed = true;
        break;
      case "run_cancelled":
        cancelledByRun = true;
        break;
      default:
        break;
    }
  }

  const cancelled = cancelledByRun || Boolean(opts.cancelled);
  const status: RunStatus = failure
    ? "FAILED"
    : completed
      ? "COMPLETED"
      : cancelled
        ? "CANCELLED"
        : events.length > 0
          ? "RUNNING"
          : "IDLE";

  const live = status === "RUNNING";
  const steps: WorkflowStep[] = PIPELINE.map((part) => {
    const idx = stepIndex(part.id);
    const sAcc = stepAcc.get(part.id) ?? emptyAcc();
    const visited = sAcc.count > 0;
    const isFailed = failedStep === part.id;

    let stepStatus: StepStatus;
    if (isFailed) stepStatus = "FAILED";
    else if (live && idx === pointer) stepStatus = "RUNNING";
    else if (completed && visited) stepStatus = "COMPLETED";
    else if (idx < pointer && visited) stepStatus = "COMPLETED";
    else stepStatus = "PENDING";

    const tasks: WorkflowTask[] = part.tasks.map((blueprint) => {
      const acc = taskAcc.get(`${part.id}:${blueprint.id}`) ?? emptyAcc();
      const seen = acc.count > 0;
      const isCurrent = idx === pointer && blueprint.id === currentTask;
      // A cancelled run leaves its in-flight task unfinished. It reads PENDING again so
      // the UI never claims a task completed when it was stopped mid-flight.
      const interrupted = status === "CANCELLED" && isCurrent && !acc.done;

      let taskStatus: StepStatus;
      if (isFailed && blueprint.id === failedTask) taskStatus = "FAILED";
      else if (live && isCurrent && !acc.done) taskStatus = "RUNNING";
      else if (interrupted) taskStatus = "PENDING";
      else if (acc.done) taskStatus = "COMPLETED";
      else if (seen) taskStatus = live ? "RUNNING" : "COMPLETED";
      else taskStatus = "PENDING";

      return {
        id: blueprint.id,
        title: blueprint.title,
        hint: blueprint.hint,
        status: taskStatus,
        visited: seen,
        eventCount: acc.count,
        durationMs: acc.latencyMs ?? ms(acc.first, acc.last),
        detail: acc.detail,
      };
    });

    const done = tasks.filter((t) => t.status === "COMPLETED").length;
    const running = tasks.filter((t) => t.status === "RUNNING").length;
    const progress = stepStatus === "COMPLETED"
      ? 1
      : tasks.length === 0
        ? 0
        : Math.min(1, (done + running * 0.5) / tasks.length);

    return {
      id: part.id,
      title: part.title,
      name: part.name,
      summary: part.summary,
      status: stepStatus,
      index: idx,
      tasks,
      logs: logs.filter((l) => l.step === part.id),
      progress,
      eventCount: sAcc.count,
      startedAt: sAcc.first,
      endedAt: stepStatus === "COMPLETED" || stepStatus === "FAILED" ? sAcc.last : null,
      durationMs: sAcc.latencyMs ?? ms(sAcc.first, sAcc.last),
      error: isFailed ? failure : null,
    };
  });

  const first = events.length > 0 ? events[0].ts : null;
  const last = events.length > 0 ? events[events.length - 1].ts : null;

  return {
    currentStep: pointer,
    status,
    steps,
    output: completed && opts.envelope
      ? buildOutput(opts.envelope, {
        runId: opts.runId ?? null,
        stageLatency,
        wallMs: sum(Object.values(stageLatency)) || (ms(first, last) ?? 0),
        finishedAt: last,
        source: opts.source ?? "fixture",
      })
      : null,
    runId: opts.runId ?? null,
    scenarioId: opts.scenarioId ?? opts.envelope?.scenario.id ?? null,
    attempt,
    error: failure ?? opts.error ?? (status === "CANCELLED" ? "Run stopped by the reviewer." : null),
    startedAt: first,
    endedAt: status === "COMPLETED" || status === "FAILED" ? last : null,
    eventCount: events.length,
    logs,
    source: opts.source ?? null,
  };
}

function sum(xs: number[]): number {
  return xs.reduce((a, b) => a + b, 0);
}

function defaultLevel(type: WorkflowEvent["type"]): WorkflowLog["level"] {
  switch (type) {
    case "stage_failed":
    case "run_failed": return "error";
    case "run_cancelled": return "warn";
    case "run_completed":
    case "stage_completed": return "success";
    default: return "info";
  }
}

interface OutputContext {
  runId: string | null;
  stageLatency: Record<string, number>;
  wallMs: number;
  finishedAt: string | null;
  source: "fixture" | "live";
}

/**
 * The output is built only once `run_completed` has landed *and* an envelope is present,
 * so a run that decided but never reported (a dropped connection) yields `null` rather
 * than a half-populated card claiming to be final.
 */
function buildOutput(envelope: ScenarioEnvelope, ctx: OutputContext): WorkflowOutput {
  const a = envelope.assessment;
  return {
    runId: ctx.runId ?? a.assessment_id,
    scenarioId: envelope.scenario.id,
    title: envelope.scenario.title,
    decision: a.decision,
    visibleToRequester: a.visible_to_requester ?? null,
    riskScore: a.risk_score,
    intentConfidence: a.intent_confidence?.value ?? 0,
    fingerprintVerdict: envelope.signals.fingerprint?.verdict ?? null,
    policyVersion: a.policy_version,
    assessmentId: a.assessment_id,
    topReasons: a.top_reasons ?? [],
    requiredActions: a.required_actions ?? [],
    stageLatencyMs: ctx.stageLatency,
    wallMs: ctx.wallMs,
    finishedAt: ctx.finishedAt,
    source: ctx.source,
    envelope,
  };
}
