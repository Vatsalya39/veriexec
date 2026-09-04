/**
 * ★ The theme survives a reload, and the first paint is already correct. §23
 *
 * Two failures this guards against, both of which only show up in front of an audience:
 * a chosen mode forgotten on reload, and the white flash that happens when React applies
 * the theme after paint instead of the inline script applying it before.
 *
 * The flash is prevented by a script in `index.html` that must read the same storage key
 * and set the same class as this module. Nothing but a test keeps those two in agreement,
 * so the test reads both files and compares them.
 */

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, render } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { applyTheme, clearThemeChoice, storedTheme, useTheme } from "./useTheme";
import { ThemeToggle } from "../components/ThemeToggle";

const KEY = "intentlock-theme";

function reset() {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
  document.documentElement.style.colorScheme = "";
}

beforeEach(reset);
afterEach(reset);

describe("the theme is a property of the document", () => {
  it("applying dark sets the class, the color-scheme and the stored choice", () => {
    applyTheme("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(localStorage.getItem(KEY)).toBe("dark");
    expect(storedTheme()).toBe("dark");
  });

  it("applying light removes the class again", () => {
    applyTheme("dark");
    applyTheme("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(localStorage.getItem(KEY)).toBe("light");
  });

  it("an OS-driven change does not become the user's choice", () => {
    applyTheme("dark", false);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(storedTheme()).toBeNull();
  });

  it("clearing the choice returns to following the system", () => {
    applyTheme("dark");
    clearThemeChoice();
    expect(storedTheme()).toBeNull();
  });
});

/** A probe: the hook's value, rendered, so `useSyncExternalStore` is exercised for real. */
function Probe() {
  const { theme, followsSystem } = useTheme();
  return <span data-testid="probe">{theme}{followsSystem ? " auto" : ""}</span>;
}

describe("the toggle flips the document and every reader of it", () => {
  it("reports light and auto before a choice is made", () => {
    const { getByTestId } = render(<Probe />);
    expect(getByTestId("probe").textContent).toBe("light auto");
  });

  it("a store change re-renders subscribers without a context provider", () => {
    const { getByTestId } = render(<Probe />);
    act(() => applyTheme("dark"));
    expect(getByTestId("probe").textContent).toBe("dark");
  });

  it("the toggle button moves the document class", () => {
    const { container } = render(<ThemeToggle />);
    const button = container.querySelector("button");
    expect(button).toBeTruthy();
    act(() => button!.click());
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    act(() => button!.click());
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("names the mode it will switch to, not the one it is in", () => {
    const { container } = render(<ThemeToggle />);
    expect(container.querySelector("button")?.getAttribute("title")).toMatch(/dark/i);
  });
});

describe("the pre-paint script and the store agree", () => {
  const html = readFileSync(join(process.cwd(), "index.html"), "utf8");

  it("runs before the module bundle, in the head", () => {
    const scriptAt = html.indexOf("prefers-color-scheme");
    const moduleAt = html.indexOf("/src/main.tsx");
    expect(scriptAt).toBeGreaterThan(-1);
    expect(moduleAt).toBeGreaterThan(-1);
    expect(scriptAt, "the theme script must run before React loads").toBeLessThan(moduleAt);
  });

  it("reads the same storage key the store writes", () => {
    expect(html).toContain(KEY);
  });

  it("sets the same class and color-scheme the store sets", () => {
    expect(html).toMatch(/classList\.toggle\(\s*["']dark["']/);
    expect(html).toContain("colorScheme");
  });
});
