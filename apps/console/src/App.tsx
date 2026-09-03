/**
 * The app shell: hash-based navigation (no router dependency — one less thing to break
 * on venue wifi), the breaker banner above the nav from a single poll, the kill-switch
 * chip top-right, and five screens, no more (§7.2). `/desk` exists behind the demo role
 * selector and is deliberately not in the main nav's face (§12.2).
 */

import { useEffect, useState } from "react";
import * as api from "./api/client";
import type { ScenarioEnvelope } from "./api/types";
import { usePoll } from "./state/hooks";
import { BreakerBanner } from "./panels/Temporal";
import { VerifyScreen } from "./screens/Verify";
import { ChallengeScreen } from "./screens/Challenge";
import { DeviceScreen } from "./screens/Device";
import { SandboxScreen } from "./screens/Sandbox";
import { BenchmarkScreen } from "./screens/Benchmark";
import { AuditScreen } from "./screens/Audit";
import { TimelineScreen } from "./screens/Timeline";
import { DeskScreen } from "./screens/Desk";
import { KillSwitchScreen } from "./screens/KillSwitch";

type Route = "verify" | "challenge" | "device" | "sandbox" | "benchmark" | "audit" | "timeline" | "desk" | "killswitch";

const ROUTES: Array<{ id: Route; label: string }> = [
  { id: "verify", label: "Verify" },
  { id: "challenge", label: "Challenge" },
  { id: "device", label: "Device" },
  { id: "sandbox", label: "Sandbox" },
  { id: "benchmark", label: "Benchmark" },
  { id: "audit", label: "Audit" },
  { id: "timeline", label: "Timeline" },
  { id: "killswitch", label: "Kill switch" },
];

function currentRoute(): Route {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const known = ROUTES.find((r) => r.id === hash) ?? (hash === "desk" ? { id: "desk" as Route } : null);
  return known?.id ?? "verify";
}

export function App() {
  const [route, setRoute] = useState<Route>(currentRoute());
  const [scenarioId, setScenarioId] = useState<string | null>("S06");
  const [envelope, setEnvelope] = useState<ScenarioEnvelope | null>(null);

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

  return (
    <>
      <BreakerBanner state={breaker.value?.state ?? "CLOSED"} />
      <nav className="nav" aria-label="Screens">
        {ROUTES.map((r) => (
          <a key={r.id} href={`#/${r.id}`} className={route === r.id ? "active" : ""}>{r.label}</a>
        ))}
        <span className="grow" />
        <a href="#/desk" className={route === "desk" ? "active" : ""}
           title="Behind the demo role selector — a selected identity, not an authenticated one">
          Desk (acting as)
        </a>
      </nav>

      {route === "verify" && <VerifyScreen scenarioId={scenarioId} onScenarioChange={(id) => { setScenarioId(id); setRoute("verify"); }} />}
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

      <footer className="chain-footer">
        <span className="smallcaps">INTENTLOCK</span>
        <span className="xs" style={{ color: "var(--faint)" }}>
          Every number on this screen is clickable down to the raw evidence, and every record in
          the log is provable.
        </span>
        <span className="grow" />
        <span className="xs mono" style={{ color: "var(--faint)" }}>console :5173 · audit :8003</span>
      </footer>
    </>
  );
}

function Empty({ hint }: { hint: string }) {
  return <div className="screen"><div className="card"><span className="sm" style={{ color: "var(--faint)" }}>{hint}</span></div></div>;
}
