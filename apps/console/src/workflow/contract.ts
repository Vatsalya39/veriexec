/**
 * `workflow/contract.ts` — the execution contract the pipeline screen renders.
 *
 * Deliberately separate from `api/types.ts`: that file describes *what the verification
 * decided*, this one describes *how far the run got*. The snapshot shape is fixed:
 *
 *   {
 *     "currentStep": 2,
 *     "status": "RUNNING",
 *     "steps": [ { "id": "part1", "title": "Part 1", "status": "COMPLETED", "logs": [] }, … ],
 *     "output": null
 *   }
 *
 * Everything past those four keys is additive and optional to consume, so a real backend
 * can serve the minimum above and every component still renders.
 *
 * The three parts are not invented for the UI — they are the product's own decomposition,
 * and the six tasks are the six `timeline` stages every golden fixture already carries
 * (`ingest, extract, detect, fuse, decide, record`). The visualizer therefore replays the
 * engine's real execution story, with the fixture's own `latency_ms` as the pacing.
 */

import type { Decision, ScenarioEnvelope } from "../api/types";

/** The four discrete states every step and task transitions through. */
export type StepStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";

/** Run-level status. Adds the two states a step cannot be in. */
export type RunStatus = "IDLE" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";

export const STEP_STATUSES: readonly StepStatus[] = ["PENDING", "RUNNING", "COMPLETED", "FAILED"] as const;

export type LogLevel = "info" | "success" | "warn" | "error";

/** One console line. `seq < 0` marks a synthetic line (a retry divider, a control note). */
export interface WorkflowLog {
  /** Stable across re-renders, so it is a safe React key. */
  id: string;
  seq: number;
  ts: string;
  /** Owning part, e.g. `part2`. */
  step: string;
  /** Owning task, e.g. `detect`. */
  task: string;
  /** Short label, e.g. `Detectors scored`. */
  label: string;
  level: LogLevel;
  message: string;
  /** Attempt number this line belongs to (1-based); survives a retry. */
  attempt: number;
  /** Raw payload, for the console's expandable rows. */
  payload?: Record<string, unknown>;
}

/** A task is the smallest unit with its own status: one row inside a part card. */
export interface WorkflowTask {
  id: string;
  title: string;
  /** One line on what this task does — shown while it is still idle. */
  hint: string;
  status: StepStatus;
  /** False until at least one event has landed here. */
  visited: boolean;
  eventCount: number;
  /** Measured, not guessed: the stage's own `latency_ms` once it has run. */
  durationMs: number | null;
  /** Narration of the most recent event on this task — the live sub-line. */
  detail: string | null;
}

/** A step is one part of the three-part pipeline. */
export interface WorkflowStep {
  id: string;
  /** `Part 1` — the contract's `title`. */
  title: string;
  /** `Capture` — the part's name in the product. */
  name: string;
  summary: string;
  status: StepStatus;
  /** 1-based position, matching `currentStep`. */
  index: number;
  tasks: WorkflowTask[];
  logs: WorkflowLog[];
  /** 0..1 across *visited* tasks, so a skipped task cannot inflate progress. */
  progress: number;
  eventCount: number;
  startedAt: string | null;
  endedAt: string | null;
  durationMs: number | null;
  /** Present only when this part failed. */
  error: string | null;
}

/** The terminal artefact of a completed run. `null` until then. */
export interface WorkflowOutput {
  runId: string;
  scenarioId: string;
  title: string;
  decision: Decision;
  /** What the requester is allowed to see — not always the same as `decision` (§12). */
  visibleToRequester: string | null;
  riskScore: number;
  intentConfidence: number;
  fingerprintVerdict: string | null;
  policyVersion: string;
  assessmentId: string;
  topReasons: string[];
  requiredActions: string[];
  /** The stage totals, so the report can be read without the timeline screen. */
  stageLatencyMs: Record<string, number>;
  wallMs: number;
  finishedAt: string | null;
  /** `fixture` or `live` — provenance of the run, never hidden. */
  source: "fixture" | "live";
  /** The envelope itself, for the evidence drawer. */
  envelope: ScenarioEnvelope;
}

export interface WorkflowSnapshot {
  /** 1-based index of the running (or last touched) part. 0 before the run starts. */
  currentStep: number;
  status: RunStatus;
  steps: WorkflowStep[];
  output: WorkflowOutput | null;

  // ---- additive; a minimal backend may omit all of these ---------------------
  runId: string | null;
  scenarioId: string | null;
  /** Retry counter, 1-based; > 1 means at least one attempt failed. */
  attempt: number;
  error: string | null;
  startedAt: string | null;
  endedAt: string | null;
  eventCount: number;
  /** Every log line, in order — the flat feed the console renders. */
  logs: WorkflowLog[];
  /** Where this run's data came from. Absent until the run resolves it. */
  source: "fixture" | "live" | null;
}

