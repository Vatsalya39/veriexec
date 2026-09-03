/**
 * `screens/Benchmark.tsx` â€” the benchmark screen. `[NOVEL-N13]` Â§17 [NEVER CUT]
 *
 * All five organizer metrics with raw fractions beside the percentages, the 3Ã—3
 * confusion matrix, the threshold sweep with the chosen point annotated, and the honesty
 * line ON the screen â€” "22 scenarios, authored by us. Treat as a smoke test, not an
 * evaluation." Judges have seen inflated metrics all day; the team that discounts its own
 * numbers is the one they believe.
 *
 * Charts are inline SVG (Recharts-class output, no dependency, no CDN font â€” venue wifi
 * is the single most common cause of a failed hackathon demo).
 */

import { useState } from "react";
import { useBench } from "../state/hooks";
import type { BenchReport } from "../api/types";
import { ErrorPane, Loading } from "../components/ui";
import { CanaryPanel } from "./CanaryPanel";

export function BenchmarkScreen() {
  const [live, setLive] = useState(false);
  const { load, run } = useBench(live);
  const [sweep] = useState<{ threshold: number; detection: number | null; fp: number | null }[] | null>(null);

  return (
    <div className="screen">
      <div className="card">
        <div className="spread">
          <div>
            <div className="smallcaps">Benchmark Â· N13</div>
            <h2 style={{ margin: 0 }}>Twenty-two scenarios, five metrics, the denominators visible</h2>
          </div>
          <div className="row">
            <span className={"chip " + (live ? "system" : "neutral")}>{live ? "live :8002" : "fixtures"}</span>
            <button onClick={() => { setLive(false); void run(); }} disabled={load.state === "loading"}>Run fixtures</button>
            <button onClick={() => { setLive(true); void run(); }} disabled={load.state === "loading"}>Run live</button>
          </div>
        </div>
        <p className="xs" style={{ color: "var(--faint)", margin: "8px 0 0" }}>
          22 scenarios, authored by us. Treat as a smoke test, not an evaluation.
        </p>
      </div>

      {load.state === "loading" && <Loading label="Running all 22 scenarios" />}
      {load.state === "error" && <ErrorPane error={load.error} retry={run} />}
       {load.state === "ready" && <Report report={load.data} sweep={sweep} />}

      <CanaryPanel />
    </div>
  );
}

