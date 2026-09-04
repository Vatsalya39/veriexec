/**
 * `panels/PipelineVisualizer.tsx` — three part cards, each with its task rows, each row in
 * exactly one of the four states.
 *
 * Every value comes from the snapshot. There is no local state, no timer and no simulation
 * in this file, which is what lets the same component render a replayed fixture and a live
 * run without changes. Delete `workflow/mockEngine.ts` and this file does not notice.
 */

import { formatDuration } from "../api/format";
import { StatusChip, StatusIcon } from "../components/StatusBadge";
import type { StepStatus, WorkflowSnapshot, WorkflowStep, WorkflowTask } from "../workflow/contract";

const METER_COLOR: Record<StepStatus, string> = {
  PENDING: "var(--neutral)",
  RUNNING: "hsl(var(--primary))",
  COMPLETED: "var(--approve)",
  FAILED: "var(--block)",
};

function TaskRow({ task, stepStatus }: { task: WorkflowTask; stepStatus: StepStatus }) {
  // A part can legitimately finish without exercising every task — a sandbox envelope
  // carries no timeline for some stages. Saying so is more honest than a tick.
  const skipped = task.status === "PENDING" && !task.visited && stepStatus === "COMPLETED";
  const took = task.durationMs !== null && task.durationMs > 0 ? formatDuration(task.durationMs) : null;

  return (
    <li className="task" data-task={task.id} data-status={task.status}>
      <div className="row" style={{ gap: 8 }}>
        <StatusIcon status={task.status} />
        <span className="task-title grow" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {task.title}
        </span>
        {skipped && <span className="xs smallcaps" style={{ color: "var(--faint)" }}>not exercised</span>}
        {took && <span className="mono-xs nums" style={{ color: "var(--faint)", flexShrink: 0 }}>{took}</span>}
      </div>
      <p className="task-detail">{task.detail ?? task.hint}</p>
    </li>
  );
}

function PartCard({
  step, active, onSelect, onRetry,
}: {
  step: WorkflowStep;
  active: boolean;
  onSelect?: (stepId: string | null) => void;
  onRetry?: () => void;
}) {
  const done = step.tasks.filter((t) => t.status === "COMPLETED").length;
  const took = step.durationMs !== null && step.durationMs > 0 ? formatDuration(step.durationMs) : null;

  return (
    <article className="part" data-testid={`part-card-${step.id}`} data-status={step.status}
             data-active={active} aria-busy={step.status === "RUNNING"}>
      <header className="part-head">
        <div className="row">
          <span className="state-ring" data-status={step.status} aria-hidden>{step.index}</span>
          <button type="button" className="filter-chip grow" style={{ textAlign: "left" }}
                  onClick={() => onSelect?.(active ? null : step.id)} aria-pressed={active}
                  title={active ? "Show every part in the console" : `Scope the console to ${step.title}`}>
            {step.title}
          </button>
          <StatusChip status={step.status} />
        </div>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, letterSpacing: "-0.005em" }}>{step.name}</h3>
        <p className="xs" style={{ margin: 0, color: "var(--faint)" }}>{step.summary}</p>
        <div className="row" style={{ gap: 8 }}>
          <div className="meter grow" role="meter" aria-valuemin={0} aria-valuemax={100}
               aria-valuenow={Math.round(step.progress * 100)} aria-label={`${step.title} progress`}>
            <span style={{ width: `${step.progress * 100}%`, background: METER_COLOR[step.status] }} />
          </div>
          <span className="mono-xs nums" style={{ color: "var(--faint)", flexShrink: 0 }}>
            {done}/{step.tasks.length}{took ? ` · ${took}` : ""}
          </span>
        </div>
      </header>

      <ul className="part-tasks">
        {step.tasks.map((task) => <TaskRow key={task.id} task={task} stepStatus={step.status} />)}
      </ul>

      {step.status === "FAILED" && (
        <footer className="part-fail">
          <p className="xs grow" style={{ margin: 0, color: "var(--block)" }}>{step.error}</p>
          {onRetry && <button className="xs" onClick={onRetry} style={{ flexShrink: 0 }}>Retry</button>}
        </footer>
      )}
    </article>
  );
}

export function PipelineVisualizer({
  snapshot, activeStepId, onSelectStep, onRetry,
}: {
  snapshot: WorkflowSnapshot;
  activeStepId?: string | null;
  onSelectStep?: (stepId: string | null) => void;
  onRetry?: () => void;
}) {
  return (
    <div className="parts" data-testid="pipeline-visualizer" data-current-step={snapshot.currentStep}>
      {snapshot.steps.map((step, i) => (
        <div key={step.id} className="row" style={{ flex: 1, minWidth: 0, alignItems: "stretch", gap: 8 }}>
          <PartCard step={step} active={activeStepId === step.id} onSelect={onSelectStep}
                    onRetry={step.status === "FAILED" ? onRetry : undefined} />
          {i < snapshot.steps.length - 1 && (
            <div className="part-arrow" aria-hidden
                 style={{ opacity: snapshot.currentStep > step.index ? 1 : 0.4 }}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 6l6 6-6 6" />
              </svg>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
