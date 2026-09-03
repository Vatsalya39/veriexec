/**
 * `screens/Desk.tsx` — the security desk's face of a silent escalation. §12.2 `[NOVEL-N1c]`
 *
 * Side-by-side: the requester's live view (an ordinary progress bar) next to the DURESS
 * banner. This juxtaposition IS the demo moment. The desk sees THAT a duress condition
 * fired, never the marker, the scheme or its position — `duress_reason` renders as the
 * category, and if the phrase ever appears here, the registry is compromised the first
 * time a screenshot leaves the room.
 *
 * This screen is only linked from the demo role selector labelled "Acting as (demo)" —
 * a selected identity, not an authenticated one (§4.6).
 */

import type { ScenarioEnvelope } from "../api/types";
import { ProcessingPane } from "../panels/ProcessingPane";
import { redactAccount } from "../api/format";

export function DeskScreen({ envelope }: { envelope: ScenarioEnvelope | null }) {
  const duress = envelope?.assessment.duress_escalation === true;

  return (
    <div className="screen">
      <div className="card">
        <div className="spread">
          <div>
            <div className="smallcaps">Security desk · acting as (demo)</div>
            <h2 style={{ margin: 0 }}>Escalations</h2>
          </div>
          <span className="chip neutral">selected identity, not authenticated — a deliberate scope cut</span>
        </div>
        <p className="xs" style={{ color: "var(--faint)" }}>
          This screen is what the requester must never see. The network tab on their client contains no
          request to any escalation endpoint — the escalation is entirely server-side.
        </p>
      </div>

      {duress && envelope ? (
        <>
          <div className="chain-banner broken flash" role="alert">
            <span aria-hidden>⛔</span> <strong>SILENT ESCALATION ACTIVE</strong> — a registered
            signal was used. The requester's screen below is an ordinary progress bar. Respond per protocol.
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <div className="col">
              <div className="smallcaps">The requester sees</div>
              <ProcessingPane />
              <div className="xs" style={{ color: "var(--faint)" }}>
                Indistinguishable from a genuine slow approval: no warning colour, no badge, no changed
                layout, no new network-visible route. The eventual terminal state reads as an ordinary one.
              </div>
            </div>
            <div className="col">
              <div className="smallcaps">The desk sees</div>
              <div className="card" style={{ borderColor: "var(--block)" }}>
                <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                  <span className="chip block">⛔ SILENT ESCALATION</span>
                  <span className="chip neutral mono">{envelope.intent.intent_id}</span>
                  <span className="chip neutral">{envelope.intent.channel}</span>
                </div>
                <table style={{ marginTop: 10 }}>
                  <tbody>
                    <tr><td>Requester</td><td><strong>{envelope.intent.executive_id}</strong> (claimed)</td></tr>
                    <tr><td>Amount</td><td className="mono">{envelope.intent.amount_display ?? "—"}</td></tr>
                    <tr><td>Destination</td><td className="mono">{redactAccount(envelope.intent.beneficiary?.account_last4 ?? null)}</td></tr>
                    <tr><td>Reason category</td><td><span className="chip system">REGISTERED_MARKER_PRESENT</span></td></tr>
                  </tbody>
                </table>
                <div className="xs" style={{ color: "var(--faint)", marginTop: 8 }}>
                  The category, never the phrase: rendering the marker here would burn the registry the
                  first time this screenshot left the room.
                </div>
              </div>
              <div className="card" style={{ background: "var(--surface)" }}>
                <strong className="sm">Response protocol</strong>
                <ol className="xs" style={{ color: "var(--faint)", paddingLeft: 18, margin: "6px 0 0" }}>
                  <li>Do not contact the requester on the requesting channel.</li>
                  <li>Reach the executive on a pre-registered contact by voice.</li>
                  <li>If coercion is confirmed, involve emergency services — the transaction is already held.</li>
                </ol>
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="card">
          <strong>No active escalation.</strong>{" "}
          <span className="sm" style={{ color: "var(--faint)" }}>
            Load scenario S09 (the coercion scenario) on the Verify screen — the desk view mirrors it.
          </span>
        </div>
      )}
    </div>
  );
}
