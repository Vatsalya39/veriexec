/**
 * â˜… The challenge DOM contains no answers. Â§9.1 â€” the single most attackable claim in
 * the system. Rendered S06 challenge must contain neither the amount, its digit runs,
 * nor the destination account's last-4. The challenge carries `answer_hmac` only.
 */

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { ChallengeScreen } from "./Challenge";
import S06 from "@contracts/golden/S06.json";
import type { ScenarioEnvelope } from "../api/types";

const env = S06 as unknown as ScenarioEnvelope;

// The values that must never appear. Amount in paise and the raw amount as digits.
const FORBIDDEN = [
  "1000000000",           // amount_minor_units (â‚¹1,00,00,000 in paise)
  "1,00,00,000",
  "10,00,000",            // the originally authorized â‚¹10 lakh
  "100000000",
  "9281",                 // destination account last-4 (unmasked value in fixtures)
  "7890",                 // authorized account last-4
  "Global Trading FZE",   // payee â€” the answer to "which payee"
  "BEN-003",
];

describe("the challenge screen never contains its own answers", () => {
  it("renders", () => {
    const { getByTestId } = render(<ChallengeScreen envelope={env} />);
    expect(getByTestId("challenge")).toBeTruthy();
  });

  it("serialized DOM carries none of the forbidden values", () => {
    const { container } = render(<ChallengeScreen envelope={env} />);
    const html = container.innerHTML;
    for (const value of FORBIDDEN) {
      expect(html, `DOM leaks the answer "${value}"`).not.toContain(value);
    }
  });

  it("carries the hmac and nonce, not the answer", () => {
    const { container } = render(<ChallengeScreen envelope={env} />);
    const html = container.innerHTML;
    expect(html).toContain("answer_hmac");
    expect(html).toContain(env.challenge!.nonce);
  });

  it("prompt asks a question, not a consent", () => {
    const { container } = render(<ChallengeScreen envelope={env} />);
    expect(container.innerHTML).not.toMatch(/do you approve/i);
  });
});
