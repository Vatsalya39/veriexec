/**
 * `workflow/mockEngine.ts` — the replay engine. It owns *all* timing, jitter, fault
 * injection and cancellation for mock mode, and emits nothing but contract-shaped
 * `WorkflowEvent`s: the same objects a live SSE connection would deliver.
 *
 * Two clocks, kept honestly separate:
 *
 *   - `latencyMs` on each event is the engine's **real** measurement, taken verbatim from
 *     the fixture's `timeline[].latency_ms`. Never scaled, never invented.
 *   - the **replay dwell** is a presentation decision. The real pipeline finishes in about
 *     a second, which is the product's whole point and also unreadable on a projector, so
 *     each stage is held on screen long enough to read. The UI says so in words rather
 *     than letting a viewer infer that the pipeline is slow.
 *
 * Timestamps are stamped at emission time, not copied from the fixture: the recorded ones
 * are from whenever the trace was captured, and leaving them would make the header clock,
 * the per-task durations and the console disagree with each other.
 */

import type { ScenarioEnvelope } from "../api/types";
import type { EndReason, FaultPoint, WorkflowEvent, WorkflowEventType } from "./contract";
import { stagesOf } from "./timeline";

export interface EngineOptions {
  runId: string;
  envelope: ScenarioEnvelope;
  /** 1 = designed pacing. Larger is faster. `Infinity` emits with no delay (tests). */
  speed: number;
  fault: FaultPoint;
  onEvent(ev: WorkflowEvent): void;
  onEnd(reason: EndReason): void;
}

export interface EngineHandle {
  cancel(): void;
  isRunning(): boolean;
}

/**
 * Presentation dwell per stage in ms at 1×. Tuned so a run reads like work being done:
 * longer on the two stages that carry the reasoning, short on the bookkeeping. A full run
 * lands near 5 s, which is long enough to narrate and short enough to re-run on stage.
 */
const DWELL_MS: Record<string, number> = {
  ingest: 480,
  extract: 900,
  detect: 1100,
  fuse: 760,
  decide: 820,
  record: 620,
};

const DEFAULT_DWELL_MS = 600;
const JITTER = 0.16;

/** Deterministic 32-bit hash, so the same run id always jitters the same way. */
function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Small LCG. Seeded replay beats `Math.random()` for reproducing a demo. */
function lcg(seed: number): () => number {
  let state = seed || 1;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

function dwellFor(stage: string, speed: number, rand: () => number): number {
  if (!Number.isFinite(speed) || speed <= 0) return 0;
  const base = DWELL_MS[stage] ?? DEFAULT_DWELL_MS;
  const jittered = base * (1 + (rand() * 2 - 1) * JITTER);
  return Math.max(0, Math.round(jittered / speed));
}

/**
 * The stages this run will replay. Envelope arithmetic lives in `timeline.ts`; the engine
 * only decides how long each of them is held on screen.
 */

const FAULT_COPY: Record<Exclude<FaultPoint, "none">, { provider: string; reason: string }> = {
  detect: {
    provider: "voice-authenticity detector",
    reason: "the detector host did not answer within the scoring timeout",
  },
  record: {
    provider: "audit chain",
    reason: "the append call was refused: the chain head moved between read and write",
  },
};

/**
 * Start a replay. The returned handle's `cancel()` is safe to call at any time, including
 * after the run has already ended.
 */
export function startEngine(opts: EngineOptions): EngineHandle {
  const { runId, envelope, onEvent, onEnd } = opts;
  const rand = lcg(hash(runId));
  const stages = stagesOf(envelope);
  const breakAt = opts.fault === "none" ? -1 : stages.findIndex((s) => s.stage === opts.fault);

  let index = 0;
  let seq = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  const emit = (
    type: WorkflowEventType,
    fields: Partial<Omit<WorkflowEvent, "seq" | "ts" | "type">> = {},
  ) => {
    onEvent({ seq: seq++, ts: new Date().toISOString(), type, ...fields });
  };

  const finish = (reason: EndReason) => {
    if (stopped) return;
    stopped = true;
    if (timer !== null) clearTimeout(timer);
    timer = null;
    onEnd(reason);
  };

  const fail = () => {
    const s = stages[breakAt];
    const copy = FAULT_COPY[opts.fault as Exclude<FaultPoint, "none">];
    emit("stage_failed", {
      stage: s.stage,
      label: `${s.stage} failed`,
      detail: `${copy.provider} — ${copy.reason}.`,
      level: "error",
      payload: { provider: copy.provider, reason: copy.reason, retryable: true, stage: s.stage },
    });
    emit("run_failed", {
      label: "Run failed",
      detail: `No decision was rendered. The engine refuses to score a dimension it could not read, so the run stops rather than guessing — abstention is a result, not a gap.`,
      level: "error",
      payload: { failed_at: s.stage, retryable: true },
    });
    finish("failed");
  };

  const pump = () => {
    if (stopped) return;
    if (index >= stages.length) {
      emit("run_completed", {
        label: "Decision rendered",
        detail: `${envelope.assessment.decision} · risk ${envelope.assessment.risk_score} · policy ${envelope.assessment.policy_version}`,
        level: "success",
        payload: {
          decision: envelope.assessment.decision,
          risk_score: envelope.assessment.risk_score,
          assessment_id: envelope.assessment.assessment_id,
        },
      });
      finish("completed");
      return;
    }
    const s = stages[index];
    if (index === breakAt) { fail(); return; }
    emit("stage_completed", {
      stage: s.stage,
      label: s.label,
      detail: s.detail,
      level: "success",
      latencyMs: s.latencyMs ?? undefined,
      payload: { stage: s.stage, latency_ms: s.latencyMs },
    });
    index += 1;
    schedule();
  };

  const schedule = () => {
    if (stopped) return;
    if (index >= stages.length) { pump(); return; }
    const s = stages[index];
    // `stage_started` fires immediately so the row goes RUNNING the moment the stage is
    // entered; the dwell sits between started and completed, which is where a viewer
    // expects to see the spinner.
    emit("stage_started", {
      stage: s.stage,
      label: `${s.label} — running`,
      detail: s.detail,
      level: "info",
      payload: { stage: s.stage },
    });
    timer = setTimeout(pump, dwellFor(s.stage, opts.speed, rand));
  };

  emit("run_started", {
    label: "Run opened",
    detail: `${envelope.scenario.id} · ${envelope.scenario.title} · policy ${envelope.assessment.policy_version}`,
    level: "info",
    payload: { run_id: runId, scenario_id: envelope.scenario.id, intent_id: envelope.intent.intent_id },
  });
  schedule();

  return { cancel: () => finish("cancelled"), isRunning: () => !stopped };
}

/** Total replay wall time for a scenario at a given speed, for the UI's estimate. */
export function estimateDurationMs(envelope: ScenarioEnvelope, speed: number): number {
  if (!Number.isFinite(speed) || speed <= 0) return 0;
  return stagesOf(envelope).reduce((sum, s) => sum + (DWELL_MS[s.stage] ?? DEFAULT_DWELL_MS) / speed, 0);
}
