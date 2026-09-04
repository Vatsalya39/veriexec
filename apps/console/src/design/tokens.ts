/**
 * Design tokens — the rules, not the taste. §23
 *
 * Near-neutral achromatic surface; exactly four semantic colours; voice authenticity is
 * `--neutral` always (the one deliberate colour decision in the product); 8-px spacing;
 * one shadow; 150 ms transitions. Fixed at G1 and never argued about again.
 *
 * The values below are *references*, not literals: `tokens.css` resolves each name from a
 * light/dark HSL ladder, so a component that reads `COLORS.approve` is theme-correct in
 * both modes. A hex here would be a light-mode-only colour smuggled into TypeScript.
 */

export const COLORS = {
  approve: "var(--approve)",      // success — emerald family
  challenge: "var(--challenge)",  // warning — amber family
  block: "var(--block)",          // destructive — rose family
  system: "var(--system)",        // info — violet: breaker, degraded mode, canary
  neutral: "var(--neutral)",      // voice authenticity, ALWAYS
  text: "var(--text)",            // primary text tier
  faint: "var(--faint)",          // the only secondary text tier
  surface: "var(--surface)",      // one step off the card
  border: "var(--border)",        // hairline
} as const;

export type DecisionTone = "approve" | "challenge" | "block" | "system" | "neutral";

export function decisionTone(decision: string | null | undefined): DecisionTone {
  switch (decision) {
    case "APPROVE": case "approve": return "approve";
    case "CHALLENGE": case "challenge": return "challenge";
    case "BLOCK": case "block": case "SILENT_ESCALATION": return "block";
    case "BREAKER": case "HALF_OPEN": case "DEGRADED": return "system";
    default: return "neutral";
  }
}

export function decisionColor(decision: string | null | undefined): string {
  return `var(--${decisionTone(decision ?? "")})`;
}

/** Icon + text for every state, so the screen survives a projector and a colour-blind judge. */
export const DECISION_ICON: Record<string, string> = {
  APPROVE: "✓", CHALLENGE: "⚠", BLOCK: "⛔",
  SILENT_ESCALATION: "⛔", BREAKER_TRIPPED: "⏸", PROCESSING: "…",
};

export function decisionLabel(decision: string | null | undefined): string {
  switch (decision) {
    case "APPROVE": return "Approved";
    case "CHALLENGE": return "Challenge required";
    case "BLOCK": return "Blocked";
    case "SILENT_ESCALATION": return "Blocked";       // the requester's view; §12
    case "PROCESSING": return "Processing";
    case "BREAKER": case "BREAKER_TRIPPED": return "Organization-wide hold";
    default: return decision ?? "—";
  }
}
