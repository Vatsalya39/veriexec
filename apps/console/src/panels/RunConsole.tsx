/**
 * `panels/RunConsole.tsx` — the live output console. One line per event, in the order the
 * run produced them, with the owning part called out so a reader can follow a single part
 * or the whole run.
 *
 * Everything shown comes from `snapshot.logs`. The only state this file owns is
 * presentational — whether the view is pinned to the tail, and whether the last copy
 * succeeded — and the part filter is the same `activeStepId` the visualizer and the rail
 * use, so scoping anywhere scopes everywhere.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { formatClock } from "../api/format";
import type { WorkflowLog, WorkflowSnapshot } from "../workflow/contract";

const PART_TOKEN: Record<string, string> = { part1: "P1", part2: "P2", part3: "P3" };

function textLine(log: WorkflowLog): string {
  return `[${formatClock(log.ts)}] ${PART_TOKEN[log.step] ?? log.step} ${log.label} — ${log.message}`;
}

function ConsoleRow({ log, scoped }: { log: WorkflowLog; scoped: boolean }) {
  // Attempt dividers carry a negative sequence: they are the one line the run did not
  // emit, so they read as a rule rather than as output.
  if (log.seq < 0) {
    return (
      <li className="log-divider" data-attempt={log.attempt}>
        <span className="bar" aria-hidden />
        <span className="chip challenge">{log.message}</span>
        <span className="bar" aria-hidden />
      </li>
    );
  }

  return (
    <li className="log fade-in" data-step={log.step} data-level={log.level} data-scoped={scoped}>
      <span className="log-time">{formatClock(log.ts)}</span>
      <span className="log-part">{PART_TOKEN[log.step] ?? log.step}</span>
      <span className="log-body">
        <span className="log-label">{log.label}</span>{" "}
        <span className="log-msg">{log.message}</span>
      </span>
    </li>
  );
}

function FilterChip({ label, active, onClick, title }: {
  label: string; active: boolean; onClick: () => void; title: string;
}) {
  return (
    <button type="button" className="filter-chip" onClick={onClick} aria-pressed={active} title={title}>
      {label}
    </button>
  );
}

export function RunConsole({ snapshot, activeStepId, onSelectStep }: {
  snapshot: WorkflowSnapshot;
  activeStepId?: string | null;
  onSelectStep?: (stepId: string | null) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  /** Follow the tail until the reader scrolls away from it. */
  const [pinned, setPinned] = useState(true);
  const [copied, setCopied] = useState(false);

  const visible = useMemo(
    () => (activeStepId
      ? snapshot.logs.filter((l) => l.step === activeStepId || l.seq < 0)
      : snapshot.logs),
    [snapshot.logs, activeStepId],
  );

  useEffect(() => {
    if (!pinned) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [visible.length, pinned]);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1400);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    // A small tolerance: sub-pixel scroll heights otherwise unpin the view on their own
    // the moment a row is appended.
    setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 24);
  };

  const onCopy = () => {
    void navigator.clipboard?.writeText(visible.map(textLine).join("\n"))
      .then(() => setCopied(true)).catch(() => setCopied(false));
  };

  return (
    <section className="console grow" aria-label="Run output" data-testid="run-console">
      <div className="console-head">
        <span className="smallcaps">Live output</span>
        <span className="mono-xs nums" style={{ color: "var(--faint)" }}>
          {visible.length}{activeStepId ? ` / ${snapshot.logs.length}` : ""} line{visible.length === 1 ? "" : "s"}
        </span>
        <span className="grow" />
        <FilterChip label="ALL" active={!activeStepId} onClick={() => onSelectStep?.(null)}
                    title="Show every part" />
        {snapshot.steps.map((step) => (
          <FilterChip key={step.id} label={PART_TOKEN[step.id] ?? step.id}
                      active={activeStepId === step.id}
                      onClick={() => onSelectStep?.(activeStepId === step.id ? null : step.id)}
                      title={`${step.title} — ${step.name}`} />
        ))}
        <button className="xs" onClick={onCopy} disabled={visible.length === 0}
                title="Copy the visible output">
          {copied ? "✓ copied" : "Copy"}
        </button>
      </div>

      <div style={{ position: "relative", minHeight: 0, flex: 1, display: "flex" }}>
        <div ref={scrollRef} onScroll={onScroll} className="console-scroll" data-testid="run-console-scroll">
          {visible.length === 0 ? (
            <div className="col" style={{ alignItems: "center", justifyContent: "center", height: "100%", padding: 24 }}>
              <span className="sm" style={{ color: "var(--faint)", textAlign: "center", maxWidth: 380 }}>
                {snapshot.status === "IDLE"
                  ? "No output yet. Run the verification to watch each part report as it executes."
                  : "Nothing from this part yet."}
              </span>
            </div>
          ) : (
            <ol className="console-lines">
              {visible.map((log) => (
                <ConsoleRow key={log.id} log={log} scoped={activeStepId === log.step} />
              ))}
            </ol>
          )}
        </div>
        {!pinned && visible.length > 0 && (
          <button className="xs" onClick={() => setPinned(true)}
                  style={{ position: "absolute", bottom: 8, right: 12, boxShadow: "var(--shadow-2)" }}>
            ↓ Latest
          </button>
        )}
      </div>
    </section>
  );
}