// --------------------------------------------------------------------- events

/**
 * The event stream the engine emits and `deriveSnapshot` folds. One event type per
 * pipeline stage, plus the four control events every run needs. A real backend can emit
 * exactly these over SSE and nothing in the UI changes.
 */
export type WorkflowEventType =
  | "run_started"
  | "stage_started"
  | "stage_completed"
  | "stage_failed"
  | "run_completed"
  | "run_failed"
  | "run_cancelled";

export interface WorkflowEvent {
  seq: number;
  ts: string;
  type: WorkflowEventType;
  /** The pipeline stage this event concerns; absent on run-level events. */
  stage?: string;
  label?: string;
  detail?: string;
  level?: LogLevel;
  latencyMs?: number;
  payload?: Record<string, unknown>;
}

/** Why a stream closed. The transport reports it; nothing derives state from it. */
export type EndReason = "completed" | "failed" | "cancelled";

/**
 * Where a simulated outage lands, for exercising the failed state and retry on demand.
 * Simulation-only: a live core sets its own pace and does not take instructions to fail,
 * so it ignores this. Declared here rather than in the engine so that deleting the
 * simulator leaves no dangling import behind.
 */
export type FaultPoint = "none" | "detect" | "record";

// ------------------------------------------------------------------ blueprint

export interface TaskBlueprint {
  id: string;
  title: string;
  hint: string;
  /** The fixture `timeline` stage that advances this task. */
  stage: string;
}

export interface StepBlueprint {
  id: string;
  title: string;
  name: string;
  summary: string;
  tasks: readonly TaskBlueprint[];
}

export const PIPELINE: readonly StepBlueprint[] = [
  {
    id: "part1",
    title: "Part 1",
    name: "Capture",
    summary: "Take the request off the wire and pin down what was actually authorized.",
    tasks: [
      {
        id: "ingest",
        title: "Ingest communication",
        hint: "Receive the channel payload and stamp it into the log.",
        stage: "ingest",
      },
      {
        id: "extract",
        title: "Extract intent",
        hint: "Read the instruction; fingerprint the fields that must not change.",
        stage: "extract",
      },
    ],
  },
  {
    id: "part2",
    title: "Part 2",
    name: "Investigate",
    summary: "Score every dimension independently, then fuse them into one number.",
    tasks: [
      {
        id: "detect",
        title: "Score detectors",
        hint: "Voice, video, stylometry, behaviour, beneficiary — each on its own evidence.",
        stage: "detect",
      },
      {
        id: "fuse",
        title: "Fuse dimensions",
        hint: "Weighted arithmetic with an explicit penalty for what could not be scored.",
        stage: "fuse",
      },
    ],
  },
  {
    id: "part3",
    title: "Part 3",
    name: "Adjudicate",
    summary: "Apply policy deterministically, then make the decision provable.",
    tasks: [
      {
        id: "decide",
        title: "Apply policy",
        hint: "Bands, floors and hard overrides — approve, challenge or block.",
        stage: "decide",
      },
      {
        id: "record",
        title: "Record to chain",
        hint: "Append the decision to the hash chain so it can be verified later.",
        stage: "record",
      },
    ],
  },
] as const;

/** Every stage the blueprint knows, in execution order. */
export const STAGES: readonly string[] = PIPELINE.flatMap((p) => p.tasks.map((t) => t.stage));

/** `part2` → 2. Unknown ids yield 0. */
export function stepIndex(stepId: string): number {
  const i = PIPELINE.findIndex((s) => s.id === stepId);
  return i < 0 ? 0 : i + 1;
}

/** Route one event to its `{ step, task }` owner, or `null` for run-level events. */
export function ownerOf(ev: WorkflowEvent): { step: string; task: string } | null {
  if (!ev.stage) return null;
  for (const part of PIPELINE) {
    for (const task of part.tasks) {
      if (task.stage === ev.stage) return { step: part.id, task: task.id };
    }
  }
  return null;
}

/** The empty snapshot: what the screen renders before anything has run. */
export function idleSnapshot(): WorkflowSnapshot {
  return {
    currentStep: 0,
    status: "IDLE",
    steps: PIPELINE.map((part, i) => ({
      id: part.id,
      title: part.title,
      name: part.name,
      summary: part.summary,
      status: "PENDING",
      index: i + 1,
      tasks: part.tasks.map((t) => ({
        id: t.id, title: t.title, hint: t.hint, status: "PENDING",
        visited: false, eventCount: 0, durationMs: null, detail: null,
      })),
      logs: [],
      progress: 0,
      eventCount: 0,
      startedAt: null,
      endedAt: null,
      durationMs: null,
      error: null,
    })),
    output: null,
    runId: null,
    scenarioId: null,
    attempt: 1,
    error: null,
    startedAt: null,
    endedAt: null,
    eventCount: 0,
    logs: [],
    source: null,
  };
}
