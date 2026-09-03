/**
 * The evidence graph. `[NOVEL-N5b]` §13
 *
 * B returns the subgraph; this renders it. No trust arithmetic in the browser — if the
 * graph and the score disagree, the score is right and the graph is a bug.
 *
 * Layout is computed client-side as ranked columns (a dagre-class layout in ~40 lines,
 * no dependency): sources left, fusion and control right. Colour encodes evidence AGE
 * where the nodes carry it — grey established, amber recent, red created this session.
 * The `Graph / Table` toggle reuses one drawer for node clicks and gives the trackpad-
 * hostile judge a table anyway. Cap at 14 nodes with a visible chip, never a silent drop.
 */

import { useMemo, useState } from "react";
import type { EvidenceGraph, ScenarioEnvelope } from "../api/types";
import { EvidenceDrawer, ViewToggle } from "../components/ui";

const NODE_CAP = 14;

const KIND_ORDER: Record<string, number> = {
  source: 0, detector: 1, dimension: 2, fusion: 3, control: 4, decision: 5,
};

export function EvidenceGraphPanel({ envelope }: { envelope: ScenarioEnvelope }) {
  const [view, setView] = useState<"graph" | "table">("graph");
  const [drawer, setDrawer] = useState<{ id: string } | null>(null);
  const graph: EvidenceGraph | null = envelope.assessment.evidence_graph ?? null;

  const layout = useMemo(() => {
    if (!graph) return null;
    const nodes = graph.nodes ?? [];
    const truncated = nodes.length > NODE_CAP;
    const visible = nodes.slice(0, NODE_CAP);
    // Rank by kind with a per-rank stacking order; edges fall right-to-left naturally.
    const byId = new Map(visible.map((n) => [n.id, n]));
    const rank = (n: (typeof visible)[number]) => NODE_ORDER(n);
    const columns = new Map<number, typeof visible>();
    for (const n of visible) {
      const r = rank(n);
      if (!columns.has(r)) columns.set(r, []);
      columns.get(r)!.push(n);
    }
    const positions = new Map<string, { x: number; y: number }>();
    for (const [r, col] of columns) {
      col.forEach((n, i) => positions.set(n.id, { x: r * 190 + 20, y: i * 74 + 20 }));
    }
    const edges = (graph.edges ?? []).filter((e) => byId.has(e.from) && byId.has(e.to));
    return { visible, edges, positions, truncated, hidden: nodes.length - visible.length };
  }, [graph]);

  if (!graph || !layout) return null;

  const width = Math.max(...[...layout.positions.values()].map((p) => p.x + 190), 800);
  const height = Math.max(...[...layout.positions.values()].map((p) => p.y + 70), 200);

  const nodeColor = (n: (typeof layout.visible)[number]) => {
    if (n.state === "block") return "var(--block)";
    if (n.state === "warn" || n.state === "challenge") return "var(--challenge)";
    if (n.state === "recent") return "var(--challenge)";
    if (n.state === "new_session") return "var(--block)";
    return "var(--border)";
  };

  return (
    <div className="card">
      <div className="spread">
        <h2 style={{ marginBottom: 0 }}>Evidence graph</h2>
        <div className="row">
          {layout.truncated && (
            <span className="chip system" title="The payload exceeded the 14-node render cap">
              GRAPH_TRUNCATED · +{layout.hidden} more relationships
            </span>
          )}
          <ViewToggle view={view} onChange={setView} />
        </div>
      </div>

      {view === "graph" ? (
        <div style={{ overflowX: "auto", marginTop: 8 }}>
          <svg width={width} height={height} role="img" aria-label="Evidence graph: how signals flow into the decision">
            {layout.edges.map((e, i) => {
              const from = layout.positions.get(e.from)!;
              const to = layout.positions.get(e.to)!;
              const x1 = from.x + 168, y1 = from.y + 26;
              const x2 = to.x + 22, y2 = to.y + 26;
              return (
                <g key={i}>
                  <path d={`M${x1},${y1} C${x1 + 60},${y1} ${x2 - 60},${y2} ${x2},${y2}`}
                        fill="none" stroke="#cbd5e1" strokeWidth="1.5" />
                  {e.label && (
                    <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 4} fontSize="10" fill="#64748b" textAnchor="middle">
                      {e.label}
                    </text>
                  )}
                </g>
              );
            })}
            {layout.visible.map((n) => {
              const p = layout.positions.get(n.id)!;
              const color = nodeColor(n);
              const isDecision = n.kind === "decision" || n.kind === "control";
              return (
                <g key={n.id} transform={`translate(${p.x},${p.y})`}
                   style={{ cursor: "pointer" }} tabIndex={0} role="button"
                   aria-label={`${n.label} — ${n.detail ?? ""}`}
                   onClick={() => setDrawer({ id: n.id })}
                   onKeyDown={(e) => { if (e.key === "Enter") setDrawer({ id: n.id }); }}>
                  <rect width="168" height="52" rx="8"
                        fill={isDecision && n.state === "block" ? "#fff1f2" : "#fff"}
                        stroke={color} strokeWidth={isDecision ? 2 : 1} />
                  <text x="12" y="21" fontSize="12" fontWeight="600" fill="#0f172a">{n.label}</text>
                  <text x="12" y="38" fontSize="10" fill="#64748b">{n.detail}</text>
                </g>
              );
            })}
          </svg>
          <div className="xs" style={{ color: "var(--faint)", marginTop: 4 }}>
            Grey = established evidence · amber = recent (&lt; 7 days) · red = created this session.{" "}
            Every node opens its evidence record.
          </div>
        </div>
      ) : (
        <table style={{ marginTop: 8 }}>
          <thead><tr><th>Node</th><th>Kind</th><th>Detail</th><th>Points</th></tr></thead>
          <tbody>
            {layout.visible.map((n) => (
              <tr key={n.id} className="clickable" onClick={() => setDrawer({ id: n.id })}>
                <td><strong>{n.label}</strong> <span className="mono-xs" style={{ color: "var(--faint)" }}>{n.id}</span></td>
                <td><span className="chip neutral">{n.kind}</span></td>
                <td style={{ color: "var(--faint)" }}>{n.detail}</td>
                <td className="mono-xs nums">{n.points ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {drawer && (
        <EvidenceDrawer
          title={layout.visible.find((n) => n.id === drawer.id)?.label ?? drawer.id}
          reference={drawer.id}
          evidence={{
            node: layout.visible.find((n) => n.id === drawer.id),
            edges_from: layout.edges.filter((e) => e.from === drawer.id),
            edges_to: layout.edges.filter((e) => e.to === drawer.id),
            full_graph: graph,
          }}
          onClose={() => setDrawer(null)} />
      )}
    </div>
  );
}

function NODE_ORDER(n: { kind: string }): number {
  return KIND_ORDER[n.kind] ?? 3;
}
