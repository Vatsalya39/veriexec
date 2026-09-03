/**
 * ★ The challenge DOM contains no answers. §9.1 — the single most attackable claim in
 * the system. Rendered S06 challenge must contain neither the amount, its digit runs,
 * nor the destination account's last-4. The challenge carries `answer_hmac` only.
 */

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { ChallengeScreen } from "./Challenge";
import S06 from "@contracts/golden/S06.json";
import type { ScenarioEnvelope } from "../api/types";

const env = {
  ...S06,
  challenge: {
    challenge_id: "CHL-S06",
    session_id: "SES-S06",
    nonce: "7f8a9b0c1d2e3f4a",
    issued_at: new Date(Date.now() + 600000).toISOString(),
    expires_at: new Date(Date.now() + 900000).toISOString(),
    attempts_allowed: 3,
    answer_hmac: "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0",
  },
} as unknown as ScenarioEnvelope;

// The values that must never appear. Amount in paise and the raw amount as digits.
const FORBIDDEN = [
  "1000000000",           // amount_minor_units (₹1,00,00,000 in paise)
  "1,00,00,000",
  "10,00,000",            // the originally authorized ₹10 lakh
  "100000000",
  "9281",                 // destination account last-4 (unmasked value in fixtures)
  "7890",                 // authorized account last-4
  "Global Trading FZE",   // payee — the answer to "which payee"
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
