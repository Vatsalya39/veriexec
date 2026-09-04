/**
 * `screens/Pipeline.tsx` — the execution screen: controls, three part cards, live output,
 * and the outcome once there is one.
 *
 * The run itself lives one level up, in `App`, because the rail's phase monitor watches the
 * same snapshot this screen renders — one run, two views of it, never two runs. Everything
 * here is a pure function of the snapshot it is handed, which is why these three components
 * render a replayed fixture today and a live core stream after one flag flips.
 */

import { useEffect, useMemo, useState } from "react";
import { PipelineVisualizer } from "../panels/PipelineVisualizer";
import { RunConsole } from "../panels/RunConsole";
import { RunControls } from "../panels/RunControls";
import { ErrorPane } from "../components/ui";
import { formatDuration, shortHash } from "../api/format";
import { decisionLabel, decisionTone, DECISION_ICON } from "../design/tokens";
import type { UseVerificationResult } from "../state/useVerification";
import { listScenarios } from "../workflow/verificationService";
import { measuredLatencyMs } from "../workflow/timeline";
import { modeLabel } from "../workflow/mode";
import type { ScenarioSummary } from "../api/client";
import type { WorkflowOutput } from "../workflow/contract";

function OutcomeCard({ output }: { output: WorkflowOutput }) {
  const tone = decisionTone(output.decision);
  const stages = Object.entries(output.stageLatencyMs);

  return (
    <section className="card fade-in" data-testid="run-outcome" style={{ padding: 12 }}>
      <div className="row" style={{ flexWrap: "wrap", gap: 10 }}>
        <span className={`chip ${tone}`} style={{ fontSize: 14, padding: "4px 10px" }}>
          <span aria-hidden>{DECISION_ICON[output.decision] ?? "•"}</span>
          {decisionLabel(output.decision)}
        </span>
        <div className="col grow" style={{ gap: 0, minWidth: 0 }}>
          <span className="sm" style={{ fontWeight: 600 }}>{output.title}</span>
          <span className="xs" style={{ color: "var(--faint)" }}>
            {output.scenarioId} · policy {output.policyVersion} · assessment {shortHash(output.assessmentId, 6, 4)}
          </span>
        </div>
        <div className="row" style={{ gap: 12 }}>
          <span className="col" style={{ gap: 0 }}>
            <span className="smallcaps">Risk</span>
            <span className="figure nums" style={{ fontSize: 17, fontWeight: 600 }}>{output.riskScore}</span>
          </span>
          <span className="col" style={{ gap: 0 }}>
            <span className="smallcaps">Confidence</span>
            <span className="figure nums" style={{ fontSize: 17, fontWeight: 600 }}>{output.intentConfidence}%</span>
          </span>
        </div>
      </div>

      {output.visibleToRequester && output.visibleToRequester !== output.decision && (
        <p className="xs" style={{ margin: "8px 0 0", color: "var(--faint)" }}>
          The requester sees <strong>{output.visibleToRequester}</strong>. The decision above is
          the bank's, and is not disclosed.
        </p>
      )}

      <div className="row" style={{ alignItems: "flex-start", flexWrap: "wrap", gap: 16, marginTop: 10 }}>
        {output.topReasons.length > 0 && (
          <div className="grow" style={{ minWidth: 220 }}>
            <div className="smallcaps">Why</div>
            <ul className="xs" style={{ margin: "4px 0 0", paddingLeft: 16, color: "var(--faint)" }}>
              {output.topReasons.map((r) => <li key={r}>{r}</li>)}
            </ul>
          </div>
        )}
        {output.requiredActions.length > 0 && (
          <div className="grow" style={{ minWidth: 220 }}>
            <div className="smallcaps">Required next</div>
            <ul className="xs" style={{ margin: "4px 0 0", paddingLeft: 16, color: "var(--faint)" }}>
              {output.requiredActions.map((a) => <li key={a}>{a}</li>)}
            </ul>
          </div>
        )}
      </div>

      {stages.length > 0 && (
        <div className="row inset-strip" style={{ flexWrap: "wrap", gap: 10, marginTop: 10, padding: "6px 8px", borderRadius: "var(--r-md)" }}>
          <span className="smallcaps">Engine latency</span>
          {stages.map(([stage, ms]) => (
            <span key={stage} className="mono-xs nums" style={{ color: "var(--faint)" }}>
              {stage} {formatDuration(ms)}
            </span>
          ))}
          <span className="grow" />
          <span className="mono-xs nums" style={{ color: "var(--faint)" }}>
            total {formatDuration(output.wallMs)}
          </span>
        </div>
      )}
    </section>
  );
}

export function PipelineScreen({
  verification: v, activeStepId, onSelectStep, onSelectScenario,
}: {
  verification: UseVerificationResult;
  activeStepId: string | null;
  onSelectStep: (stepId: string | null) => void;
  onSelectScenario: (id: string) => void;
}) {
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [listError, setListError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void listScenarios()
      .then((rows) => { if (live) setScenarios(rows); })
      .catch(() => { if (live) setListError("The scenario index could not be loaded."); });
    return () => { live = false; };
  }, []);

  const measuredMs = useMemo(
    () => (v.envelope ? measuredLatencyMs(v.envelope) : null),
    [v.envelope],
  );

  return (
    <div className="screen tall">
      <div className="col" style={{ gap: 8, minHeight: 0, flex: 1 }}>
        <RunControls
          snapshot={v.snapshot}
          scenarios={scenarios}
          scenarioId={v.scenarioId}
          onSelectScenario={onSelectScenario}
          speed={v.speed} onSpeed={v.setSpeed}
          fault={v.fault} onFault={v.setFault}
          elapsedMs={v.elapsedMs} measuredMs={measuredMs}
          mode={modeLabel()} source={v.source}
          canRun={v.canRun} canCancel={v.canCancel} canRetry={v.canRetry} busy={v.busy}
          onRun={v.run} onCancel={v.cancel} onRetry={v.retry} onReset={v.reset}
        />

        {listError && <ErrorPane error={{ code: "UPSTREAM_UNAVAILABLE", detail: listError }} />}
        {v.error && <ErrorPane error={{ code: "UPSTREAM_UNAVAILABLE", detail: v.error }}
                               retry={v.canRetry ? v.retry : undefined} />}

        <PipelineVisualizer snapshot={v.snapshot} activeStepId={activeStepId}
                            onSelectStep={onSelectStep} onRetry={v.retry} />

        {v.snapshot.output && <OutcomeCard output={v.snapshot.output} />}

        <RunConsole snapshot={v.snapshot} activeStepId={activeStepId} onSelectStep={onSelectStep} />
      </div>
    </div>
  );
}
