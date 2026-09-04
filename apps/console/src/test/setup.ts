// Vitest setup: jsdom globals + a deterministic-enough crypto polyfill for the
// chain-recompute test (Node's WebCrypto is present in modern versions; assert early),
// and a localStorage bridge for the theme store.
//
// The bridge exists because this vitest build's jsdom environment transfers a fixed
// `LIVING_KEYS` list of window properties to globalThis and `localStorage` is not on it
// (jsdom itself provisions it only when the document has a real origin). The theme store
// is a plain module that reads `localStorage` at call time, so binding the same object
// the jsdom window would have used is the smallest honest fix — not a fake with different
// semantics.

import { beforeEach } from "vitest";

beforeEach(() => {
  if (typeof crypto !== "undefined" && !crypto.subtle) {
    throw new Error("WebCrypto unavailable — tests that hash need Node >= 19.");
  }
  if (typeof localStorage === "undefined" || localStorage === undefined) {
    const win = (globalThis as unknown as { window?: { localStorage?: Storage } }).window;
    if (win && win.localStorage) {
      (globalThis as Record<string, unknown>).localStorage = win.localStorage;
    } else {
      // Last resort: an in-memory Storage with the Web Storage API surface the theme
      // store exercises (getItem/setItem/removeItem/clear + key/length).
      const store = new Map<string, string>();
      class MemStorage {
        get length(): number { return store.size; }
        key(index: number): string | null { return [...store.keys()][index] ?? null; }
        getItem(key: string): string | null { return store.has(key) ? store.get(key)! : null; }
        setItem(key: string, value: string): void { store.set(String(key), String(value)); }
        removeItem(key: string): void { store.delete(key); }
        clear(): void { store.clear(); }
      }
      (globalThis as Record<string, unknown>).localStorage = new MemStorage();
    }
  }
});
