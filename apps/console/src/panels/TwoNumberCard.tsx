/**
 * THE TWO-NUMBER CARD — the most important component in the repo. §8.2
 *
 * Voice authenticity and intent confidence: adjacent, same size, same visual weight,
 * always both visible. Never separate screens, never behind a tab, never split across
 * the fold. The whole thesis is the gap between these two bars.
 *
 * Rules enforced here and asserted in `two_number_card.test.tsx`:
 *  - identical bar geometry (one shared class, .twin-meter);
 *  - voice authenticity is neutral grey ALWAYS, regardless of its value — a green 96
 *    next to a red 20 is exactly the story, and the colour must not help it;
 *  - intent confidence carries the decision colour;
 *  - labels "Is it him?" / "Is it his transaction?" in small caps under each.
 */

import type { Decision } from "../api/types";
import { decisionColor, DECISION_ICON } from "../design/tokens";

export function TwinNumberCard({
  voiceAuthenticity, intentConfidence, decision,
}: {
  voiceAuthenticity: number | null;
  intentConfidence: number | null;
  decision: Decision | string | null;
}) {
  return (
    <div className="card" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <div className="col" data-testid="voice-authenticity">
        <div className="smallcaps">Is it him?</div>
        <div className="xl nums" aria-label="Voice authenticity">
          {voiceAuthenticity === null ? <span className="lg" style={{ color: "var(--neutral)" }}>abstained</span> : voiceAuthenticity}
        </div>
        <div className="twin-meter" role="meter" aria-valuemin={0} aria-valuemax={100}
             aria-valuenow={voiceAuthenticity ?? undefined} aria-label="Voice authenticity out of 100">
          {/* neutral grey regardless of its value — the deliberate exception (§8.2) */}
          <span style={{ width: `${voiceAuthenticity ?? 0}%`, background: "var(--neutral)" }} />
        </div>
        <div className="xs" style={{ color: "var(--faint)" }}>Voice authenticity</div>
      </div>
      <div className="col" data-testid="intent-confidence">
        <div className="smallcaps">Is it his transaction?</div>
        <div className="xl nums" aria-label="Intent confidence" style={{ color: decisionColor(decision) }}>
          {intentConfidence === null ? "—" : intentConfidence}
        </div>
        <div className="twin-meter" role="meter" aria-valuemin={0} aria-valuemax={100}
             aria-valuenow={intentConfidence ?? undefined} aria-label="Intent confidence out of 100">
          <span style={{ width: `${intentConfidence ?? 0}%`, background: decisionColor(decision) }} />
        </div>
        <div className="xs" style={{ color: "var(--faint)" }}>
          Intent confidence {decision && <span aria-hidden>{DECISION_ICON[decision] ?? ""}</span>}
        </div>
      </div>
    </div>
  );
}
