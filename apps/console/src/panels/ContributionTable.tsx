/**
 * Contributions — every number clickable down to its `evidence_ref`. §8.3
 *
 * "Explainable" must be verifiable, not asserted: clicking 19.8 on the beneficiary row
 * opens the evidence JSON, highlighted. Ordered by points, descending — the audit trail
 * behind the risk score, rendered as the story.
 */

import { useState } from "react";
import type { Contribution, ScenarioEnvelope } from "../api/types";
import { EvidenceDrawer } from "../components/ui";

export function ContributionTable({ assessment, envelope }: { assessment: ScenarioEnvelope["assessment"]; envelope: ScenarioEnvelope }) {
  const [drawer, setDrawer] = useState<{ row: Contribution } | null>(null);
  const rows = [...(assessment.contributions ?? [])].sort((a, b) => (b.points ?? 0) - (a.points ?? 0));

  const evidenceFor = (row: Contribution): unknown => {
    // The evidence ref resolves into the envelope: contributions cite EV-PAYEE etc.,
    // which live on the scenario's beneficiary/identity blocks. Full JSON, highlighted.
    const direct = (envelope as unknown as Record<string, Record<string, unknown>>)[row.evidence_ref];
    if (direct) return direct;
    return {
      evidence_ref: row.evidence_ref,
      dimension: row.dimension,
      raw_score: row.raw,
      weight: row.weight,
      points: row.points,
      reason: row.reason,
      source: envelope.signals,
    };
  };

  return (
    <div className="card">
      <h2>Contributions to the risk score</h2>
      <table>
        <thead>
          <tr><th>Dimension</th><th className="right">Raw</th><th className="right">× Weight</th>
              <th className="right">Points</th><th>Why</th></tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.dimension} className="clickable"
                onClick={() => setDrawer({ row })}
                title={`Open evidence ${row.evidence_ref}`}>
              <td><strong>{row.label}</strong>
                {row.abstained === true || (row as { scored_as_clean?: boolean }).scored_as_clean === false
                  ? <span className="chip challenge" style={{ marginLeft: 6 }}>⚠ abstained — not scored as clean</span>
                  : null}
              </td>
              <td className="right mono-xs nums">{row.raw}</td>
              <td className="right mono-xs nums">{row.weight}</td>
              <td className="right mono-xs nums">
                <button className="xs" style={{ padding: "1px 6px" }}
                        aria-label={`Evidence for ${row.label} (${row.evidence_ref})`}>
                  {row.points?.toFixed?.(1) ?? row.points}
                </button>
              </td>
              <td style={{ color: "var(--faint)" }}>{row.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="xs" style={{ color: "var(--faint)", marginTop: 8 }}>
        Every points value opens its evidence record. Sum: {" "}
        <span className="mono">{(assessment.arithmetic?.contributions_subtotal ?? rows.reduce((s, r) => s + (r.points ?? 0), 0)).toFixed?.(1)}</span>
        {" "}→ risk <span className="mono">{assessment.risk_score}</span>
        {assessment.arithmetic?.uncertainty_penalty ? <> · uncertainty penalty {" "}
          <span className="mono">{assessment.arithmetic.uncertainty_penalty}</span></> : null}
      </div>
      {drawer && (
        <EvidenceDrawer
          title={drawer.row.label}
          reference={drawer.row.evidence_ref}
          evidence={evidenceFor(drawer.row)}
          onClose={() => setDrawer(null)} />
      )}
    </div>
  );
}
