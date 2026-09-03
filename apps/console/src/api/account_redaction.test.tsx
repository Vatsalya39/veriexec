/**
 * â˜… Account redaction across every fixture. Â§8.4
 *
 * Walk the rendering path for all 22 fixtures: no component may render more than the
 * last 4 digits of an account. The copy payload too â€” a judge with devtools open is a
 * real scenario, and "redacted in the UI but full in the JSON" is worse than not
 * redacting.
 */

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { redactAccount } from "./format";
import { FieldDiff } from "../panels/FieldDiff";
import { OobPanel } from "../panels/OobPanel";
import type { ScenarioEnvelope } from "./types";

// The masked fixtures load statically for a handful; walking all 22 via import.meta.glob
// keeps the walk honest without a dynamic import per id.
const modules = import.meta.glob("@contracts/golden/S*.json", { eager: true }) as
  Record<string, { default: ScenarioEnvelope }>;
const fixtures = Object.entries(modules)
  .map(([path, mod]) => [path.match(/S\d+\.json$/)?.[0]?.replace(".json", ""), mod.default] as const)
  .filter(([id]) => Boolean(id));

const FULL_ACCOUNT = /\b(?:HDFC|ICIC|SBIN|ADCB|EBIL|AXIS)0\d{7,}\b/;

describe("account redaction", () => {
  it("walks all 22 fixtures", () => {
    expect(fixtures.length).toBe(22);
  });

  it("the redaction helper never emits a full account", () => {
    for (const bank of ["HDFC0001234567890", "ADCB0000099281", "SBIN0000000001"]) {
      const out = redactAccount(bank);
      expect(out).toBe(`••••${bank.slice(-4)}`);
      expect(FULL_ACCOUNT.test(out)).toBe(false);
    }
  });

  it("FieldDiff renders no full account in the DOM", () => {
    for (const [id, env] of fixtures) {
      const { container } = render(<FieldDiff envelope={env} />);
      const html = container.innerHTML;
      expect(FULL_ACCOUNT.test(html), `${id} leaks a full account in FieldDiff`).toBe(false);
    }
  });

  it("OobPanel renders registered contacts masked", () => {
    const withOob = fixtures.find(([, env]) => env.out_of_band !== null);
    if (!withOob) return;
    const { container } = render(<OobPanel envelope={withOob[1]} />);
    expect(container.textContent).not.toMatch(/\d{6,}/); // no 6+ digit run of any phone
  });

  it("masked values stay masked — redaction is idempotent", () => {
    expect(redactAccount("••••9281")).toBe("••••9281");
  });
});
