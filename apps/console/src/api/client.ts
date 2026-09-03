/**
 * Typed fetch wrappers, one per service. §24
 *
 * Rules (§24.2, made structural here): a 3-second timeout; one retry only on GET; a typed
 * error state that carries a stable machine code — never a partial result rendered as
 * complete. A dashboard that quietly renders `0` for a missing contribution is the exact
 * "unavailable ≠ clean" failure the whole project argues against, committed in the
 * presentation layer.
 */

import type {
  AskResult, AuditRecord, BenchReport, BenchRow, CanaryHistory, CanaryRun,
  HealthResult, ScenarioEnvelope, VerifyResult,
} from "./types";

export const AUDIT_URL = (import.meta.env?.VITE_AUDIT_URL as string | undefined)
  ?? "http://127.0.0.1:8003";
export const CORE_URL = (import.meta.env?.VITE_CORE_URL as string | undefined)
  ?? "http://127.0.0.1:8002";
export const SIGNAL_URL = (import.meta.env?.VITE_SIGNAL_URL as string | undefined)
  ?? "http://127.0.0.1:8001";

export type ApiError = { code: "UPSTREAM_UNAVAILABLE" | "TIMEOUT" | "HTTP_" | "BAD_JSON"; detail: string };

const TIMEOUT_MS = 3000;

async function call<T>(
  method: "GET" | "POST",
  url: string,
  body?: unknown,
  opts: { retry?: boolean } = {},
): Promise<T> {
  const attempt = async (): Promise<T> => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const res = await fetch(url, {
        method,
        headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try { detail = ((await res.json()) as { detail?: string }).detail ?? detail; } catch { /* keep status */ }
        throw { code: `HTTP_`, detail: `${detail} (HTTP ${res.status})` } as ApiError;
      }
      return (await res.json()) as T;
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        throw { code: "TIMEOUT", detail: `${url} did not respond in 3 seconds` } as ApiError;
      }
      if ((err as ApiError)?.code) throw err;
      throw { code: "UPSTREAM_UNAVAILABLE", detail: `${url}: unreachable` } as ApiError;
    } finally {
      clearTimeout(timer);
    }
  };
  try {
    return await attempt();
  } catch (err) {
    const apiErr = err as ApiError;
    if (method === "GET" && opts.retry !== false && apiErr.code !== "HTTP_") {
      return attempt(); // one retry, GET only (§24.2)
    }
    throw err;
  }
}

// ------------------------------------------------------------------ fixtures + upstream

export interface ScenarioSummary {
  id: string; title: string; channel: string; "class": "ATTACK" | "LEGIT";
  decision: string; hero: number | null; risk_score: number; intent_confidence: number;
  amount_display: string;
}

async function fetchJson(url: string): Promise<unknown> {
  const res = await fetch(url);
  if (!res.ok) throw { code: "HTTP_", detail: `HTTP ${res.status}` } as ApiError;
  return res.json();
}

/** All 22 scenario summaries from the fixture index (static, always available). */
export async function listScenarios(): Promise<ScenarioSummary[]> {
  const idx = await fetchJson("/golden/index.json") as { scenarios: ScenarioSummary[] };
  return idx.scenarios;
}

/**
 * One scenario envelope. Tries the live services first (A for samples, B for assess);
 * falls back to `contracts/golden/` with a visible "cached fixture" badge — never a blank
 * screen in front of a judge (00_SHARED_CONTEXT §14).
 */
export async function loadScenario(id: string): Promise<{ data: ScenarioEnvelope; source: "live" | "fixture" }> {
  try {
    const a = await call<ScenarioEnvelope>("GET", `${SIGNAL_URL}/v1/samples/${id}`, undefined, { retry: false });
    if (a?.assessment) return { data: a, source: "live" };
  } catch { /* fall through to fixtures */ }
  const data = await fetchJson(`/golden/${id}.json`) as ScenarioEnvelope;
  return { data, source: "fixture" };
}

// --------------------------------------------------------------------------- the chain

export const audit = {
  head: () =>
    call<{ seq: number; record_hash: string; record_count: number; verified_at: string }>(
      "GET", `${AUDIT_URL}/v1/audit/head`),
  verify: () => call<VerifyResult>("GET", `${AUDIT_URL}/v1/audit/verify`),
  records: (params: { transaction_id?: string; event_type?: string; limit?: number; order?: "asc" | "desc" } = {}) => {
    const q = new URLSearchParams();
    if (params.transaction_id) q.set("transaction_id", params.transaction_id);
    if (params.event_type) q.set("event_type", params.event_type);
    q.set("limit", String(params.limit ?? 200));
    if (params.order) q.set("order", params.order);
    return call<{ count: number; limit: number; truncated: boolean; records: AuditRecord[] }>(
      "GET", `${AUDIT_URL}/v1/audit/records?${q}`);
  },
  append: (body: { event_type: string; actor: string; payload: Record<string, unknown>; transaction_id?: string }) =>
    call<{ seq: number; record_id: string; record_hash: string; prev_hash: string }>(
      "POST", `${AUDIT_URL}/v1/audit/append`, body),
  ask: (question: string) => call<AskResult>("POST", `${AUDIT_URL}/v1/audit/ask`, { question }),
  tamper: (seq: number, field: string, value: unknown) =>
    call<{ seq: number; field: string; stored_record_hash: string; warning: string }>(
      "POST", `${AUDIT_URL}/v1/audit/_tamper`, { seq, field, value }),
  health: () => call<HealthResult>("GET", `${AUDIT_URL}/v1/health`),
};

export const bench = {
  run: (live = false) => call<BenchReport>("POST", `${AUDIT_URL}/v1/bench/run?live=${live}`),
  latest: () => fetchJson("/bench_latest.json") as Promise<BenchReport | null>,
};

export const canary = {
  run: () => call<CanaryRun>("POST", `${AUDIT_URL}/v1/canary/run`),
  history: () => call<CanaryHistory>("GET", `${AUDIT_URL}/v1/canary/history`),
};

// ------------------------------------------------------- live-upstream endpoints (Team B)

export const core = {
  mode: (mode: "FULL" | "NO_LLM" | "MINIMAL") =>
    call<{ mode: string }>("POST", `${CORE_URL}/v1/mode`, { mode }),
  breaker: () => call<{ state: string; opened_at?: string; trial_at?: string }>(
    "GET", `${CORE_URL}/v1/breaker/state`),
  enrol: (body: { device_id: string; executive_id: string; public_key_spki_b64u: string; label?: string }) =>
    call<{ device_id: string; thumbprint: string; enrolled_at: string }>(
      "POST", `${CORE_URL}/v1/device/enrol`, body),
  verifySignature: (body: { device_id: string; fingerprint: string; signature_b64u: string }) =>
    call<{ verdict: string; detail: string; field_deltas?: Array<{ field: string; expected: string; presented: string; severity: string }> }>(
      "POST", `${CORE_URL}/v1/signature/verify`, body),
};
