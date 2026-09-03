/**
 * Data hooks — small, explicit, no React Query dependency. Every screen's loading,
 * error and empty states exist, because a screen without them is a screen that fails
 * open (§23: a UI that fails open is the same bug as a policy that fails open).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import type { ApiError } from "../api/client";
import type { BenchReport, ScenarioEnvelope } from "../api/types";

export type Loadable<T> =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "error"; error: ApiError };

export function useScenario(id: string | null) {
  const [load, setLoad] = useState<Loadable<{ data: ScenarioEnvelope; source: "live" | "fixture" }>>({ state: "idle" });
  const reload = useCallback(async () => {
    if (!id) return;
    setLoad({ state: "loading" });
    try {
      setLoad({ state: "ready", data: await api.loadScenario(id) });
    } catch (e) {
      setLoad({ state: "error", error: e as ApiError });
    }
  }, [id]);
  useEffect(() => { void reload(); }, [reload]);
  return { load, reload };
}

/** Poll on an interval, cleanly; pause when the tab is hidden (no stale banner mid-demo). */
export function usePoll<T>(fn: () => Promise<T>, intervalMs: number): { value: T | null; error: ApiError | null; refresh: () => void } {
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const timer = useRef<number | undefined>(undefined);

  const refresh = useCallback(() => {
    fnRef.current().then(setValue, (e: ApiError) => { setValue(null); setError(e); });
  }, []);

  useEffect(() => {
    const tick = () => {
      if (document.visibilityState === "visible") refresh();
    };
    refresh();
    timer.current = window.setInterval(tick, intervalMs);
    return () => window.clearInterval(timer.current);
  }, [refresh, intervalMs]);

  return { value, error, refresh };
}

/** The chain banner + footer: poll verify every 10 s and on demand (§21.2). */
export function useChain() {
  return usePoll(() => api.audit.verify(), 10_000);
}

/** Bench report from the service, falling back to the static artifact. */
export function useBench(live: boolean) {
  const [load, setLoad] = useState<Loadable<BenchReport>>({ state: "idle" });
  const run = useCallback(async () => {
    setLoad({ state: "loading" });
    try {
      setLoad({ state: "ready", data: await api.bench.run(live) });
    } catch {
      try {
        setLoad({ state: "ready", data: await api.bench.latest() as BenchReport });
      } catch {
        setLoad({ state: "error", error: { code: "UPSTREAM_UNAVAILABLE", detail: "No benchmark report available." } });
      }
    }
  }, [live]);
  useEffect(() => { void run(); }, [run]);
  return { load, run };
}

/**
 * Two stored assessments for the kill-switch Compare: exactly one region should differ,
 * the explanation. Automating the comparison is the point — nobody eyeballs JSON on
 * stage (§20).
 */
export interface ComparePair {
  withLlm: ScenarioEnvelope;
  withoutLlm: ScenarioEnvelope;
}

export function diffAssessments(a: ScenarioEnvelope["assessment"], b: ScenarioEnvelope["assessment"]): string[] {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  const differing: string[] = [];
  for (const k of keys) {
    if (JSON.stringify((a as unknown as Record<string, unknown>)[k]) !== JSON.stringify((b as unknown as Record<string, unknown>)[k])) {
      differing.push(k);
    }
  }
  return differing.sort();
}
