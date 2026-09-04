/**
 * `workflow/timeline.ts` — reading the stage timeline off a run envelope.
 *
 * This is envelope arithmetic, not simulation: the numbers here are the ones the engine
 * measured, whether they arrive from a frozen fixture or from a live core response. It
 * lives outside `mockEngine.ts` so that deleting the simulator leaves the console's
 * latency reporting untouched.
 */

import type { ScenarioEnvelope } from "../api/types";
import { STAGES } from "./contract";

export interface StageRow {
  stage: string;
  label: string;
  detail: string;
  /** The engine's real measurement. `null` when the envelope carries no timeline. */
  latencyMs: number | null;
}

/**
 * The stages a run covers: the envelope's own timeline when it has one, otherwise the
 * blueprint order with no latency, so a sandbox envelope still moves through the pipeline
 * instead of rendering an empty one.
 */
export function stagesOf(envelope: ScenarioEnvelope): StageRow[] {
  const timeline = envelope.timeline ?? [];
  if (timeline.length > 0) {
    return timeline.map((t) => ({
      stage: t.stage, label: t.label, detail: t.detail, latencyMs: t.latency_ms ?? null,
    }));
  }
  return STAGES.map((stage) => ({
    stage,
    label: stage,
    detail: "No recorded timeline for this envelope — the stage ran, its latency was not captured.",
    latencyMs: null,
  }));
}

/** The engine's real measured total — the number the product actually claims. */
export function measuredLatencyMs(envelope: ScenarioEnvelope): number {
  return stagesOf(envelope).reduce((sum, s) => sum + (s.latencyMs ?? 0), 0);
}
