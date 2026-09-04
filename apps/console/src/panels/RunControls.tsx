/**
 * `panels/RunControls.tsx` — the strip above the pipeline: pick a scenario, run it, watch
 * the clock, stop or retry.
 *
 * The buttons call the actions `useVerification` handed down and nothing else. This file
 * does not know how long a stage takes, what a fault is, or whether the run is a replay or
 * a live core call — it renders the labels the service reports and the state the snapshot
 * derives.
 */

import { formatDuration } from "../api/format";
import { RunStatusChip } from "../components/StatusBadge";
import type { ScenarioSummary } from "../api/client";
import type { WorkflowSnapshot } from "../workflow/contract";
import { FAULT_OPTIONS, SPEED_OPTIONS } from "../state/useVerification";
import type { FaultPoint } from "../workflow/verificationService";

/** The one place the two clocks are named side by side, so neither can be mistaken for
 *  the other: `wall` is how long the replay took, `engine` is the fixture's measurement. */
function Clocks({ elapsedMs, measuredMs }: { elapsedMs: number; measuredMs: number | null }) {
  return (
    <div className="row" style={{ gap: 12 }}>
      <span className="col" style={{ gap: 0 }}>
        <span className="smallcaps">Wall</span>
        <span className="mono-xs nums figure">{formatDuration(elapsedMs)}</span>
      </span>
      <span className="hairline" style={{ width: 1, height: 22 }} aria-hidden />
      <span className="col" style={{ gap: 0 }}
            title="The latency the engine actually measured, copied from the run envelope. The replay is deliberately slower so it can be read.">
        <span className="smallcaps">Engine</span>
        <span className="mono-xs nums figure">{measuredMs === null ? "—" : formatDuration(measuredMs)}</span>
      </span>
    </div>
  );
}

export function RunControls({
  snapshot, scenarios, scenarioId, onSelectScenario,
  speed, onSpeed, fault, onFault,
  elapsedMs, measuredMs, mode, source,
  canRun, canCancel, canRetry, busy,
  onRun, onCancel, onRetry, onReset,
}: {
  snapshot: WorkflowSnapshot;
  scenarios: ScenarioSummary[];
  scenarioId: string | null;
  onSelectScenario: (id: string) => void;
  speed: string;
  onSpeed: (value: string) => void;
  fault: FaultPoint;
  onFault: (value: FaultPoint) => void;
  elapsedMs: number;
  measuredMs: number | null;
  mode: string;
  source: "fixture" | "live" | null;
  canRun: boolean;
  canCancel: boolean;
  canRetry: boolean;
  busy: boolean;
  onRun: () => void;
  onCancel: () => void;
  onRetry: () => void;
  onReset: () => void;
}) {
  const active = scenarios.find((s) => s.id === scenarioId) ?? null;
  const live = snapshot.status === "RUNNING";

  return (
    <section className="card" data-testid="run-controls" style={{ padding: 12 }}>
      <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
        <label className="sm row" htmlFor="run-scenario" style={{ gap: 6 }}>
          <span className="smallcaps">Scenario</span>
          <select id="run-scenario" value={scenarioId ?? ""} disabled={live}
                  onChange={(e) => onSelectScenario(e.target.value)}>
            <option value="" disabled>Pick a scenario…</option>
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.id} — {s.title}{s.hero ? " ★" : ""} [{s.class}]
              </option>
            ))}
          </select>
        </label>

        <button className="primary" onClick={onRun} disabled={!canRun} data-testid="run-button">
          {busy && !live ? "Starting…" : snapshot.status === "IDLE" ? "Run verification" : "Run again"}
        </button>
        {canCancel && <button onClick={onCancel} data-testid="cancel-button">Stop</button>}
        {canRetry && <button className="primary" onClick={onRetry} data-testid="retry-button">Retry</button>}
        {!live && snapshot.status !== "IDLE" && (
          <button className="ghost" onClick={onReset} title="Clear the run and start from idle">Clear</button>
        )}

        <span className="grow" />
        <Clocks elapsedMs={elapsedMs} measuredMs={measuredMs} />
        <RunStatusChip status={snapshot.status} />
      </div>

      <div className="row inset-strip" style={{ flexWrap: "wrap", gap: 8, marginTop: 10, padding: 8, borderRadius: "var(--r-md)" }}>
        <label className="xs row" htmlFor="run-speed" style={{ gap: 6 }}>
          <span className="smallcaps">Replay speed</span>
          <select id="run-speed" value={speed} onChange={(e) => onSpeed(e.target.value)}>
            {SPEED_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
        <label className="xs row" htmlFor="run-fault" style={{ gap: 6 }}>
          <span className="smallcaps">Fault injection</span>
          <select id="run-fault" value={fault} disabled={live}
                  onChange={(e) => onFault(e.target.value as FaultPoint)}>
            {FAULT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
        <span className="grow" />
        {active && (
          <span className="xs" style={{ color: "var(--faint)" }}>
            {active.amount_display} · expected {active.decision}
          </span>
        )}
        <span className="chip neutral" title="Replay drives the pipeline from the run envelope; live drives it from the core service.">
          {mode}
        </span>
        {source && (
          <span className={`chip ${source === "live" ? "system" : "neutral"}`}
                title={source === "live" ? "Envelope resolved from the running service." : "Envelope resolved from the frozen golden fixture."}>
            {source === "live" ? "live envelope" : "cached fixture"}
          </span>
        )}
      </div>
    </section>
  );
}
