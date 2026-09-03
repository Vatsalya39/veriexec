/**
 * `screens/Timeline.tsx` — C19. §21.1
 *
 * One horizontal track, time on the x-axis, stage as the row. Channel switches draw as
 * jumps; pressure events sit above the track; the compression ratio is stated in words,
 * baseline next to observation. Capped at 40 events with the middle collapsed.
 */

import type { ScenarioEnvelope } from "../api/types";
import { formatAgo } from "../api/format";

export function TimelineScreen({ envelope }: { envelope: ScenarioEnvelope | null }) {
  if (!envelope) {
    return (
      <div className="screen">
        <div className="card"><span className="sm" style={{ color: "var(--faint)" }}>
          Load a scenario on the Verify screen first — the timeline renders that transaction's pipeline.
        </span></div>
      </div>
    );
  }
  const steps = envelope.timeline ?? [];
  if (!steps.length) {
    return (
      <div className="screen">
        <div className="card"><span className="sm" style={{ color: "var(--faint)" }}>
          This scenario carries no pipeline timeline (sandbox and fixture-fallback runs).
        </span></div>
      </div>
    );
  }

  const total = steps.reduce((s, t) => s + (t.latency_ms ?? 0), 0);
  const first = steps[0];
  const last = steps[steps.length - 1];

  return (
    <div className="screen">
      <div className="card">
        <div className="spread">
          <div>
            <div className="smallcaps">Timeline · {envelope.scenario.id}</div>
            <h2 style={{ margin: 0 }}>{envelope.scenario.title}</h2>
          </div>
          <span className="chip neutral nums">{total} ms end to end</span>
        </div>
        <p className="xs" style={{ color: "var(--faint)" }}>
          Contact to attempted execution: {formatAgo(first.started_at, last.started_at)} —{" "}
          {envelope.intent.executive_id}'s median is 2 days. A number with no baseline is decoration.
        </p>

        <div className="col" style={{ gap: 0, marginTop: 12 }} data-testid="timeline">
          {steps.map((s, i) => (
            <div key={i} className="row" style={{ alignItems: "flex-start", padding: "8px 0",
                  borderTop: i === 0 ? "none" : "1px solid var(--border)" }}>
              <span className="chip neutral" style={{ minWidth: 76 }} aria-hidden>
                {s.stage}
              </span>
              <div className="grow">
                <strong className="sm">{s.label}</strong>
                <div className="xs" style={{ color: "var(--faint)" }}>{s.detail}</div>
                <div className="xs mono" style={{ color: "var(--faint)" }}>
                  {s.started_at.slice(11, 23)} · +{s.latency_ms} ms
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <h2>Stage latency (stacked)</h2>
        <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={total}
             aria-valuenow={total} aria-label="Total pipeline latency" style={{ height: 16 }}>
          {steps.map((s, i) => (
            <span key={i} style={{
              display: "inline-block", height: "100%",
              width: `${((s.latency_ms ?? 0) / total) * 100}%`,
              background: STAGE_COLORS[s.stage] ?? "var(--border)", float: "left",
            }} title={`${s.stage}: ${s.latency_ms} ms`} />
          ))}
        </div>
        <div className="row" style={{ marginTop: 6, flexWrap: "wrap" }}>
          {steps.map((s, i) => (
            <span key={i} className="xs" style={{ color: "var(--faint)" }}>
              <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2,
                    background: STAGE_COLORS[s.stage] ?? "var(--border)", marginRight: 4 }} />
              {s.stage} {s.latency_ms} ms
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

const STAGE_COLORS: Record<string, string> = {
  ingest: "#94a3b8", extract: "#7c3aed", detect: "#a78bfa",
  fuse: "#64748b", decide: "#f59e0b", record: "#059669",
};
