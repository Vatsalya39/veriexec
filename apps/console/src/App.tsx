/**
 * The app shell: hash-based navigation (no router dependency — one less thing to break
 * on venue wifi) inside a collapsible rail that doubles as the workflow phase monitor, the
 * breaker banner above it from a single poll, and the screens themselves. `/desk` exists
 * behind the demo role selector and is deliberately not in the main nav's face (§12.2).
 *
 * The verification run lives here rather than in the pipeline screen because two surfaces
 * watch it — the rail's phase monitor and the pipeline itself. One run, two views.
 */

import { useCallback, useEffect, useState } from "react";
import * as api from "./api/client";
import type { ScenarioEnvelope } from "./api/types";
import { usePoll } from "./state/hooks";
import { useVerification } from "./state/useVerification";
import { AppShell, type ShellRoute } from "./components/AppShell";
import { BreakerBanner } from "./panels/Temporal";
import { PipelineScreen } from "./screens/Pipeline";
import { VerifyScreen } from "./screens/Verify";
import { ChallengeScreen } from "./screens/Challenge";
import { DeviceScreen } from "./screens/Device";
import { SandboxScreen } from "./screens/Sandbox";
import { BenchmarkScreen } from "./screens/Benchmark";
import { AuditScreen } from "./screens/Audit";
import { TimelineScreen } from "./screens/Timeline";
import { DeskScreen } from "./screens/Desk";
import { KillSwitchScreen } from "./screens/KillSwitch";

type Route =
  | "pipeline" | "verify" | "challenge" | "device" | "sandbox"
  | "benchmark" | "audit" | "timeline" | "desk" | "killswitch";

const ROUTES: ReadonlyArray<ShellRoute & { id: Route }> = [
  { id: "pipeline", label: "Pipeline", hint: "Run a verification end to end and watch each part report." },
  { id: "verify", label: "Verify", hint: "The decision, its two numbers and the evidence behind them." },
  { id: "challenge", label: "Challenge", hint: "The out-of-band step a challenged transaction must clear." },
  { id: "device", label: "Device", hint: "Device posture and the bindings that vouch for it." },
  { id: "sandbox", label: "Sandbox", hint: "Change one input and watch the decision move." },
  { id: "benchmark", label: "Benchmark", hint: "The threshold sweep across all 22 frozen scenarios." },
  { id: "audit", label: "Audit", hint: "The hash chain, verified from genesis on every load." },
  { id: "timeline", label: "Timeline", hint: "Where the milliseconds went, stage by stage." },
  { id: "killswitch", label: "Kill switch", hint: "Organization-wide hold, and what it does to a decision." },
];

function currentRoute(): Route {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const known = ROUTES.find((r) => r.id === hash) ?? (hash === "desk" ? { id: "desk" as Route } : null);
  return known?.id ?? "pipeline";
}

export function App() {
  const [route, setRoute] = useState<Route>(currentRoute());
  const [scenarioId, setScenarioId] = useState<string | null>("S06");
  const [envelope, setEnvelope] = useState<ScenarioEnvelope | null>(null);
  /** Which part the reader scoped to. Shared by the rail, the visualizer and the console. */
  const [activeStepId, setActiveStepId] = useState<string | null>(null);

  const verification = useVerification(scenarioId);

  useEffect(() => {
    const onHash = () => setRoute(currentRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // The active envelope follows the scenario id so Challenge/Device/Timeline/Desk/Kill
  // all render the same transaction the Verify screen just loaded.
  useEffect(() => {
    if (!scenarioId) { setEnvelope(null); return; }
    void api.loadScenario(scenarioId).then((r) => setEnvelope(r.data)).catch(() => setEnvelope(null));
  }, [scenarioId]);

  // One poll for the org-level breaker state, every 5 s, so it cannot go stale mid-demo.
  const breaker = usePoll(() => api.core.breaker().catch(() => ({ state: "CLOSED" })), 5_000);

  const go = (id: string) => { window.location.hash = `/${id}`; setRoute(currentRoute()); };

  /** One scenario for the whole console: picking on any screen resets the run too. */
  const selectScenario = verification.selectScenario;
  const pickScenario = useCallback((id: string) => {
    setScenarioId(id);
    selectScenario(id);
  }, [selectScenario]);

  return (
    <div className="app">
      <BreakerBanner state={breaker.value?.state ?? "CLOSED"} />

      <AppShell routes={ROUTES} activeRoute={route} snapshot={verification.snapshot}
                activeStepId={activeStepId} onSelectStep={setActiveStepId}
                topbarRight={
                  <a href="#/desk" className="xs" style={{ color: "var(--faint)" }}
                     title="Behind the demo role selector — a selected identity, not an authenticated one">
                    Desk (acting as)
                  </a>
                }>
        {route === "pipeline" && (
          <PipelineScreen verification={verification} activeStepId={activeStepId}
                          onSelectStep={setActiveStepId} onSelectScenario={pickScenario} />
        )}
        {route === "verify" && <VerifyScreen scenarioId={scenarioId} onScenarioChange={(id) => { pickScenario(id); setRoute("verify"); }} />}
        {route === "challenge" && (envelope
          ? <ChallengeScreen envelope={envelope} onOutcome={() => go("device")} />
          : <Empty hint="Load a scenario on Verify first." />)}
        {route === "device" && <DeviceScreen envelope={envelope} />}
        {route === "sandbox" && <SandboxScreen />}
        {route === "benchmark" && <BenchmarkScreen />}
        {route === "audit" && <AuditScreen />}
        {route === "timeline" && <TimelineScreen envelope={envelope} />}
        {route === "desk" && <DeskScreen envelope={envelope} />}
        {route === "killswitch" && <KillSwitchScreen envelope={envelope} />}
      </AppShell>

      <footer className="chain-footer">
        <span className="smallcaps">INTENTLOCK</span>
        <span className="xs" style={{ color: "var(--faint)" }}>
          Every number on this screen is clickable down to the raw evidence, and every record in
          the log is provable.
        </span>
        <span className="grow" />
        <span className="xs mono" style={{ color: "var(--faint)" }}>console :5173 · audit :8003</span>
      </footer>
    </div>
  );
}

function Empty({ hint }: { hint: string }) {
  return <div className="screen"><div className="card"><span className="sm" style={{ color: "var(--faint)" }}>{hint}</span></div></div>;
}
