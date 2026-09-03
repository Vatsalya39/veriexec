/**
 * `screens/CanaryPanel.tsx` — the canary strip. `[NOVEL-N4]` §18
 *
 * "The system tests itself every hour and tells you when it has stopped working. Most
 * fraud controls fail silently." A strip of the last 24 pass/fail ticks, the current
 * streak, a Run button for the stage beat, and the red integrity banner when one fails.
 */

import { useState } from "react";
import { canary } from "../api/client";
import type { CanaryHistory } from "../api/types";
import { ErrorPane, Loading } from "../components/ui";
import { usePoll } from "../state/hooks";

export function CanaryPanel() {
  const { value, error, refresh } = usePoll(() => canary.history(), 30_000);
  const [running, setRunning] = useState(false);
  const [lastRun, setLastRun] = useState<string | null>(null);

  const run = async () => {
    setRunning(true);
    try {
      const result = await canary.run();
      setLastRun(`${result.passed ? "✓ passed" : `✗ FAILED — expected ${result.expected}, got ${result.actual}`} · variant ${result.variant} · risk ${result.risk_score}`);
      refresh();
    } catch {
      setLastRun("Could not reach the canary endpoint — the integrity check is unverified, not passed.");
    } finally {
      setRunning(false);
    }
  };

  if (error && !value) return <ErrorPane error={error} retry={refresh} />;
  if (!value) return <Loading label="Loading canary history" />;

  const h: CanaryHistory = value;
  return (
    <div className="card" data-testid="canary">
      <div className="spread">
        <div>
          <div className="smallcaps">Canary integrity · N4</div>
          <h2 style={{ margin: 0 }}>The system tests itself</h2>
        </div>
        <div className="row">
          <span className={"chip " + (h.streak > 0 ? "approve" : "neutral")}>
            streak {h.streak} · {h.total} total
          </span>
          <button className="primary" onClick={() => void run()} disabled={running}>
            {running ? "Injecting…" : "Inject one canary now"}
          </button>
        </div>
      </div>

      {h.banner && (
        <div className="chain-banner broken" role="alert" style={{ marginTop: 10, borderRadius: 8 }}>
          <span aria-hidden>⛔</span> {h.banner.message}
        </div>
      )}

      <div className="row" style={{ marginTop: 10, flexWrap: "wrap" }} aria-label="Last 24 canary results">
        {h.runs.length === 0 && (
          <span className="xs" style={{ color: "var(--faint)" }}>
            No canaries yet — not run is reported as not run, never as a fake pass.
          </span>
        )}
        {h.runs.map((r) => (
          <span key={r.canary_id} title={`${r.ran_at} · variant ${r.variant} · risk ${r.risk_score}`}
                className={"chip " + (r.passed ? "approve" : "block")}
                style={{ padding: "1px 6px" }} aria-label={`${r.canary_id}: ${r.passed ? "passed" : "failed"}`}>
            {r.passed ? "✓" : "✗"}
          </span>
        ))}
      </div>

      {lastRun && <div className="sm mono" style={{ marginTop: 8 }}>{lastRun}</div>}

      <div className="xs" style={{ color: "var(--faint)", marginTop: 8 }}>
        A synthetic transaction with a known attack shape, expected BLOCK, injected at intervals.
        A canary that returns anything else is a detector regression. Canary runs never affect the
        benchmark metrics or breaker counts.
      </div>
    </div>
  );
}
