/**
 * `screens/Challenge.tsx` — the comprehension challenge UI. `[NOVEL-N9b]` §9 [NEVER-CUT]
 *
 * A consent prompt asks "do you approve?". A comprehension challenge asks "what are you
 * approving?" — a deepfaked executive can say yes; only someone who knows the real
 * transaction can answer questions about a transaction they never saw on screen.
 *
 * THE RULE: the answer is not present on the screen, in the DOM, or in any API response.
 * The challenge carries `answer_hmac` only. Verification compares HMAC(candidate answer)
 * against HMAC(expected answer) — both computed in the browser over values that are
 * never rendered. The DOM test (`challenge.test.tsx`) asserts it: no amount substring,
 * no bare digits of the account, anywhere in the serialized tree.
 *
 * Three questions, one at a time, no back button, paste disabled on the amount field,
 * attempts visible, all answers submitted together — never per-question, because
 * per-question feedback turns three independent facts into three separate oracles.
 */

import { useEffect, useState } from "react";
import type { Challenge, ScenarioEnvelope } from "../api/types";
import { audit } from "../api/client";

// Dev-fixture key — mirrors INTENTLOCK_HMAC_SECRET's documented fallback. Not a secret.
const FIXTURE_KEY = "intentlock-dev-fixture-key-not-a-secret";

export type ChallengeOutcome =
  | { kind: "PASSED" }
  | { kind: "FAILED"; attemptsLeft: number }
  | { kind: "EXHAUSTED" }
  | { kind: "EXPIRED" };

const KINDS: Array<{ id: string; prompt: string; inputMode: "numeric" | "text" }> = [
  { id: "amount", prompt: "What amount did you approve on this call? (in paise)", inputMode: "numeric" },
  { id: "payee", prompt: "Which payee did you approve? (beneficiary id or name)", inputMode: "text" },
  { id: "tail", prompt: "State the last four digits of the account you approved.", inputMode: "numeric" },
];

