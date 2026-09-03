/**
 * `screens/Verify.tsx` — THE HERO SCREEN. §8 [NOVEL-N21b, N12b]
 *
 * One transaction, the full verification story: scenario bar, two-number card, decision,
 * diff, contributions, counterfactual, evidence graph, chain footer. Everything else in
 * the console is supporting material; disproportionate time belongs here.
 *
 * Stage labels (§8.3): "Extracting… → Scoring… → Deciding…" — no spinner over 400 ms
 * without one. Empty/loading/error exist for every section; a missing contribution
 * renders as absent, never as 0.
 */

import { useEffect, useMemo, useState } from "react";
import * as api from "../api/client";
import type { ScenarioSummary } from "../api/client";
import { useChain, useScenario } from "../state/hooks";
import { ErrorPane, Loading } from "../components/ui";
import { ScenarioBar } from "../panels/ScenarioBar";
import { TwinNumberCard } from "../panels/TwoNumberCard";
import { DecisionBar } from "../panels/DecisionBar";
import { FieldDiff } from "../panels/FieldDiff";
import { ContributionTable } from "../panels/ContributionTable";
import { CounterfactualCard } from "../panels/CounterfactualCard";
import { EvidenceGraphPanel } from "../panels/EvidenceGraph";
import { CooldownBar, StepRail } from "../panels/Temporal";
import { OobPanel } from "../panels/OobPanel";
import { ProcessingPane } from "../panels/ProcessingPane";
import { ChainFooter } from "../panels/ChainFooter";
import { audit } from "../api/client";

export function VerifyScreen({ scenarioId, onScenarioChange }: { scenarioId: string | null; onScenarioChange: (id: string) => void }) {
  const [summaries, setSummaries] = useState<ScenarioSummary[] | null>(null);
  const { load, reload } = useScenario(scenarioId);
  const chain = useChain();

  useEffect(() => {
    api.listScenarios().then(setSummaries).catch(() => setSummaries([]));
  }, []);

  // The decision is an audit event, recorded when the screen renders a complete verdict.
  useEffect(() => {
    if (load.state !== "ready") return;
    const env = load.data.data;
    if (env.assessment.decision === "SILENT_ESCALATION") return; // logged server-side only, §12
    void audit.append({
      event_type: "DECISION_RENDERED", actor: "console",
      transaction_id: env.intent.intent_id,
      payload: { decision: env.assessment.decision, risk_score: env.assessment.risk_score,
                 scenario: env.scenario.id, source: load.data.source },
    }).catch(() => undefined);
  }, [load]);

  const envelope = load.state === "ready" ? load.data.data : null;

  const stageLabel = useMemo(() => {
    if (load.state === "loading") return scenarioId ? `Scoring ${scenarioId}` : "Scoring";
    return "Scoring";
  }, [load.state, scenarioId]);

  return (
    <div className="screen">
      {summaries !== null && (
        <ScenarioBar scenarios={summaries} activeId={scenarioId} onPick={onScenarioChange} />
      )}

      {load.state === "loading" && <Loading label={stageLabel} />}
      {load.state === "error" && <ErrorPane error={load.error} retry={reload} />}
      {load.state === "ready" && envelope && (
        load.data.source === "fixture" ? (
          <span className="chip system" style={{ alignSelf: "flex-start" }} role="status">
            ⚙ cached fixture — upstream services not reachable; same policy engine, same shape
          </span>
        ) : null
      )}

      {envelope && (
        <>
          {/* The requester's face of a silent escalation: an ordinary slow approval. §12 */}
          {envelope.assessment.visible_to_requester === "PROCESSING" ? (
            <ProcessingPane />
          ) : (
            <>
              <TwinNumberCard
                voiceAuthenticity={envelope.signals.communication?.voice_authenticity
                  ?? envelope.signals.communication?.stylometry_match
                  ?? null}
                intentConfidence={envelope.assessment.intent_confidence.value}
                decision={envelope.assessment.decision} />

              <DecisionBar envelope={envelope} />
              <StepRail envelope={envelope} />
              <FieldDiff envelope={envelope} />

              <div style={{ display: "grid", gridTemplateColumns: "minmax(320px, 3fr) minmax(280px, 2fr)", gap: 16 }}>
                <ContributionTable assessment={envelope.assessment} envelope={envelope} />
                <div className="col">
                  <CounterfactualCard envelope={envelope} />
                  <CooldownBar envelope={envelope} />
                </div>
              </div>

              <OobPanel envelope={envelope} />
              <EvidenceGraphPanel envelope={envelope} />

              <div className="xs" style={{ color: "var(--faint)" }}>
                Total pipeline latency on this assessment: {" "}
                <span className="mono nums">{envelope.assessment.latency_ms ?? envelope.timeline?.reduce((s, t) => s + (t.latency_ms ?? 0), 0)} ms</span>
                {" "}· policy <span className="mono">{envelope.assessment.policy_version}</span>
                {" "}· engine <span className="mono">{envelope.assessment.engine_version ?? "—"}</span>
              </div>
            </>
          )}
        </>
      )}

      <ChainFooter verify={chain.value} />
    </div>
  );
}
