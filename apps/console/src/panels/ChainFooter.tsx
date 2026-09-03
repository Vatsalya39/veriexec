/**
 * The chain footer — the published head hash, monospace, always visible. §4.4
 *
 * "That is the head of the chain. Anything that changes any record in the log changes
 * that string." Red when the chain is broken; the verify banner names the record.
 */

import type { VerifyResult } from "../api/types";
import { shortHash } from "../api/format";

export function ChainBanner({ verify }: { verify: VerifyResult | null }) {
  if (!verify) return null;
  if (verify.ok) {
    return (
      <div className="chain-banner ok" role="status">
        <span aria-hidden>✓</span>
        <span>Chain verified · {verify.record_count.toLocaleString("en-IN")} records ·
              head <span className="mono">{shortHash(verify.head_hash, 4, 4)}</span> ·
              <span className="nums"> {Math.round(verify.elapsed_ms)} ms</span>
        </span>
      </div>
    );
  }
  return (
    <div className="chain-banner broken flash" role="alert">
      <span aria-hidden>⛔</span>
      <span>
        Chain broken at record {verify.first_broken_seq}
        {verify.broken_field ? <>: field <code className="mono">{verify.broken_field}</code></> : null}
        . Records {verify.untrusted_from}–{verify.record_count} can no longer be trusted — a break is
        inherited, not local.
      </span>
    </div>
  );
}

export function ChainFooter({ verify, recordCount }: { verify: VerifyResult | null; recordCount?: number }) {
  const broken = verify && !verify.ok;
  return (
    <footer className={"chain-footer" + (broken ? " broken" : "")}>
      <span aria-hidden>⛓</span>
      <span className="smallcaps">Chain head</span>
      <span className="hash mono">{verify?.head_hash ? shortHash(verify.head_hash, 6, 3) : "—"}</span>
      <span className="nums">{(recordCount ?? verify?.record_count ?? 0).toLocaleString("en-IN")} records</span>
      {verify?.ok && <span className="nums">verified {Math.round(verify.elapsed_ms)} ms</span>}
      {broken && <span style={{ color: "var(--block)", fontWeight: 700 }}>BROKEN at record {verify?.first_broken_seq}</span>}
      <span className="grow" />
      <span className="xs" style={{ color: "var(--faint)" }}>
        Anything that changes any record in the log changes this string.
      </span>
    </footer>
  );
}
