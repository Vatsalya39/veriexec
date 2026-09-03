/**
 * The counterfactual card. `[NOVEL-N12b]` §8.5
 *
 * One card, one sentence, present tense, actionable. B's honest text — "No change to
 * risk scoring would approve this" — rendered verbatim, never softened. For APPROVE,
 * the inverse card: what would have challenged it.
 */

import type { ScenarioEnvelope } from "../api/types";

export function CounterfactualCard({ envelope }: { envelope: ScenarioEnvelope }) {
  const a = envelope.assessment;
  const cf = a.counterfactual;
  if (!cf) return null;

  const isOverride = Boolean(a.override_applied && a.override_applied.startsWith("HO-"));
  const approved = a.decision === "APPROVE";

  return (
    <div className="card" data-testid="counterfactual">
      <div className="smallcaps">{approved ? "What would have challenged this" : "What would have approved this"}</div>
      <p className="sm" style={{ margin: "8px 0 4px", fontWeight: 550 }}>
        {cf.narrative ?? "The risk engine published no counterfactual for this decision."}
      </p>
      {cf.kind === "categorical" && !approved && (
        <div className="xs" style={{ color: "var(--faint)" }}>
          Categorical, not numeric: a control replaced the score, so there is no lower score
          that would have changed it{isOverride ? ` — override ${a.override_applied}` : ""}.
        </div>
      )}
      {cf.kind === "withheld" && (
        <div className="xs" style={{ color: "var(--faint)" }}>
          Withheld on this record. The full contributions remain available to anyone with access.
        </div>
      )}
      <div className="xs mono" style={{ color: "var(--faint)", marginTop: 6 }}>
        Quoted from the decision record — not recomputed in this browser.
      </div>
    </div>
  );
}
