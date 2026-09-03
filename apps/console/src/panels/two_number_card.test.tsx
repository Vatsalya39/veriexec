/**
 * â˜… The two-number card obeys its rules. Â§8.2
 *
 * Voice authenticity neutral grey at any value; intent confidence in the decision
 * colour; identical geometry; both on one screen, always.
 */

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { TwinNumberCard } from "./TwoNumberCard";

function barStyles(container: HTMLElement) {
  const bars = container.querySelectorAll<HTMLElement>(".twin-meter > span");
  const [voice, intent] = bars;
  return { voice, intent, bars };
}

describe("the two-number card", () => {
  it("renders both numbers, adjacent, always", () => {
    const { getByTestId } = render(
      <TwinNumberCard voiceAuthenticity={96} intentConfidence={20} decision="BLOCK" />);
    expect(getByTestId("voice-authenticity")).toBeTruthy();
    expect(getByTestId("intent-confidence")).toBeTruthy();
  });

  it("voice bar is neutral grey at ANY value â€” even 96 next to a red 20", () => {
    const { container } = render(
      <TwinNumberCard voiceAuthenticity={96} intentConfidence={20} decision="BLOCK" />);
    const { voice, intent } = barStyles(container);
    expect(voice!.style.background).toBe("var(--neutral)");
    expect(intent!.style.background).toBe("var(--block)"); // decision colour
  });

  it("voice bar stays neutral even when voice is 3", () => {
    const { container } = render(
      <TwinNumberCard voiceAuthenticity={3} intentConfidence={85} decision="APPROVE" />);
    const { voice, intent } = barStyles(container);
    expect(voice!.style.background).toBe("var(--neutral)");
    expect(intent!.style.background).toBe("var(--approve)");
  });

  it("both bars share geometry â€” one class, same height", () => {
    const { container } = render(
      <TwinNumberCard voiceAuthenticity={50} intentConfidence={50} decision="CHALLENGE" />);
    const bars = container.querySelectorAll<HTMLElement>(".twin-meter");
    expect(bars.length).toBe(2);
    expect(bars[0].className).toBe(bars[1].className);
    expect(getComputedStyle(bars[0]).height).toBe(getComputedStyle(bars[1]).height);
  });

  it("an abstained voice reads as abstained, never as 0 (unavailable â‰  clean)", () => {
    const { getByTestId } = render(
      <TwinNumberCard voiceAuthenticity={null} intentConfidence={40} decision="CHALLENGE" />);
    expect(getByTestId("voice-authenticity").textContent).toContain("abstained");
    expect(getByTestId("voice-authenticity").textContent).not.toContain("0");
  });

  it("labels are the two questions", () => {
    const { container } = render(
      <TwinNumberCard voiceAuthenticity={96} intentConfidence={20} decision="BLOCK" />);
    const text = container.textContent ?? "";
    expect(text).toContain("Is it him?");
    expect(text).toContain("Is it his transaction?");
  });
});
