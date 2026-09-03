/**
 * The decision bar — the band ALONGSIDE the override, never instead of it. §8.3
 *
 * `risk 58 (band: CHALLENGE)` struck through, then `BLOCK — HO-1`. Displaying where the
 * policy overruled its own score is the cheapest possible proof that nothing is hidden.
 */

import type { ScenarioEnvelope } from "../api/types";
import { decisionColor, decisionLabel, DECISION_ICON } from "../design/tokens";
import { reasonSentence } from "../copy/reasons";

export function DecisionBar({ envelope }: { envelope: ScenarioEnvelope }) {
  const a = envelope.assessment;
  const overridden = Boolean(a.override_applied) && a.band_outcome !== a.decision && a.decision !== "SILENT_ESCALATION";
  const visible = a.visible_to_requester ?? a.decision;
  const overrideSentence = reasonSentence(a.override_applied ?? a.hard_override?.code ?? null)
    ?? a.hard_override?.reason ?? null;

  return (
    <div className="card" data-testid="decision" aria-live="polite">
      <div className="row" style={{ flexWrap: "wrap", gap: 12 }}>
        <div className="xl" style={{ color: decisionColor(a.decision) }} aria-label={`Decision: ${decisionLabel(a.decision)}`}>
          <span aria-hidden>{DECISION_ICON[a.decision] ?? ""} </span>
          {decisionLabel(visible === "PROCESSING" ? "CHALLENGE" : a.decision)}
        </div>
        <div className="col" style={{ gap: 2 }}>
          <div className="sm nums">
            risk <strong>{a.risk_score}</strong>{" "}
            <span className="mono-xs">(band: </span>
            <span className="mono-xs" style={overridden ? { textDecoration: "line-through", color: "var(--faint)" } : {}}>
              {a.band_outcome}
            </span>
            <span className="mono-xs">)</span>
            {overridden && (
              <span className="mono-xs" style={{ marginLeft: 6, fontWeight: 700, color: decisionColor(a.decision) }}>
                → {a.decision} — {a.override_applied}
              </span>
            )}
          </div>
          {overrideSentence && (
            <div className="xs" style={{ color: "var(--faint)" }}>{overrideSentence}</div>
          )}
        </div>
        <div className="grow" />
        {a.policy_version && (
          <span className="chip neutral" title="Reproducible: replaying the stored record under this policy version yields a byte-identical assessment">
            policy {a.policy_version}
          </span>
        )}
        {a.mode === "NO_LLM" && <span className="chip system">⚙ deterministic core only — LLM off</span>}
      </div>
      {a.required_actions?.length ? (
        <ul className="sm" style={{ margin: "10px 0 0", paddingLeft: 20, color: "var(--faint)" }}>
          {a.required_actions.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      ) : null}
    </div>
  );
}
