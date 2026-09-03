/**
 * Cooldown, breaker, and the step rail. §14, §15
 *
 * Cooldown shows its arithmetic — `58 × 6 = 348s` — because a cooldown that shows its
 * formula is a policy and one that just spins is a delay. On expiry: no auto-submit; a
 * fresh click is required, because auto-submission after a hold defeats the hold.
 *
 * Breaker banner appears on every screen above the nav, sourced from one poll so it
 * cannot go stale mid-demo.
 *
 * The step rail (P2) shows all required steps up front — users abandon flows whose
 * length they cannot see — with one line of why: friction that explains itself.
 */

import { useEffect, useState } from "react";
import { formatCountdown } from "../api/format";
import { STEP_LABELS, stepRailLine } from "../copy/reasons";
import type { ScenarioEnvelope } from "../api/types";

export function CooldownBar({ envelope, onRelease }: { envelope: ScenarioEnvelope; onRelease?: () => void }) {
  const seconds = envelope.assessment.contributions === undefined ? 0 : cooldownSeconds(envelope);
  const [left, setLeft] = useState(seconds);
  const [expired, setExpired] = useState(seconds <= 0);

  useEffect(() => {
    if (seconds <= 0) return;
    const started = Date.now();
    setLeft(seconds);
    setExpired(false);
    const timer = window.setInterval(() => {
      const remaining = seconds - (Date.now() - started) / 1000;
      if (remaining <= 0) { setLeft(0); setExpired(true); window.clearInterval(timer); }
      else setLeft(remaining);
    }, 250);
    return () => window.clearInterval(timer);
  }, [seconds]);

  if (seconds <= 0) return null;
  const risk = envelope.assessment.risk_score;

  return (
    <div className="card" data-testid="cooldown" aria-live="polite">
      <div className="spread">
        <div>
          <strong>Mandatory hold</strong>{" "}
          <span className="sm" style={{ color: "var(--faint)" }}>
            Risk {risk} — {formatCountdown(left)} before this authorization can be redeemed.
          </span>
        </div>
        <span className="chip neutral mono">{risk} × 6 = {seconds}s</span>
      </div>
      <div className="meter" style={{ marginTop: 8 }} role="meter" aria-valuemin={0}
           aria-valuemax={seconds} aria-valuenow={Math.round(left)} aria-label="Cooldown remaining">
        <span style={{ width: `${seconds ? (left / seconds) * 100 : 0}%`, background: "var(--challenge)" }} />
      </div>
      {expired ? (
        <div className="row" style={{ marginTop: 8 }}>
          <span className="chip approve">✓ hold complete</span>
          <button onClick={onRelease} disabled={!onRelease}>Redeem authorization</button>
          <span className="xs" style={{ color: "var(--faint)" }}>
            Redeeming requires a fresh click — it is never automatic.
          </span>
        </div>
      ) : (
        <div className="xs" style={{ marginTop: 6, color: "var(--faint)" }}>
          The hold expires; nothing is submitted until you click.
        </div>
      )}
    </div>
  );
}

function cooldownSeconds(envelope: ScenarioEnvelope): number {
  const raw = envelope.challenge?.cooldown_seconds ?? 0;
  if (raw > 0) return raw;
  const risk = envelope.assessment.risk_score ?? 0;
  return Math.min(900, Math.max(0, Math.round(risk * 6)));
}

/** The org-wide breaker banner — persistent, above the nav, every screen. §14 */
export function BreakerBanner({ state, openedAt, trialAt }: { state: string; openedAt?: string; trialAt?: string }) {
  if (state === "CLOSED") return null;
  return (
    <div className="chain-banner" role="alert"
         style={state === "OPEN"
           ? { background: "#f5f3ff", color: "#5b21b6", borderBottom: "1px solid #ddd6fe" }
           : { background: "#fffbeb", color: "#92400e", borderBottom: "1px solid #fde68a" }}>
      <span aria-hidden>{state === "OPEN" ? "⏸" : "⚠"}</span>
      {state === "OPEN" ? (
        <>Organization-wide hold — 4 high-risk authorizations in 10 minutes. All executive transfers paused
          {openedAt ? <> until {new Date(openedAt).toLocaleTimeString("en-IN")}</> : null}.</>
      ) : (
        <>Trial mode — next authorization decides whether the hold stays or lifts
          {trialAt ? <> (from {new Date(trialAt).toLocaleTimeString("en-IN")})</> : null}.</>
      )}
    </div>
  );
}

/** The step rail: friction that explains itself. §15 `[NOVEL-N6]` [P2] */
export function StepRail({ envelope }: { envelope: ScenarioEnvelope }) {
  const steps = requiredSteps(envelope);
  if (steps.length <= 1) return null;
  const why: string[] = [];
  if (envelope.signals.fingerprint?.verdict !== "MATCH") why.push("the fingerprint was not verified");
  if ((envelope.assessment.risk_score ?? 0) >= 50) why.push("the risk score is high");
  if (envelope.signals.communication?.voice_abstain || envelope.signals.communication?.video_abstain)
    why.push("a detector could not score its input");

  return (
    <div className="card" data-testid="step-rail">
      <div className="sm" style={{ marginBottom: 8 }}>{stepRailLine(why)}</div>
      <ol className="col" style={{ margin: 0, paddingLeft: 0, listStyle: "none", gap: 4 }}>
        {steps.map((s, i) => (
          <li key={i} className="row" style={{ gap: 8 }}>
            <span className="chip neutral" aria-hidden>{i + 1}</span>
            <span className="sm">{STEP_LABELS[s] ?? s}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function requiredSteps(envelope: ScenarioEnvelope): string[] {
  const risk = envelope.assessment.risk_score ?? 0;
  const steps: string[] = ["signature"];
  if (risk >= 70) return [];          // terminal block — no path
  if (risk >= 50) { steps.push("questions", "cooldown"); }
  else if (risk >= 30) steps.push("question");
  if (envelope.out_of_band) steps.push("oob");
  return steps;
}
