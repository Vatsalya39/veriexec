/**
 * ★ The simulator is removable. §7, and the whole premise of the mock architecture.
 *
 * The claim this file defends is the one that costs the most to discover late: that going
 * live is a one-file change. It is enforced structurally rather than by review, because a
 * single convenient import from a panel would quietly make the mock load-bearing.
 *
 * Two rules:
 *   1. No component, screen or hook imports the replay engine or its run store. Only
 *      `verificationService.ts` — the swap point — may name those files.
 *   2. No presentation file starts, times or schedules a run: no `setTimeout`/`setInterval`
 *      driving pipeline state, no `startEngine`, no fixture-derived pacing.
 */

import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

/** Vitest runs from the console package root; the sources are one directory in. */
const SRC = join(process.cwd(), "src");

function sourcesUnder(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(join(SRC, dir), { withFileTypes: true })) {
    const rel = `${dir}/${entry.name}`;
    if (entry.isDirectory()) { out.push(...sourcesUnder(rel)); continue; }
    if (!/\.tsx?$/.test(entry.name)) continue;
    if (entry.name.includes(".test.")) continue;
    out.push(rel);
  }
  return out;
}

/** Everything a reviewer would call "the UI", plus the hook layer above it. */
const PRESENTATION = [
  ...sourcesUnder("components"),
  ...sourcesUnder("panels"),
  ...sourcesUnder("screens"),
  ...sourcesUnder("state"),
];

function read(rel: string): string {
  return readFileSync(join(SRC, rel), "utf8");
}

describe("the mock engine is behind exactly one door", () => {
  it("finds the presentation layer it claims to check", () => {
    expect(PRESENTATION.length).toBeGreaterThan(15);
    expect(PRESENTATION).toContain("screens/Pipeline.tsx");
    expect(PRESENTATION).toContain("panels/PipelineVisualizer.tsx");
    expect(PRESENTATION).toContain("state/useVerification.ts");
  });

  it("no component, screen or hook imports mockEngine or mockRuns", () => {
    const offenders = PRESENTATION.filter((rel) => /from\s+["'][^"']*mock(Engine|Runs)["']/.test(read(rel)));
    expect(offenders, "these files would break when the simulator is deleted").toEqual([]);
  });

  it("only the swap point names the mock modules at all", () => {
    const workflow = sourcesUnder("workflow");
    const namers = workflow.filter((rel) => rel !== "workflow/verificationService.ts"
      && /["'][^"']*mock(Engine|Runs)["']/.test(read(rel)));
    // `mockRuns` imports the engine — that is the simulator wiring itself together.
    expect(namers).toEqual(["workflow/mockRuns.ts"]);
  });

  it("the swap point reaches the mock only through dynamic import", () => {
    const svc = read("workflow/verificationService.ts");
    expect(svc).toMatch(/await import\(["']\.\/mockRuns["']\)/);
    // A static import would put the simulator in the production bundle unconditionally.
    expect(svc).not.toMatch(/^import .*mock(Engine|Runs)/m);
  });
});

/** The files that render a run. None of them may advance one. */
const PIPELINE_UI = [
  "components/AppShell.tsx",
  "panels/PhaseMonitor.tsx",
  "panels/PipelineVisualizer.tsx",
  "panels/RunConsole.tsx",
  "panels/RunControls.tsx",
  "screens/Pipeline.tsx",
];

describe("no presentation file drives the pipeline itself", () => {
  it("nothing that renders a run starts one, or paces it with an interval", () => {
    for (const rel of PIPELINE_UI) {
      const src = read(rel);
      expect(src, `${rel} starts a run`).not.toMatch(/startEngine/);
      expect(src, `${rel} paces the pipeline`).not.toMatch(/setInterval/);
      // Prose may name the simulator — the visualizer's header brags about not needing it.
      // An import may not.
      expect(src, `${rel} reaches past the swap point`)
        .not.toMatch(/from\s+["'][^"']*mock(Engine|Runs)["']/);
    }
  });

  it("the two surfaces that draw run state hold no timers at all", () => {
    for (const rel of ["panels/PipelineVisualizer.tsx", "panels/PhaseMonitor.tsx"]) {
      expect(read(rel), `${rel} holds a timer`).not.toMatch(/setTimeout|setInterval|requestAnimationFrame/);
    }
  });

  it("the visualizer holds no state at all", () => {
    const src = read("panels/PipelineVisualizer.tsx");
    expect(src).not.toMatch(/useState|useEffect|useReducer|setTimeout/);
  });

  it("the console holds only presentational state", () => {
    const src = read("panels/RunConsole.tsx");
    // `pinned` and `copied` are about the viewport and the clipboard, not the run.
    const states = [...src.matchAll(/useState[<(]/g)];
    expect(states).toHaveLength(2);
    expect(src).toMatch(/const \[pinned, setPinned\]/);
    expect(src).toMatch(/const \[copied, setCopied\]/);
  });
});

describe("the derived snapshot is pure", () => {
  it("the fold imports no React and no clock", () => {
    const src = read("workflow/deriveSnapshot.ts");
    expect(src).not.toMatch(/from ["']react["']/);
    expect(src).not.toMatch(/setTimeout|setInterval/);
  });
});
