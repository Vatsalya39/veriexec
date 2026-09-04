/**
 * `screens/Audit.tsx` — the chain table, verify banner, tamper box, chatbot. §21.2 [NEVER CUT]
 *
 * The "break it" screen. A permanent chain banner; a filterable record table; the tamper
 * box (only reachable when the demo endpoint exists — otherwise it explains its own
 * absence, which is itself the security property); the chatbot panel with citations.
 */

import { useEffect, useState } from "react";
import { audit } from "../api/client";
import type { AskResult, AuditRecord, VerifyResult } from "../api/types";
import { ErrorPane, Loading, EvidenceDrawer } from "../components/ui";
import { usePoll } from "../state/hooks";
import { ChainFooter } from "../panels/ChainFooter";
import { shortHash } from "../api/format";

const EVENT_TYPES = [
  "COMMUNICATION_RECEIVED", "INTENT_CAPTURED", "FINGERPRINT_COMPUTED", "RISK_ASSESSED",
  "CHALLENGE_ISSUED", "CHALLENGE_ANSWERED", "SIGNATURE_VERIFIED", "TOKEN_MINTED",
  "TOKEN_REDEEMED", "TOKEN_REDEMPTION_FAILED", "DECISION_RENDERED", "COOLDOWN_STARTED",
  "COOLDOWN_CANCELLED", "BREAKER_TRIPPED", "BREAKER_CLOSED", "DURESS_ESCALATED",
  "CANARY_INJECTED", "CANARY_RESULT", "POLICY_REPLAYED", "OFFICER_OVERRIDE", "CHAIN_VERIFIED",
];

