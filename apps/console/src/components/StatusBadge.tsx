/**
 * `components/StatusBadge.tsx` — one vocabulary for the four run states.
 *
 * `PENDING · RUNNING · COMPLETED · FAILED`, rendered identically in the phase monitor, the
 * part cards and the task rows, because a state that looks different in two places reads
 * as two different states. Colour is never the only channel: every state carries a glyph
 * and a word, so the screen survives a projector and a colour-blind reviewer (§23).
 */

import type { RunStatus, StepStatus } from "../workflow/contract";

export const STATUS_LABEL: Record<StepStatus, string> = {
  PENDING: "Pending",
  RUNNING: "Running",
  COMPLETED: "Completed",
  FAILED: "Failed",
};

export const RUN_LABEL: Record<RunStatus, string> = {
  IDLE: "Idle",
  RUNNING: "Running",
  COMPLETED: "Completed",
  FAILED: "Failed",
  CANCELLED: "Stopped",
};

/** The chip tone each state borrows from the four semantic colours. */
const CHIP_TONE: Record<StepStatus, string> = {
  PENDING: "neutral",
  RUNNING: "system",
  COMPLETED: "approve",
  FAILED: "block",
};

const RUN_TONE: Record<RunStatus, string> = {
  IDLE: "neutral",
  RUNNING: "system",
  COMPLETED: "approve",
  FAILED: "block",
  CANCELLED: "challenge",
};

/**
 * The state glyph: a ring holding a tick, a cross, a spinner or nothing. `PENDING` is an
 * empty ring on purpose — an icon for "has not happened" invites the reader to think
 * something did.
 */
export function StatusIcon({ status }: { status: StepStatus }) {
  return (
    <span className="state-ring" data-status={status} aria-hidden>
      {status === "COMPLETED" ? "✓"
        : status === "FAILED" ? "✕"
          : status === "RUNNING" ? <Spinner />
            : ""}
    </span>
  );
}

/** The one indeterminate indicator in the product: a 900 ms arc, no bounce, no trail. */
function Spinner() {
  return (
    <svg className="spin" width="12" height="12" viewBox="0 0 24 24" aria-hidden>
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="3"
              strokeLinecap="round" strokeDasharray="42 14" opacity="0.9" />
    </svg>
  );
}

export function StatusChip({ status }: { status: StepStatus }) {
  return (
    <span className={`chip ${CHIP_TONE[status]}`} data-status={status}>
      {status === "RUNNING" && <span className="state-dot pulse" style={{ marginRight: 5 }} aria-hidden />}
      {STATUS_LABEL[status]}
    </span>
  );
}

export function RunStatusChip({ status }: { status: RunStatus }) {
  return (
    <span className={`chip ${RUN_TONE[status]}`} data-status={status} data-testid="run-status">
      {status === "RUNNING" && <span className="state-dot pulse" style={{ marginRight: 5 }} aria-hidden />}
      {RUN_LABEL[status]}
    </span>
  );
}
