/**
 * Design tokens — the rules, not the taste. §23
 *
 * Near-neutral slate surface; exactly four semantic colours; voice authenticity is
 * slate-400 always (the one deliberate colour decision in the product); 8-px spacing;
 * one shadow; 150 ms transitions. Fixed at G1 and never argued about again.
 */

export const COLORS = {
  approve: "#059669",     // emerald-600
  challenge: "#f59e0b",  // amber-500
  block: "#e11d48",      // rose-600
  system: "#7c3aed",     // violet-600 — breaker, degraded mode, canary
  neutral: "#94a3b8",    // slate-400 — voice authenticity, ALWAYS
  text: "#0f172a",      // slate-900
  faint: "#64748b",      // slate-500
  surface: "#f8fafc",    // slate-50
  border: "#e2e8f0",     // slate-200
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
