/**
 * The ChainBanner and DecisionBar â€” the two banner components with rules of their own:
 * the banner names the first broken seq, and the decision shows the band alongside the
 * override (the cheapest proof that nothing is hidden).
 */

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { ChainBanner } from "./ChainFooter";
import { DecisionBar } from "./DecisionBar";
import S06 from "@contracts/golden/S06.json";
import S01 from "@contracts/golden/S01.json";
import type { ScenarioEnvelope } from "../api/types";

const s06 = S06 as unknown as ScenarioEnvelope;
const s01 = S01 as unknown as ScenarioEnvelope;

describe("the chain banner", () => {
  it("green banner counts records and shows the head hash", () => {
    const { container } = render(
      <ChainBanner verify={{ ok: true, record_count: 1284, first_broken_seq: null, broken_field: null,
        broken_field_source: null, detail: null, untrusted_from: null,
        head_hash: "7f2a".padEnd(64, "0"), elapsed_ms: 38 }} />);
    const text = container.textContent ?? "";
    expect(text).toContain("1,284");
    expect(text).toContain("38 ms");
  });

  it("broken banner names the first broken seq and the inherited break", () => {
    const { container } = render(
      <ChainBanner verify={{ ok: false, record_count: 1284, first_broken_seq: 47,
        broken_field: "payload.amount_minor_units", broken_field_source: "demo_affordance",
        detail: "Record 47 no longer hashes to its stored value.",
        untrusted_from: 47, head_hash: null, elapsed_ms: 12 }} />);
    const text = container.textContent ?? "";
    expect(text).toContain("47");
    expect(text).toContain("payload.amount_minor_units");
    expect(text).toContain("47â€“1284");
  });
});

describe("the decision bar shows the band alongside the override", () => {
  it("S06: risk 58 (band CHALLENGE) struck through â†’ BLOCK â€” HO-1", () => {
    const { container, getByTestId } = render(<DecisionBar envelope={s06} />);
    const html = container.innerHTML;
    expect(getByTestId("decision")).toBeTruthy();
    expect(html).toContain("risk");
    expect(html).toContain("CHALLENGE");
    expect(html).toContain("HO-1");
    expect(html).toContain("BLOCK");
    // The strike-through styling is applied to the band when overridden:
    expect(html).toMatch(/line-through/);
  });

  it("S01 (no override): band and decision agree, no strike-through", () => {
    const { container } = render(<DecisionBar envelope={s01} />);
    expect(container.innerHTML).not.toMatch(/line-through/);
  });

  it("the override reason is a sentence, never a raw code alone", () => {
    const { container } = render(<DecisionBar envelope={s06} />);
    const text = container.textContent ?? "";
    expect(text).toContain("not the account that was authorized");
  });
});
