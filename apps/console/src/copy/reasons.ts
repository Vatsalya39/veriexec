/**
 * `copy/reasons.ts` â€” every raw enum mapped to a sentence, in one file, so the language
 * is consistent everywhere and reviewable in one place. Â§8.3: never render a raw enum.
 */

const REASONS: Record<string, string> = {
  FINGERPRINT_MISMATCH: "The account changed after authorization.",
  DURESS: "Sent for out-of-band verification.",
  SAME_CHANNEL_VERIFICATION: "The verification came back on the channel it was asked to leave.",
  BREAKER_TRIPPED: "Too many high-risk requests in a short window.",
  AMOUNT_CEILING: "The amount is above the single-transaction ceiling for this payee.",
  BREAKER: "The organization-wide velocity breaker is open.",
  "HO-1": "The destination account in this request is not the account that was authorized.",
  "HO-2": "Payment to an account not on record, above the single-transaction ceiling.",
  "HO-3": "The payee name is visually identical to an established payee but differs at one codepoint.",
  "HO-4": "This authorization was already consumed.",
  "HO-5": "The approver could not confirm the details of this transaction.",
  "HO-6": "The approving device's signature did not verify.",
  "HO-7": "The beneficiary appears on a screening list.",
  "HO-8": "This authorization was issued under an older policy version.",
  "FC-1": "Too little of the risk model could be evaluated to approve anything.",
  "FC-2": "A detector received input it could not score â€” scored as unavailable, not as clean.",
  "FC-3": "The transaction fingerprint was not verified.",
  INJECTION_ATTEMPT: "The message contains instructions aimed at this system itself.",
  TOKEN_SCOPE_VIOLATION: "The authorization does not cover this payment.",
  NONCE_REPLAY: "This authorization was already used.",
  AUTH_EXPIRED: "This authorization has expired.",
  LLM_UNAVAILABLE: "The language model is offline; the decision did not need it.",
};

/** A sentence for a code. Unknown codes render as the code itself â€” never a blank. */
export function reasonSentence(code: string | null | undefined): string | null {
  if (!code) return null;
  return REASONS[code] ?? code;
}

/** The ladder line for the step rail: friction that explains itself. Â§15 */
export function stepRailLine(reasons: string[]): string {
  if (!reasons.length) return "1 step for this transaction: signature only.";
  return `${reasons.length + 1} steps for this transaction because ${joinAnd(reasons)}.`;
}

function joinAnd(parts: string[]): string {
  if (parts.length === 1) return parts[0];
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

export const STEP_LABELS: Record<string, string> = {
  signature: "Device signature",
  question: "Comprehension question",
  questions: "Comprehension questions",
  cooldown: "Mandatory cooldown",
  oob: "Out-of-band verification",
};
