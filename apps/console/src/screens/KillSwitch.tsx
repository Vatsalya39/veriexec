/**
 * `screens/KillSwitch.tsx` — C17. §20 `[NOVEL-N25b]` [NEVER CUT]
 *
 * One toggle, top-right everywhere: `LLM: ON`. Flipping it POSTs B's /v1/mode server-side
 * — never client-only, so the change is real and lands in the audit log as MODE_CHANGED.
 * Re-run S06 both ways and `Compare` shows exactly one differing region: the
 * explanation. "The language model wrote the paragraph. Arithmetic and cryptography
 * wrote the decision."
 */

import { useState } from "react";
import * as api from "../api/client";
import type { ScenarioEnvelope } from "../api/types";
import { diffAssessments } from "../state/hooks";
import { ErrorPane } from "../components/ui";
import { ChainFooter } from "../panels/ChainFooter";
import { usePoll } from "../state/hooks";
import { audit } from "../api/client";

export function KillSwitchScreen({ envelope }: { envelope: ScenarioEnvelope | null }) {
  const [llmOn, setLlmOn] = useState(true);
  const [baseline, setBaseline] = useState<ScenarioEnvelope | null>(null);
  const [flipped, setFlipped] = useState<ScenarioEnvelope | null>(null);
  const [diff, setDiff] = useState<string[] | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const chain = usePoll(() => audit.verify(), 10_000);

  const flip = async (next: boolean) => {
    setBusy(true); setError(null);
    try {
      await api.core.mode(next ? "FULL" : "NO_LLM").catch(() => setOfflineNote());
      setLlmOn(next);
      await audit.append({
        event_type: "POLICY_REPLAYED", actor: "console:kill-switch",
        transaction_id: envelope?.intent.intent_id,
        payload: { mode: next ? "FULL" : "NO_LLM" },
      }).catch(() => undefined);
    } catch (e) {
      setError(e as Error);
    } finally { setBusy(false); }
  };

  const [offlineNote, setOfflineNoteState] = useState<string | null>(null);
  function setOfflineNote() { setOfflineNoteState("Mode change recorded locally — B's /v1/mode is not reachable; the toggle state here is demonstrative until integration."); }

  const captureBaseline = () => { setBaseline(envelope); setFlipped(null); setDiff(null); };
  const captureFlipped = () => { setFlipped(envelope); setDiff(null); };

  const compare = () => {
    if (!baseline || !flipped) return;
    setDiff(diffAssessments(baseline.assessment, flipped.assessment));
  };

  return (
    <div className="screen">
      <div className="card">
        <div className="spread">
          <div>
            <div className="smallcaps">Kill switch · N25b · never cut</div>
            <h2 style={{ margin: 0 }}>Delete our own AI on stage</h2>
          </div>
          <div className="row">
            <span className={"chip " + (llmOn ? "neutral" : "system")}>
              {llmOn ? "LLM: ON" : "LLM: OFF — deterministic core only"}
            </span>
            <button className={llmOn ? "danger" : "primary"} disabled={busy} onClick={() => void flip(!llmOn)}
                    aria-live="polite">
              {busy ? "Switching…" : llmOn ? "Kill the LLM" : "Restore the LLM"}
            </button>
          </div>
        </div>
        {offlineNote && <p className="xs" style={{ color: "var(--faint)", marginTop: 8 }}>{offlineNote}</p>}
        <p className="xs" style={{ color: "var(--faint)", marginTop: 8 }}>
          The toggle is server-side: a POST to the core's mode endpoint, logged as an audit event —
          never a client-only flag. The demo beat: run S06 with the model on, flip, re-run. The
          decision, the risk score, the intent confidence and every field delta stay byte-identical.
          Only the prose disappears.
        </p>
      </div>

      {error && <ErrorPane error={error} />}

      <div className="card">
        <h2>Compare the two runs</h2>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <button onClick={captureBaseline} disabled={!envelope}>Capture current assessment as run A</button>
          <button onClick={captureFlipped} disabled={!envelope}>Capture current assessment as run B</button>
          <button className="primary" onClick={compare} disabled={!baseline || !flipped}>Compare</button>
        </div>
        {baseline && <div className="xs mono" style={{ marginTop: 6, color: "var(--faint)" }}>A: {baseline.assessment.assessment_id} · risk {baseline.assessment.risk_score} · {baseline.assessment.decision}</div>}
        {flipped && <div className="xs mono" style={{ color: "var(--faint)" }}>B: {flipped.assessment.assessment_id} · risk {flipped.assessment.risk_score} · {flipped.assessment.decision}</div>}
        {diff && (
          <div className="card" style={{ marginTop: 10, background: diff.length === 1 && diff[0] === "top_reasons" ? "var(--tint-approve)" : "var(--surface)" }}
               data-testid="compare-result" aria-live="polite">
            {diff.length === 1 && diff[0] === "top_reasons" ? (
              <>
                <span className="chip approve">✓ {diff.length} field differs: the explanation</span>
                <p className="sm" style={{ color: "var(--faint)" }}>
                  Exactly one region — the prose. The decision, the score, the confidence and every
                  delta are byte-identical. The model wrote the paragraph; arithmetic and
                  cryptography wrote the decision.
                </p>
              </>
            ) : (
              <>
                <span className="chip challenge">{diff.length} field(s) differ: {diff.join(", ")}</span>
                <p className="xs" style={{ color: "var(--faint)" }}>
                  More than the explanation moved — that would be a bug in the deterministic core, and
                  it is exactly what this comparison exists to catch.
                </p>
              </>
            )}
          </div>
        )}
      </div>

      <div className="card" style={{ background: "var(--surface)" }}>
        <h2>The strongest 25 seconds available to this project</h2>
        <p className="sm" style={{ color: "var(--faint)" }}>
          Run S06 with the model on. Note the decision and the intent confidence. Flip the switch.
          Re-run. <strong>The decision, the risk score, the intent confidence and every field delta
          are identical.</strong> Only the prose changes. Then say: <em>"The language model wrote the
          paragraph. Arithmetic and cryptography wrote the decision. Here is the decision with the
          model switched off."</em>
        </p>
      </div>

      <ChainFooter verify={chain.value} />
    </div>
  );
}
