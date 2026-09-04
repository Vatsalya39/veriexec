/**
 * `state/useTheme.ts` — the persistent theme store. §23
 *
 * One module-level store, not a context: the theme is a property of the document, so it
 * lives where the document does. `useSyncExternalStore` reads it straight from the class
 * list, which means the pre-paint script in `index.html` is the single source of truth at
 * boot and React never fights it (no flash, no double-apply, no hydration mismatch).
 *
 * Choice is sticky, absence is not: once a judge picks a mode we honour it forever; until
 * then we follow the OS, live, so a projector switched to dark mode carries the console
 * with it. Clearing the stored choice returns to that following behaviour.
 */

import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "intentlock-theme";

const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function emit(): void {
  listeners.forEach((l) => l());
}

/** Read the live theme off the document — the class list, never a duplicated variable. */
function currentTheme(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

/** The stored preference, or `null` when the user has never chosen. */
export function storedTheme(): Theme | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw === "dark" || raw === "light" ? raw : null;
  } catch {
    return null;                                  // private mode: session-only is fine
  }
}

function systemTheme(): Theme {
  return typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/**
 * Apply a theme to the document. `persist: false` is how OS changes land — they must not
 * silently become the user's stored choice, or "follow the system" would end after one
 * system change.
 */
export function applyTheme(theme: Theme, persist = true): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.documentElement.style.colorScheme = theme;
  if (persist) {
    try { localStorage.setItem(STORAGE_KEY, theme); } catch { /* session only */ }
  }
  emit();
}

/** Forget the choice and go back to following the OS. */
export function clearThemeChoice(): void {
  try { localStorage.removeItem(STORAGE_KEY); } catch { /* nothing to forget */ }
  applyTheme(systemTheme(), false);
}

// Follow the OS for as long as the user has not overridden it. Registered once, at module
// load, because the subscription belongs to the document and not to any component's life.
if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const onSystemChange = (e: MediaQueryListEvent) => {
    if (storedTheme() === null) applyTheme(e.matches ? "dark" : "light", false);
  };
  if (typeof media.addEventListener === "function") media.addEventListener("change", onSystemChange);
}

export interface ThemeApi {
  theme: Theme;
  /** True while the console is tracking the OS rather than an explicit choice. */
  followsSystem: boolean;
  setTheme: (theme: Theme) => void;
  toggle: () => void;
  followSystem: () => void;
}

export function useTheme(): ThemeApi {
  const theme = useSyncExternalStore(subscribe, currentTheme, () => "light" as Theme);
  return {
    theme,
    followsSystem: storedTheme() === null,
    setTheme: (next) => applyTheme(next),
    toggle: () => applyTheme(theme === "dark" ? "light" : "dark"),
    followSystem: clearThemeChoice,
  };
}
