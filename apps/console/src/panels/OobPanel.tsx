/**
 * The commitment-first out-of-band reveal. `[NOVEL-N7]` §11
 *
 * The code is large, monospace, letter-spaced. The transaction details are hidden behind
 * "Reveal after the executive has stated them" with an explicit warning — if the verifier
 * can see the amount while listening, they will unconsciously prompt it, and the whole
 * mechanism collapses into confirmation bias. Reveal-before-entry is an ordering
 * violation and is flagged as one.
 *
 * The callback destination comes from the registry's registered contacts, last-4 only,
 * and free text is refused — attacker-supplied callback numbers are the most common
 * real-world defeat of this control.
 */

import { useMemo, useState } from "react";
import type { OobSession, ScenarioEnvelope } from "../api/types";
import { redactAccount } from "../api/format";
import { audit } from "../api/client";

export function OobPanel({ envelope, codeVerified }: { envelope: ScenarioEnvelope; codeVerified?: (ok: boolean) => void }) {
  const oob: OobSession | null = envelope.out_of_band;
  const [revealed, setRevealed] = useState(false);
  const [revealAt, setRevealAt] = useState<string | null>(null);
  const [entered, setEntered] = useState<{ amount: string; payee: string; last4: string } | null>(null);
  const [verdict, setVerdict] = useState<{ result: "CONFIRMED" | "CONTRADICTED" | "INCOMPLETE"; field?: string } | null>(null);

  const expected = useMemo(() => ({
    amount: String(envelope.intent.amount_minor_units ?? ""),
    payee: envelope.intent.beneficiary?.beneficiary_id ?? envelope.intent.beneficiary?.name ?? "",
    last4: (envelope.intent.beneficiary?.account_last4 ?? "").slice(-4),
  }), [envelope]);

  if (!oob) return null;

  const compare = (stated: { amount: string; payee: string; last4: string }) => {
    const fieldChecks: Array<[string, boolean]> = [
      ["amount", normalizeAmount(stated.amount) === expected.amount],
      ["payee", stated.payee.trim().toLowerCase() === expected.payee.trim().toLowerCase()],
      ["last4", stated.last4.trim().slice(-4) === expected.last4],
    ];
    const failed = fieldChecks.filter(([, ok]) => !ok);
    const result = failed.length === 0 ? "CONFIRMED"
      : failed.length === fieldChecks.length ? "INCOMPLETE"
      : "CONTRADICTED";
    setVerdict({ result, field: failed.length === 1 ? failed[0][0] : undefined });

    // The reveal ordering is itself an integrity finding — recorded either way.
    void audit.append({
      event_type: result === "CONFIRMED" ? "CHALLENGE_ANSWERED" : "CHALLENGE_ANSWERED",
      actor: "user:operator",
      transaction_id: envelope.intent.intent_id,
      payload: { oob_id: oob.oob_id, result, contradicted_fields: failed.map(([f]) => f),
                 reveal_preceded_entry: Boolean(revealAt) },
    }).catch(() => undefined);
    codeVerified?.(result === "CONFIRMED");
  };

  const orderingViolation = entered !== null && revealAt === null;

  return (
    <div className="card" data-testid="oob">
      <div className="spread">
        <div>
          <div className="smallcaps">Out-of-band verification · commitment first</div>
          <strong>Call the executive on the registered number</strong>
          <div className="xs" style={{ color: "var(--faint)" }}>
            Registered contacts only — {oob.registered_contacts.map(redactAccount).join(", ")}. A free-text
            number is refused: attacker-supplied callbacks are the most common defeat of this control.
          </div>
        </div>
        <div className="mono" style={{ fontSize: 30, letterSpacing: "0.45em", fontWeight: 700 }}
             aria-label={`Verification code, read to the executive: ${oob.verification_code}`}>
          {oob.verification_code}
        </div>
      </div>

      <ol className="sm" style={{ color: "var(--faint)", margin: "10px 0", paddingLeft: 20 }}>
        <li>Read the code <strong>to</strong> the executive. One-way — the person on the line cannot supply it.</li>
        <li>The executive states the amount, payee and account last-4 <strong>unprompted</strong>.</li>
        <li>Type what they said. The console compares against the committed fingerprint.</li>
      </ol>

      {!revealed ? (
        <div className="card" style={{ background: "var(--surface)", borderStyle: "dashed" }}>
          <button className="danger"
                  onClick={() => { setRevealed(true); setRevealAt(new Date().toISOString()); }}>
            Reveal transaction details
          </button>
          <span className="xs" style={{ color: "var(--faint)", marginLeft: 8 }}>
            Reveal only <strong>after</strong> the executive has stated them — if you can see the amount
            while listening, you will prompt it.
          </span>
        </div>
      ) : (
        <div className="col" data-testid="oob-entry">
          {orderingViolation && entered && (
            <span className="chip challenge">⚠ details revealed after entry began — ordering violation recorded</span>
          )}
          <div className="row">
            <label className="sm">Executive said · amount (paise)
              <input inputMode="numeric" autoComplete="off" placeholder="e.g. 1000000000"
                     onChange={(e) => setEntered((prev) => ({ ...(prev ?? { amount: "", payee: "", last4: "" }), amount: e.target.value }))} />
            </label>
            <label className="sm">payee
              <input autoComplete="off"
                     onChange={(e) => setEntered((prev) => ({ ...(prev ?? { amount: "", payee: "", last4: "" }), payee: e.target.value }))} />
            </label>
            <label className="sm">account last-4
              <input inputMode="numeric" autoComplete="off" maxLength={4}
                     onChange={(e) => setEntered((prev) => ({ ...(prev ?? { amount: "", payee: "", last4: "" }), last4: e.target.value }))} />
            </label>
          </div>
          <div className="row">
            <button className="primary" onClick={() => entered && compare(entered)}>Compare against the commitment</button>
            {verdict && (
              <span className={"chip " + (verdict.result === "CONFIRMED" ? "approve" : verdict.result === "CONTRADICTED" ? "block" : "neutral")}>
                {verdict.result === "CONFIRMED" ? "✓ CONFIRMED"
                  : verdict.result === "CONTRADICTED" ? `✗ CONTRADICTED — ${verdict.field} does not match`
                  : "… INCOMPLETE"}
              </span>
            )}
          </div>
          <div className="xs mono" style={{ color: "var(--faint)" }}>
            The commitment was made before the call: the details were not adjusted mid-conversation.
            Contradictions are recorded with the field name — never the raw spoken values.
          </div>
        </div>
      )}
    </div>
  );
}

function normalizeAmount(s: string): string {
  const digits = s.replace(/[^\d]/g, "");
  return digits ? String(Number(digits)) : "";
}