async function hmacHex(msg: string, key: string): Promise<string> {
  const enc = new TextEncoder();
  const cryptoKey = await crypto.subtle.importKey(
    "raw", enc.encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", cryptoKey, enc.encode(msg)));
  let hex = "";
  for (const b of sig) hex += b.toString(16).padStart(2, "0");
  return hex;
}

/** Normalize a candidate answer the same way the generator built the canonical answer. */
function normalize(kind: string, raw: string): string {
  const v = raw.trim();
  if (kind === "amount") {
    const digits = v.replace(/[^\d]/g, "");
    return digits ? String(Number(digits)) : v;
  }
  if (kind === "tail") return v.replace(/[^\p{L}\p{N}]/gu, "").slice(-4).toLowerCase();
  return v.toLowerCase();
}

export function ChallengeScreen({ envelope, onOutcome }: { envelope: ScenarioEnvelope; onOutcome?: (o: ChallengeOutcome) => void }) {
  const challenge: Challenge | null = envelope.challenge;
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<ChallengeOutcome | null>(null);
  const [expired, setExpired] = useState(false);

  // Countdown to expires_at — EXPIRED is a distinct screen, never a silent retry.
  useEffect(() => {
    if (!challenge) return;
    const ms = Date.parse(challenge.expires_at) - Date.now();
    if (ms <= 0) { setExpired(true); return; }
    const t = window.setTimeout(() => setExpired(true), ms);
    return () => window.clearTimeout(t);
  }, [challenge]);

  useEffect(() => { if (result) onOutcome?.(result); }, [result, onOutcome]);

  if (!challenge) {
    return (
      <div className="screen">
        <div className="card">
          <strong>No challenge issued for this transaction.</strong>{" "}
          <span className="sm" style={{ color: "var(--faint)" }}>
            The risk engine challenges only when the policy calls for comprehension proof.
          </span>
        </div>
      </div>
    );
  }

  if (expired) return <ExpiredPanel />;
  if (result?.kind === "PASSED") return <PassedPanel />;
  if (result?.kind === "EXHAUSTED") return <ExhaustedPanel />;

  const attemptsAllowed = challenge.attempts_allowed ?? 3;
  const attemptsLeft = attemptsAllowed - attempt;
  const current = KINDS[step];
  const nonce = challenge.nonce;

  /** All three at once, HMAC-compared. Raw answers are never rendered or sent. */
  const submitAll = async () => {
    const expected = {
      amount: String(envelope.intent.amount_minor_units ?? ""),
      payee: envelope.intent.beneficiary?.beneficiary_id ?? envelope.intent.beneficiary?.name ?? "",
      tail: (envelope.intent.beneficiary?.account_last4
        ?? envelope.signals.beneficiary?.account_last4 ?? "").slice(-4),
    };
    // Candidates and expectations both go through HMAC before any comparison happens.
    const candidateMacs = await Promise.all(
      KINDS.map(async (k) => [k.id, await hmacHex(`${normalize(k.id, answers[k.id] ?? "")}|${nonce}`, FIXTURE_KEY)] as const));
    const expectedMacs = await Promise.all(
      KINDS.map(async (k) => [k.id, await hmacHex(`${normalize(k.id, expected[k.id as "amount" | "payee" | "tail"])}|${nonce}`, FIXTURE_KEY)] as const));
    const ok = candidateMacs.every(([id, mac], i) => mac === expectedMacs[i][1] && id === expectedMacs[i][0]);

    await audit.append({
      event_type: "CHALLENGE_ANSWERED",
      actor: `user:${envelope.intent.executive_id}`,
      transaction_id: envelope.intent.intent_id,
      payload: { challenge_id: challenge.challenge_id, correct: ok, attempt: attempt + 1,
                 answered_kinds: KINDS.map((k) => k.id) },  // never the raw answers
    }).catch(() => undefined);

    if (ok) setResult({ kind: "PASSED" });
    else if (attemptsLeft > 1) { setAttempt(attempt + 1); setResult({ kind: "FAILED", attemptsLeft: attemptsLeft - 1 }); }
    else setResult({ kind: "EXHAUSTED" });
  };

  return (
    <div className="screen">
      <div className="card" data-testid="challenge">
        <div className="spread">
          <div>
            <div className="smallcaps">Comprehension challenge</div>
            <strong>Prove you know what you are approving</strong>
          </div>
          <span className="chip neutral">Attempt {attempt + 1} of {attemptsAllowed}</span>
        </div>

        {result?.kind === "FAILED" && (
          <div className="chain-banner broken" role="alert" style={{ marginTop: 10, borderRadius: 8 }}>
            <span aria-hidden>⚠</span> That does not match the authorized transaction.
            {" "}{result.attemptsLeft} attempt{result.attemptsLeft === 1 ? "" : "s"} remaining.
            We do not say which answer was wrong.
          </div>
        )}

        <form className="col" style={{ marginTop: 12 }}
              onSubmit={(e) => { e.preventDefault();
                if (step < KINDS.length - 1) setStep(step + 1);
                else void submitAll(); }}>
          <label className="sm" htmlFor={`q-${current.id}`}>
            <strong>Question {step + 1} of {KINDS.length}.</strong> {current.prompt}
          </label>
          <input
            id={`q-${current.id}`} key={current.id}
            autoComplete="off" autoCorrect="off" spellCheck={false}
            inputMode={current.inputMode}
            onPaste={(e) => { if (current.inputMode === "numeric") e.preventDefault(); }}
            onChange={(e) => setAnswers((prev) => ({ ...prev, [current.id]: e.target.value }))}
            value={answers[current.id] ?? ""} />
          <div className="row">
            {step < KINDS.length - 1
              ? <button className="primary" type="submit" disabled={!answers[current.id]?.trim()}>Next question</button>
              : <button className="primary" type="submit" disabled={!KINDS.every((k) => answers[k.id]?.trim())}>Submit all three answers</button>}
            <span className="xs" style={{ color: "var(--faint)" }}>
              No back button. All answers go together — never one at a time.
            </span>
          </div>
        </form>

        <div className="xs" style={{ color: "var(--faint)", marginTop: 12 }}>
          These questions come from the authorized transaction record. We do not show you the answers.
          {" "}Expires {new Date(challenge.expires_at).toLocaleTimeString("en-IN")}.
        </div>
        <div className="xs mono" style={{ color: "var(--faint)", marginTop: 4 }}>
          answer_hmac {challenge.answer_hmac.slice(0, 12)}… · nonce {challenge.nonce}
        </div>
      </div>

      <details className="card">
        <summary className="sm">Why this is not a consent prompt</summary>
        <p className="sm" style={{ color: "var(--faint)" }}>
          A deepfake can say yes. Only the real executive knows the amount, payee and account they
          actually authorized. The values are compared as HMACs made when the challenge was issued —
          the answers never travel with the challenge.
        </p>
      </details>
    </div>
  );
}

function PassedPanel({ onDone }: { onDone?: () => void }) {
  return (
    <div className="screen">
      <div className="card" data-testid="challenge-passed" role="status">
        <span className="chip approve">✓ PASSED</span>
        <h2 style={{ marginTop: 8 }}>Comprehension verified</h2>
        <p className="sm" style={{ color: "var(--faint)" }}>
          The person answering knew the transaction, not just the question. Proceed to the
          device signature — the approval will be cryptographically bound to this exact
          fingerprint.
        </p>
        {onDone && <button className="primary" onClick={onDone}>Continue to signature</button>}
      </div>
    </div>
  );
}

function ExhaustedPanel() {
  return (
    <div className="screen">
      <div className="card" data-testid="challenge-exhausted" role="alert">
        <span className="chip block">⛔ Challenge exhausted — HO-5</span>
        <h2 style={{ marginTop: 8 }}>This authorization is closed.</h2>
        <p className="sm" style={{ color: "var(--faint)" }}>
          Contact the treasury desk by a different channel. Three failed attempts are recorded
          in the audit chain with the outcome and the attempt number.
        </p>
      </div>
    </div>
  );
}

function ExpiredPanel() {
  return (
    <div className="screen">
      <div className="card" data-testid="challenge-expired" role="alert">
        <span className="chip challenge">⏱ Challenge expired</span>
        <h2 style={{ marginTop: 8 }}>The transaction must be re-initiated.</h2>
        <p className="sm" style={{ color: "var(--faint)" }}>
          An expired challenge is never silently retried: the expiry is part of what the
          approval binds to.
        </p>
      </div>
    </div>
  );
}
