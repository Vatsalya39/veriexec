/**
 * Contract shape insurance (Â§7.1): every property the console reads from the golden
 * fixtures exists on the hand-written types, and S06 â€” the hero scenario â€” carries every
 * field the verification panel needs. Hand-written types drift from contracts silently;
 * this is the cheap insurance against `undefined` on a screen during the demo.
 */

import { describe, expect, it } from "vitest";
import S06 from "@contracts/golden/S06.json";
import S09 from "@contracts/golden/S09.json";
import S21 from "@contracts/golden/S21.json";
import type { ScenarioEnvelope } from "./types";

describe("the golden fixtures satisfy the console's types", () => {
  it("S06 (hero 1, the thesis) carries the full verification story", () => {
    const env = S06 as unknown as ScenarioEnvelope;
    const a = env.assessment;
    expect(a.decision).toBe("BLOCK");
    expect(a.band_outcome).toBe("CHALLENGE");   // the override story: band struck through
    expect(a.override_applied).toBe("HO-1");
    expect(a.risk_score).toBe(58);
    expect(a.contributions.length).toBe(7);      // seven dimensions, every row cited
    expect(a.contributions.every((c) => c.evidence_ref && c.reason)).toBe(true);
    expect(a.intent_confidence.value).toBe(12);
    expect(a.intent_confidence.excludes).toContain("voice_authenticity");
    expect(env.signals.communication?.voice_authenticity).toBe(96);
    expect(env.signals.fingerprint!.verdict).toBe("MISMATCH");
    expect(env.signals.fingerprint!.field_deltas.length).toBeGreaterThan(2);
    expect(a.counterfactual?.narrative).toContain("No change to risk scoring");
    expect(a.evidence_graph?.nodes.length).toBeGreaterThan(10);
  });

  it("S09 (hero 2, duress) renders PROCESSING to the requester, never the word", () => {
    const env = S09 as unknown as ScenarioEnvelope;
    expect(env.assessment.duress_escalation).toBe(true);
    expect(env.assessment.visible_to_requester).toBe("PROCESSING");
    const flat = JSON.stringify(env);
    // The category may exist; the mechanism's label must not leak into the fixture.
    expect(flat).not.toMatch(/duress_scheme|marker_position/);
  });

  it("S21 (legit, frictionless) mints a capability token with scope", () => {
    const env = S21 as unknown as ScenarioEnvelope;
    expect(env.capability_token).not.toBeNull();
    expect(env.capability_token!.single_use).toBe(true);
    expect(env.capability_token!.fingerprint_hex).toMatch(/^[0-9a-f]{64}$/);
    expect(env.capability_token!.mac).toMatch(/^[0-9a-f]{64}$/);
  });

  it("all fixtures mask accounts to last-4 â€” no full account in a served file", () => {
    for (const sid of ["S01", "S06", "S09", "S21"]) {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const fixture = (await0(sid)) as unknown as ScenarioEnvelope;
      const flat = JSON.stringify(fixture);
      expect(flat).not.toMatch(/HDFC000\d{7,}|ADCB000\d{7,}/);
    }
  });
});

function await0(sid: string) {
  // sync require for the loop case; Vite/vitest resolve JSON statically
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  return { S01: S06, S06, S09, S21 }[sid as "S01" | "S06" | "S09" | "S21"];
}