export function AuditScreen() {
  const chain = usePoll(() => audit.verify(), 10_000);
  const [filterTxn, setFilterTxn] = useState("");
  const [filterEvent, setFilterEvent] = useState("");
  const [records, setRecords] = useState<AuditRecord[] | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [row, setRow] = useState<AuditRecord | null>(null);
  const [recompute, setRecompute] = useState<{ record: string; stored: string; match: boolean } | null>(null);

  const load = async () => {
    setErr(null);
    try {
      const res = await audit.records({
        transaction_id: filterTxn || undefined,
        event_type: filterEvent || undefined,
        limit: 200, order: "desc",
      });
      setRecords(res.records);
    } catch (e) { setErr(e as Error); }
  };
  useEffect(() => { void load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, []);

  const verify = chain.value as VerifyResult | null;

  return (
    <div className="screen">
      {/* The permanent banner: green steady, red and naming the first bad seq when broken. */}
      {verify && (verify.ok ? (
        <div className="chain-banner ok" role="status">
          <span aria-hidden>✓</span> Chain verified · {verify.record_count.toLocaleString("en-IN")} records ·
          head <span className="mono">{shortHash(verify.head_hash, 4, 4)}</span> ·
          <span className="nums"> {Math.round(verify.elapsed_ms)} ms</span>
          <span className="grow" />
          <button className="xs" onClick={() => chain.refresh()}>Re-verify now</button>
        </div>
      ) : (
        <div className="chain-banner broken flash" role="alert">
          <span aria-hidden>⛔</span>
          Chain broken at record {verify.first_broken_seq} — records {verify.untrusted_from} to {verify.record_count} cannot be trusted.
          <span className="grow" />
          <button className="xs" onClick={() => chain.refresh()}>Re-verify now</button>
        </div>
      ))}

      <TamperBox onTampered={() => { chain.refresh(); void load(); }} />
      <ChatbotPanel />

      <div className="card">
        <div className="spread" style={{ flexWrap: "wrap" }}>
          <h2 style={{ margin: 0 }}>Records</h2>
          <div className="row">
            <input placeholder="filter by transaction id" value={filterTxn} className="mono-xs"
                   onChange={(e) => setFilterTxn(e.target.value)} style={{ width: 200 }} />
            <select value={filterEvent} onChange={(e) => setFilterEvent(e.target.value)}>
              <option value="">all event types</option>
              {EVENT_TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
            <button onClick={() => void load()}>Apply</button>
          </div>
        </div>
        {err && <ErrorPane error={err} retry={load} />}
        {records === null && !err && <Loading label="Loading records" />}
        {records && (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead><tr><th>Seq</th><th>Time</th><th>Event</th><th>Transaction</th><th>Actor</th><th>Policy</th><th>Hash</th><th></th></tr></thead>
              <tbody>
                {records.map((r) => {
                  const broken = verify && !verify.ok && r.seq >= (verify.untrusted_from ?? 0);
                  const first = verify && !verify.ok && r.seq === verify.first_broken_seq;
                  return (
                    <tr key={r.seq}
                        className={(first ? "broken " : broken ? "inherit-broken " : "") + (r.tampered_at ? "tampered" : "")}
                        onClick={() => setRow(r)} tabIndex={0} role="button"
                        onKeyDown={(e) => { if (e.key === "Enter") setRow(r); }}
                        title="Open the raw record">
                      <td className="mono-xs nums">{r.seq}</td>
                      <td className="mono-xs">{r.timestamp.slice(11, 19)}</td>
                      <td>{r.tampered_at ? <span className="chip system">DEMO ARTEFACT</span> : null} {r.event_type}</td>
                      <td className="mono-xs">{r.transaction_id ?? "—"}</td>
                      <td className="mono-xs">{r.actor}</td>
                      <td className="mono-xs">{r.policy_version}</td>
                      <td className="mono-xs">{shortHash(r.record_hash, 6, 4)}</td>
                      <td><span className="chip neutral">{broken ? "untrusted" : "ok"}</span></td>
                    </tr>
                  );
                })}
                {records.length === 0 && (
                  <tr><td colSpan={8} className="xs" style={{ color: "var(--faint)" }}>No records match. The chain itself may be empty — run a scenario first.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <ChainFooter verify={verify} recordCount={records?.length} />

      {row && (
        <EvidenceDrawer
          title={`Record ${row.seq} · ${row.event_type}`}
          reference={`${row.record_id} · prev ${shortHash(row.prev_hash, 8, 4)} → this ${shortHash(row.record_hash, 8, 4)}`}
          evidence={row}
          onClose={() => { setRow(null); setRecompute(null); }} />
      )}

      {row && (
        <div className="card">
          <h2>Verify this record yourself, in your own browser</h2>
          <div className="row">
            <button onClick={() => {
              // The console's ONLY arithmetic (§26 trap 1): hashing what the server hashed.
              void import("../api/recompute").then(async ({ recomputeRecordHash }) => {
                const record = await recomputeRecordHash(row as unknown as Record<string, unknown>);
                setRecompute({ record: record.computed, stored: row.record_hash, match: record.computed === row.record_hash });
              });
            }}>
              Recompute hash
            </button>
            {recompute && (
              <span className={"chip " + (recompute.match ? "approve" : "block")}>
                {recompute.match ? "✓ matches" : "✗ DOES NOT MATCH"} · stored {shortHash(recompute.stored, 8, 4)} · computed {shortHash(recompute.record, 8, 4)}
              </span>
            )}
          </div>
          <div className="xs" style={{ color: "var(--faint)", marginTop: 6 }}>
            SHA-256 over the canonical form of every field except <code>record_hash</code> itself.
            Letting a judge verify a hash themselves is worth more than a paragraph about integrity.
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------- tamper box

function TamperBox({ onTampered }: { onTampered: () => void }) {
  const [seq, setSeq] = useState(1);
  const [field, setField] = useState("payload.amount_minor_units");
  const [value, setValue] = useState("42000000");
  const [result, setResult] = useState<string | null>(null);
  const [absent, setAbsent] = useState(false);

  const tamper = async () => {
    setResult(null);
    try {
      const r = await audit.tamper(seq, field, Number.isNaN(Number(value)) ? value : Number(value));
      setResult(`Wrote record ${r.seq}.${r.field ? ` ${r.field} = ${value}` : ""} Stored hash is now stale: ${shortHash(r.stored_record_hash, 8, 4)}. Press Re-verify.`);
      onTampered();
    } catch (e) {
      const err = e as { code?: string; detail?: string };
      if (err.code === "HTTP_" && /404/.test(err.detail ?? "")) setAbsent(true);
      else setResult(`Refused: ${err.detail ?? "unknown"}`);
    }
  };

  return (
    <div className="card" data-testid="tamper-box" style={{ borderColor: "color-mix(in srgb, var(--block) 34%, transparent)" }}>
      <div className="spread">
        <div>
          <div className="smallcaps" style={{ color: "var(--block)" }}>The tamper demo · 40 seconds that beat any slide</div>
          <h2 style={{ margin: 0 }}>Edit a record and watch the chain turn red</h2>
        </div>
        <span className="chip system">demo endpoint — absent unless INTENTLOCK_DEMO_ENDPOINTS=1</span>
      </div>

      {absent ? (
        <p className="sm" style={{ color: "var(--faint)" }}>
          <strong>The tamper route does not exist in this configuration.</strong> It is registered only when the
          demo flag is set — not "returns 403", <em>does not exist</em>. A 403 would confirm the capability is
          present; a missing route is the honest default. Start the service with
          <code className="mono"> INTENTLOCK_DEMO_ENDPOINTS=1</code> to run this beat.
        </p>
      ) : (
        <>
          <div className="row" style={{ marginTop: 10, flexWrap: "wrap" }}>
            <label className="sm">seq
              <input type="number" min={1} value={seq} onChange={(e) => setSeq(Number(e.target.value))} className="mono-xs" style={{ width: 80 }} />
            </label>
            <label className="sm">field
              <input value={field} onChange={(e) => setField(e.target.value)} className="mono-xs" style={{ width: 240 }} />
            </label>
            <label className="sm">value
              <input value={value} onChange={(e) => setValue(e.target.value)} className="mono-xs" style={{ width: 120 }} />
            </label>
            <button className="danger" onClick={() => void tamper()}>Write directly to the row</button>
          </div>
          <p className="xs" style={{ color: "var(--faint)" }}>
            Writes straight to SQLite, bypassing the append path — exactly what an attacker with database
            access would do. Every tamper is stamped <code>tampered_at</code>, so a reviewer can tell a demo
            artefact from a real record. We did not detect the edit by comparing against a backup: the record's
            own hash no longer matches its contents, and every record after it inherits that break.
          </p>
          {result && <div className="chain-banner broken" style={{ borderRadius: 8 }}>{result}</div>}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------- chatbot

function ChatbotPanel() {
  const [question, setQuestion] = useState("");
  const [log, setLog] = useState<Array<AskResult & { q: string }>>([]);
  const [busy, setBusy] = useState(false);

  const ask = async () => {
    if (!question.trim() || busy) return;
    setBusy(true);
    const q = question; setQuestion("");
    try {
      const a = await audit.ask(q);
      setLog((prev) => [{ ...a, q }, ...prev]);
    } catch (e) {
      setLog((prev) => [{ q, answer: `The audit service did not respond (${(e as Error).message}). This screen fails visibly, never silently.`, record_seqs: [], facts: {}, refused: true, refusal_kind: "error", intent: "error", computed_by: "python", narrated_by: "template", suggestions: [] }, ...prev]);
    } finally { setBusy(false); }
  };

  const MENU = [
    "Why was TXN-S06 blocked?",
    "How many transactions were blocked today and why?",
    "Did anyone override a block?",
    "Which payees received first-time payments today?",
    "Has this log been altered?",
    "What changed in the policy today?",
  ];

  return (
    <div className="card" data-testid="chatbot">
      <div className="spread">
        <div>
          <div className="smallcaps">Audit explainability · N8</div>
          <h2 style={{ margin: 0 }}>Ask the chain</h2>
        </div>
        <span className="chip neutral">retrieval first · arithmetic in Python · model never decides</span>
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        <input style={{ flex: 1 }} value={question} placeholder="e.g. Why was TXN-S06 blocked?"
               onChange={(e) => setQuestion(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") void ask(); }} />
        <button className="primary" onClick={() => void ask()} disabled={busy || !question.trim()}>
          {busy ? "Asking…" : "Ask"}
        </button>
      </div>
      <div className="row" style={{ marginTop: 8, flexWrap: "wrap" }}>
        {MENU.map((q) => <button key={q} className="xs" onClick={() => setQuestion(q)}>{q}</button>)}
      </div>

      {log.map((a, i) => (
        <div key={i} className="card" style={{ marginTop: 10, background: "var(--surface)" }}>
          <div className="xs mono" style={{ color: "var(--faint)" }}>{a.q}</div>
          <p className="sm" style={{ whiteSpace: "pre-wrap", margin: "6px 0" }}>{a.answer}</p>
          <div className="row" style={{ flexWrap: "wrap" }}>
            {a.refused
              ? <span className="chip challenge">{a.refusal_kind === "decision" ? "refused — I can explain decisions. I cannot make them." : `refused · ${a.refusal_kind}`}</span>
              : a.record_seqs.map((s) => <a key={s} className="chip approve" href="#/audit" title={`Citation: record ${s}`}>#{s}</a>)}
            <span className="grow" />
            <span className="xs mono" style={{ color: "var(--faint)" }}>
              computed by {a.computed_by} · narrated by {a.narrated_by}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