function Report({ report, sweep }: {
  report: BenchReport;
  sweep: { threshold: number; detection: number | null; fp: number | null }[] | null;
}) {
  const m = report.metrics;
  const matrix = report.confusion.matrix;
  const decisions = ["APPROVE", "CHALLENGE", "BLOCK"];

  const sweepRows = sweep ?? report.sweep.map((s) => ({
    threshold: s.threshold, detection: s.detection_rate, fp: s.false_positive_rate,
  }));

  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 12 }}>
        <Metric label="Attack detection rate" display={m.attack_block_rate.display} pct={m.attack_block_rate.pct}
                note={m.attack_block_rate.note} target="â‰¥ 14/15 blocked+contained" good={m.attack_block_rate.value === 1} />
        <Metric label="Legit approval success" display={m.legitimate_approval_success.display} pct={m.legitimate_approval_success.pct}
                note="after OOB where required" target="15/15" good={m.legitimate_approval_success.value === 1} />
        <Metric label="False challenge rate" display={m.false_challenge_rate.display} pct={m.false_challenge_rate.pct}
                note="on frictionless-expected only" target="0/3" good={(m.false_challenge_rate.value ?? 1) === 0} />
        <Metric label="Decision latency" display={`p50 ${m.verification_time_ms.p50} ms`} pct={`p95 ${m.verification_time_ms.p95} ms`}
                note={`${m.verification_time_ms.sample} runs Â· ${m.verification_time_ms.mode}`} target="< 900 ms" good={m.verification_time_ms.p50 < 900} />
        <Metric label="Explanation completeness" display={m.explanation_completeness.display} pct={m.explanation_completeness.pct}
                note="every non-zero contribution carries evidence" target="22/22" good={m.explanation_completeness.value === 1} />
        <Metric label="Abstention correctness" display={m.abstention_correctness.display} pct={m.abstention_correctness.pct}
                note="unavailable â‰  clean, enforced" target="22/22" good={m.abstention_correctness.value === 1} />
      </div>

      <div className="card">
        <h2>Confusion matrix â€” expected â†’ actual</h2>
        <table>
          <thead><tr><th>expected â†“ / actual â†’</th>{decisions.map((d) => <th key={d} className="right">{d}</th>)}</tr></thead>
          <tbody>
            {decisions.map((e) => (
              <tr key={e}>
                <td><strong>{e}</strong></td>
                {decisions.map((a) => {
                  const n = matrix[e]?.[a] ?? 0;
                  const diag = e === a;
                  return <td key={a} className={"right nums mono " + (diag ? "" : n ? "broken" : "")}
                             style={diag ? { background: "#f0fdf4" } : n ? { background: "#fff1f2", fontWeight: 700 } : {}}>
                    {n}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {report.confusion.off_diagonal.length > 0 && (
          <ul className="xs" style={{ color: "var(--faint)" }}>
            {report.confusion.off_diagonal.map((miss, i) => (
              <li key={i}>{String(miss.id)}: expected {String(miss.expected)}, got {String(miss.actual)} â€” {String(miss.why)}</li>
            ))}
          </ul>
        )}
        <div className="xs" style={{ color: "var(--faint)", marginTop: 8 }}>
          Prevented fraudulent value: <strong>{m.prevented_fraudulent_value_display}</strong> (synthetic amounts).
        </div>
      </div>

      <div className="card">
        <div className="spread">
          <h2 style={{ margin: 0 }}>Threshold sweep â€” why 70, not 65 or 75</h2>
          <span className="xs" style={{ color: "var(--faint)" }}>
            detection rate vs false-positive rate as the BLOCK threshold moves
          </span>
        </div>
        <SweepChart rows={sweepRows} />
        <div className="xs" style={{ color: "var(--faint)" }}>
          Annotated at the chosen operating point (70). If the curve shows a better point, we say so on
          stage and explain why we did not move it â€” the fixture set is too small to justify a re-tune.
        </div>
        <details className="xs" style={{ color: "var(--faint)", marginTop: 6 }}>
          <summary>Raw sweep data</summary>
          <table><tbody>
            {sweepRows.map((r) => (
              <tr key={r.threshold}>
                <td className="mono">threshold {r.threshold}{r.threshold === 70 ? " â† chosen" : ""}</td>
                <td className="mono">detection {(r.detection ?? 0).toFixed(3)}</td>
                <td className="mono">false-positive {(r.fp ?? 0).toFixed(3)}</td>
              </tr>
            ))}
          </tbody></table>
        </details>
      </div>

      <div className="card" style={{ background: "var(--surface)" }}>
        <h2>What this number is not</h2>
        <p className="xs" style={{ color: "var(--faint)", margin: 0 }}>{report.honesty}</p>
      </div>

      <div className="card">
        <h2>Scenario rows</h2>
        <table>
          <thead><tr><th>ID</th><th>Class</th><th>Expected</th><th>Actual</th><th className="right">Risk</th><th className="right">Latency</th></tr></thead>
          <tbody>
            {report.rows.map((r) => (
              <tr key={String(r.id)}>
                <td className="mono-xs">{String(r.id)}{r.hero !== undefined && r.hero !== null ? " â˜…" : ""}</td>
                <td><span className={"chip " + (r["class"] === "ATTACK" ? "block" : "approve")}>{String(r["class"])}</span></td>
                <td>{String(r.expected)}</td>
                <td><strong>{String(r.actual)}</strong>{r.visible_to_requester && r.visible_to_requester !== r.actual
                  ? <span className="xs" style={{ color: "var(--faint)" }}> (renders as {String(r.visible_to_requester)})</span> : null}</td>
                 <td className="right mono-xs nums">{r.risk_score ?? "â€”"}</td>
                 <td className="right mono-xs nums">{Math.round(Number(r.latency_ms ?? 0))} ms</td>
               </tr>
             ))}
           </tbody>
         </table>
        </div>
        <details className="card">
          <summary className="sm">Toggle a hypothetical threshold (re-band, not re-score)</summary>
          <div className="row" style={{ marginTop: 8 }}>
            <input type="range" min={50} max={90} step={5} defaultValue={70} disabled />
            <span className="xs" style={{ color: "var(--faint)" }}>
              The sweep above is computed over the published risk scores â€” overrides never flip with the
              threshold, which is the point of a hard override.
            </span>
          </div>
        </details>
      </>
    );
  }

function Metric({ label, display, pct, note, target, good }: {
  label: string; display: string; pct: string; note?: string; target: string; good?: boolean;
}) {
  return (
    <div className="card">
      <div className="smallcaps">{label}</div>
      <div className="row" style={{ gap: 8 }}>
        <span className="lg nums mono" style={{ fontWeight: 700 }}>{display}</span>
        <span className={"chip " + (good ? "approve" : "challenge")} style={{ marginLeft: "auto" }}>{pct}</span>
      </div>
      <div className="xs" style={{ color: "var(--faint)" }}>{note}</div>
      <div className="xs" style={{ color: "var(--faint)" }}>target {target}</div>
    </div>
  );
}

function SweepChart({ rows }: { rows: { threshold: number; detection: number | null; fp: number | null }[] }) {
  const W = 560, H = 200, PAD = 34;
  const x = (t: number) => PAD + ((t - 50) / 40) * (W - PAD - 12);
  const y = (v: number) => H - PAD - v * (H - PAD - 14);
  const line = (key: "detection" | "fp") =>
    rows.filter((r) => r[key] !== null).map((r, i) => `${i ? "L" : "M"}${x(r.threshold)},${y(r[key] as number)}`).join(" ");

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", maxWidth: W }} role="img"
         aria-label="Threshold sweep: detection rate falls and false positives fall as the block threshold rises">
      <rect x={PAD} y={14} width={W - PAD - 12} height={H - PAD - 14} fill="#f8fafc" stroke="#e2e8f0" />
      <path d={line("detection")} fill="none" stroke="var(--system)" strokeWidth="2" />
      <path d={line("fp")} fill="none" stroke="var(--challenge)" strokeWidth="2" strokeDasharray="5 3" />
      {/* the chosen operating point, annotated (Â§17.3) */}
      <line x1={x(70)} x2={x(70)} y1={14} y2={H - PAD} stroke="var(--block)" strokeWidth="1.5" />
      <text x={x(70) + 4} y={30} fontSize="10" fill="var(--block)">chosen: 70</text>
      {[50, 60, 70, 80, 90].map((t) => (
        <text key={t} x={x(t)} y={H - PAD + 14} fontSize="10" fill="#64748b" textAnchor="middle">{t}</text>
      ))}
      {[0, 0.5, 1].map((v) => (
        <text key={v} x={PAD - 6} y={y(v) + 3} fontSize="10" fill="#64748b" textAnchor="end">{v}</text>
      ))}
      <text x={W - 12} y={30} fontSize="10" fill="var(--system)" textAnchor="end">â€” detection rate</text>
      <text x={W - 12} y={44} fontSize="10" fill="var(--challenge)" textAnchor="end">- - false positives</text>
    </svg>
  );
}
