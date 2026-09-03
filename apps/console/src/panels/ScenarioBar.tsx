/**
 * The scenario bar — the demo's control strip. Loads the 22 frozen scenarios as buttons
 * (hero scenarios first), shows the active one's channel and description.
 */

import type { ScenarioSummary } from "../api/client";

export function ScenarioBar({
  scenarios, activeId, onPick,
}: { scenarios: ScenarioSummary[]; activeId: string | null; onPick: (id: string) => void }) {
  const active = scenarios.find((s) => s.id === activeId) ?? null;
  const heroes = scenarios.filter((s) => s.hero !== null).sort((a, b) => (a.hero ?? 9) - (b.hero ?? 9));
  const rest = scenarios.filter((s) => s.hero === null);

  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <label className="sm" htmlFor="scenario-pick">
          <strong>Scenario</strong>
          <select id="scenario-pick" value={activeId ?? ""}
                  onChange={(e) => onPick(e.target.value)}
                  style={{ marginLeft: 8 }}>
            <option value="" disabled>Load a scenario…</option>
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.id} — {s.title}{s.hero ? " ★ HERO" : ""} [{s.class}]
              </option>
            ))}
          </select>
        </label>
        {heroes.map((s) => (
          <button key={s.id} onClick={() => onPick(s.id)}
                  style={s.id === activeId ? { background: "var(--text)", color: "#fff", borderColor: "var(--text)" } : {}}
                  title={s.title}>{s.id} ★</button>
        ))}
        <span className="grow" />
        {active && (
          <>
            <span className="chip neutral">Channel {active.channel}</span>
            {active.decision && <span className={"chip " + toneFor(active.decision)}>{active.decision}</span>}
          </>
        )}
      </div>
      {active && (
        <div className="xs" style={{ color: "var(--faint)" }}>
          {active.id}: {active.title} · {active.amount_display} · expected {active.decision}
          {" · "}
          <a href={`/golden/${active.id}.json`} target="_blank" rel="noreferrer" style={{ color: "#2563eb" }}>
            raw fixture JSON
          </a>
        </div>
      )}
      {rest.length > 0 && (
        <details className="xs" style={{ color: "var(--faint)" }}>
          <summary>All scenarios ({scenarios.length})</summary>
          <div className="row" style={{ flexWrap: "wrap", marginTop: 6 }}>
            {rest.map((s) => (
              <button key={s.id} className="xs" onClick={() => onPick(s.id)}
                      style={s.id === activeId ? { background: "var(--text)", color: "#fff" } : {}}>
                {s.id} {s.class === "ATTACK" ? "· attack" : "· legit"}
              </button>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function toneFor(decision: string): string {
  if (decision.includes("APPROVE")) return "approve";
  if (decision.includes("CHALLENGE")) return "challenge";
  if (decision === "SILENT_ESCALATION") return "system";
  return "block";
}
