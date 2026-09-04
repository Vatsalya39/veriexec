/**
 * `panels/PhaseMonitor.tsx` — the rail's second job. The same three parts the visualizer
 * draws, reduced to one row each, so the reader always knows which phase the run is in
 * even when the pipeline screen is scrolled away or another screen is open.
 *
 * Clicking a row scopes the console to that part; it is the same `activeStepId` the
 * visualizer and the console filter chips write, so the three stay in agreement. When the
 * rail collapses the rows collapse with it, down to the state glyph — the one piece of
 * information that still reads at 60 px.
 */

import { STATUS_LABEL, StatusIcon } from "../components/StatusBadge";
import { formatDuration } from "../api/format";
import type { StepStatus, WorkflowSnapshot, WorkflowStep } from "../workflow/contract";

const METER_COLOR: Record<StepStatus, string> = {
  PENDING: "var(--neutral)",
  RUNNING: "hsl(var(--primary))",
  COMPLETED: "var(--approve)",
  FAILED: "var(--block)",
};

function rowTitle(step: WorkflowStep, active: boolean): string {
  const state = `${step.title} — ${step.name}: ${STATUS_LABEL[step.status]}`;
  return active ? `${state}. Click to show every part.` : `${state}. Click to scope the console.`;
}

function PhaseRow({ step, active, onSelect }: {
  step: WorkflowStep;
  active: boolean;
  onSelect?: (stepId: string | null) => void;
}) {
  const done = step.tasks.filter((t) => t.status === "COMPLETED").length;
  const took = step.durationMs !== null && step.durationMs > 0 ? formatDuration(step.durationMs) : null;

  return (
    <button type="button" className="phase-row focus-ring" data-status={step.status}
            data-testid={`phase-row-${step.id}`} aria-pressed={active}
            title={rowTitle(step, active)}
            onClick={() => onSelect?.(active ? null : step.id)}>
      <span className="row" style={{ gap: 8 }}>
        <StatusIcon status={step.status} />
        <span className="rail-label grow" style={{ minWidth: 0 }}>
          <span className="sm" style={{ fontWeight: 600, display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {step.name}
          </span>
          <span className="xs" style={{ color: "var(--faint)" }}>
            {step.title} · {done}/{step.tasks.length}{took ? ` · ${took}` : ""}
          </span>
        </span>
      </span>
      <span className="rail-label meter" aria-hidden
            style={{ height: 4, borderRadius: 2, marginTop: 6, marginLeft: 28 }}>
        <span style={{ width: `${step.progress * 100}%`, background: METER_COLOR[step.status] }} />
      </span>
    </button>
  );
}

export function PhaseMonitor({ snapshot, activeStepId, onSelectStep, collapsed = false }: {
  snapshot: WorkflowSnapshot;
  activeStepId?: string | null;
  onSelectStep?: (stepId: string | null) => void;
  collapsed?: boolean;
}) {
  return (
    <section aria-label="Workflow phase" data-testid="phase-monitor">
      {!collapsed && (
        <div className="row rail-label" style={{ padding: "0 8px 6px" }}>
          <span className="smallcaps grow">Workflow phase</span>
          <span className="mono-xs nums" style={{ color: "var(--faint)" }}>
            {snapshot.currentStep > 0 ? `${snapshot.currentStep}/3` : "—"}
          </span>
        </div>
      )}
      <div className="col" style={{ gap: 2 }}>
        {snapshot.steps.map((step) => (
          <PhaseRow key={step.id} step={step} active={activeStepId === step.id} onSelect={onSelectStep} />
        ))}
      </div>
    </section>
  );
}
