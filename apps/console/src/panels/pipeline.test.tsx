/**
 * ★ The pipeline is a pure function of its event stream. §7
 *
 * Three claims, in order of how expensive they are to get wrong:
 *
 *   1. The fold is honest. Every state a part card can show — pending, running, completed,
 *      failed — comes from the events, and the latency it reports is the fixture's own
 *      `latency_ms`, never the replay's dwell.
 *   2. A failed run stops. No decision is rendered, the later parts stay untouched, and
 *      retry is offered rather than assumed.
 *   3. The presentation is coupled to nothing. The same components render a stream that
 *      arrived from the replay engine and one hand-written here, because they read a
 *      snapshot and hold no timers of their own.
 */

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { deriveSnapshot } from "../workflow/deriveSnapshot";
import { idleSnapshot, type EndReason, type FaultPoint, type WorkflowEvent } from "../workflow/contract";
import { startEngine } from "../workflow/mockEngine";
import { measuredLatencyMs, stagesOf } from "../workflow/timeline";
import { PipelineVisualizer } from "./PipelineVisualizer";
import { RunConsole } from "./RunConsole";
import S06 from "@contracts/golden/S06.json";
import type { ScenarioEnvelope } from "../api/types";

const env = S06 as unknown as ScenarioEnvelope;

/** Run the replay engine to its end with no dwell, and hand back what it emitted. */
function replay(fault: FaultPoint): Promise<{ events: WorkflowEvent[]; reason: EndReason }> {
  return new Promise((resolve) => {
    const events: WorkflowEvent[] = [];
    startEngine({
      runId: "run-test-0001",
      envelope: env,
      speed: Number.POSITIVE_INFINITY,
      fault,
      onEvent: (ev) => events.push(ev),
      onEnd: (reason) => resolve({ events, reason }),
    });
  });
}

function snapshotOf(events: WorkflowEvent[], cancelled = false) {
  return deriveSnapshot(events, {
    runId: "run-test-0001", scenarioId: "S06", attempt: 1, cancelled,
    envelope: env, source: "fixture",
  });
}

describe("the idle pipeline claims nothing", () => {
  it("is three pending parts and no output", () => {
    const snap = idleSnapshot();
    expect(snap.status).toBe("IDLE");
    expect(snap.currentStep).toBe(0);
    expect(snap.output).toBeNull();
    expect(snap.steps).toHaveLength(3);
    expect(snap.steps.every((s) => s.status === "PENDING")).toBe(true);
    expect(snap.steps.flatMap((s) => s.tasks).every((t) => t.status === "PENDING")).toBe(true);
  });
});

describe("a clean run folds to three completed parts", () => {
  it("ends completed, having covered every stage in the envelope", async () => {
    const { events, reason } = await replay("none");
    expect(reason).toBe("completed");

    const stages = stagesOf(env).map((s) => s.stage);
    const started = events.filter((e) => e.type === "stage_started").map((e) => e.stage);
    expect(started).toEqual(stages);
    expect(events.at(0)?.type).toBe("run_started");
    expect(events.at(-1)?.type).toBe("run_completed");
  });

  it("reports the engine's measured latency, not the replay's dwell", async () => {
    const { events } = await replay("none");
    const snap = snapshotOf(events);
    const recorded = new Map(stagesOf(env).map((s) => [s.stage, s.latencyMs]));

    for (const step of snap.steps) {
      for (const task of step.tasks) {
        expect(task.durationMs, `${task.id} duration`).toBe(recorded.get(task.id) ?? null);
      }
    }
    expect(snap.output?.wallMs).toBe(measuredLatencyMs(env));
  });

  it("renders the decision the envelope already contains", async () => {
    const { events } = await replay("none");
    const snap = snapshotOf(events);

    expect(snap.status).toBe("COMPLETED");
    expect(snap.currentStep).toBe(3);
    expect(snap.steps.every((s) => s.status === "COMPLETED")).toBe(true);
    expect(snap.steps.every((s) => s.progress === 1)).toBe(true);
    expect(snap.output?.decision).toBe(env.assessment.decision);
    expect(snap.output?.riskScore).toBe(env.assessment.risk_score);
    expect(snap.error).toBeNull();
  });
});

