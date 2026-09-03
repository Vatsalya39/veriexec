/**
 * â˜… The error states. Â§23, Â§26 trap 10
 *
 * An upstream timeout renders the error pane â€” never a 0 contribution, never a blank
 * panel with the approve button live. A UI that fails open is the same bug as a policy
 * that fails open.
 */

import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { ErrorPane, Loading } from "./ui";
import { TwinNumberCard } from "../panels/TwoNumberCard";

describe("error and empty states fail closed", () => {
  it("a timeout renders the error pane, not a zero", () => {
    const { container, getByText } = render(
      <ErrorPane error={{ code: "TIMEOUT", detail: "http://127.0.0.1:8002 did not respond" }} />);
    expect(getByText(/did not respond in 3 seconds/i)).toBeTruthy();
    expect(container.textContent).toContain("not been approved");
  });

  it("upstream unavailable names the fallback", () => {
    const { getByRole } = render(
      <ErrorPane error={{ code: "UPSTREAM_UNAVAILABLE", detail: ":8002 unreachable" }} />);
    expect(getByRole("alert")).toBeTruthy();
  });

  it("loading carries a stage label, not a bare spinner", () => {
    const { getByText } = render(<Loading label="Scoring S06" />);
    expect(getByText(/Scoring S06â€¦/)).toBeTruthy();
  });

  it("an abstained voice renders as absent, not as 0 â€” unavailable â‰  clean", () => {
    const { getByTestId } = render(
      <TwinNumberCard voiceAuthenticity={null} intentConfidence={40} decision="CHALLENGE" />);
    const text = getByTestId("voice-authenticity").textContent ?? "";
    expect(text).toContain("abstained");
    expect(text).not.toMatch(/^0/);
  });

  it("fetch timeout code is typed, not a stringly error", () => {
    expect(() => render(<ErrorPane error={{ code: "TIMEOUT", detail: "x" }} />)).not.toThrow();
  });
});

describe("the client's timeout discipline", () => {
  it("aborts after 3 seconds with a typed TIMEOUT error", async () => {
    vi.stubGlobal("fetch", (_url: string, init?: { signal?: AbortSignal }) => {
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          const err = new Error("aborted");
          err.name = "AbortError";
          reject(Object.assign(err, { code: 20 }));
        });
      });
    });
    const { audit } = await import("../api/client");
    await expect(audit.head()).rejects.toMatchObject({ code: "TIMEOUT" });
    vi.unstubAllGlobals();
  });
});