describe("exactly one task is running at a time", () => {
  it("a truncated stream leaves one running task and the rest untouched", async () => {
    const { events } = await replay("none");
    // Cut immediately after the third stage opened: part 2's first task is in flight.
    const thirdStart = events.filter((e) => e.type === "stage_started")[2];
    const snap = snapshotOf(events.slice(0, events.indexOf(thirdStart) + 1));

    expect(snap.status).toBe("RUNNING");
    expect(snap.currentStep).toBe(2);
    const running = snap.steps.flatMap((s) => s.tasks).filter((t) => t.status === "RUNNING");
    expect(running).toHaveLength(1);
    expect(running[0].id).toBe("detect");
    expect(snap.steps[0].status).toBe("COMPLETED");
    expect(snap.steps[2].status).toBe("PENDING");
    expect(snap.output).toBeNull();
  });
});

describe("a failed run stops and offers a retry", () => {
  it("fails in part 2 without touching part 3, and renders no decision", async () => {
    const { events, reason } = await replay("detect");
    expect(reason).toBe("failed");

    const snap = snapshotOf(events);
    expect(snap.status).toBe("FAILED");
    expect(snap.steps[0].status).toBe("COMPLETED");
    expect(snap.steps[1].status).toBe("FAILED");
    expect(snap.steps[2].status).toBe("PENDING");
    expect(snap.output).toBeNull();
    expect(snap.error).toBeTruthy();

    const { getByTestId } = render(<PipelineVisualizer snapshot={snap} onRetry={() => {}} />);
    expect(getByTestId("part-card-part2").getAttribute("data-status")).toBe("FAILED");
    expect(getByTestId("part-card-part2").textContent).toContain("Retry");
    expect(getByTestId("part-card-part3").getAttribute("data-status")).toBe("PENDING");
  });

  it("a cancelled run is stopped, not failed", async () => {
    const { events } = await replay("none");
    const snap = snapshotOf(events.slice(0, 4), true);
    expect(snap.status).toBe("CANCELLED");
    expect(snap.output).toBeNull();
  });
});

describe("the visualizer and the console read the snapshot and nothing else", () => {
  it("draws one card per part, each carrying its state as data", async () => {
    const { events } = await replay("none");
    const snap = snapshotOf(events);
    const { getByTestId } = render(<PipelineVisualizer snapshot={snap} />);

    expect(getByTestId("pipeline-visualizer").getAttribute("data-current-step")).toBe("3");
    for (const id of ["part1", "part2", "part3"]) {
      expect(getByTestId(`part-card-${id}`).getAttribute("data-status")).toBe("COMPLETED");
    }
  });

  it("scoping the console to one part hides the others", async () => {
    const { events } = await replay("none");
    const snap = snapshotOf(events);

    // Two independent renders, queried through their own containers: the console holds no
    // module state, so the second knows nothing about the first.
    const all = render(<RunConsole snapshot={snap} />);
    const allLines = all.container.querySelectorAll("li.log");
    expect(allLines.length).toBe(snap.logs.length);

    const scoped = render(<RunConsole snapshot={snap} activeStepId="part2" />);
    const rows = [...scoped.container.querySelectorAll("li.log")];
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThan(allLines.length);
    expect(rows.every((li) => li.getAttribute("data-step") === "part2")).toBe(true);
  });

  it("the idle console invites a run rather than showing an empty box", () => {
    const { getByTestId } = render(<RunConsole snapshot={idleSnapshot()} />);
    expect(getByTestId("run-console").textContent).toContain("Run the verification");
  });
});
