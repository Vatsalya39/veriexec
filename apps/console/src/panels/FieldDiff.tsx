/**
 * Intent vs Request — the two-column diff. §8.4
 *
 * Ordered by severity (critical first), not by field name. Fingerprint pair as the last
 * row, monospace, truncated, with a copy button — and when it mismatches, that row gets
 * the only red border on the screen.
 *
 * Redaction discipline (asserted in `account_redaction.test.tsx`): account values render
 * last-4 only, everywhere — including tooltips and the copy payload. The copy button
 * copies the *displayed* text; full account numbers must not exist in the DOM.
 */

import type { FieldDelta, ScenarioEnvelope } from "../api/types";
import { redactAccount, shortHash } from "../api/format";
import { CopyButton } from "../components/ui";

const SEVERITY_ORDER: Record<string, number> = { critical: 0, warning: 1, cosmetic: 2 };

/** Render a delta value so an account never appears in full. */
function displayValue(field: string, value: string): string {
  if (/account|ifsc/i.test(field)) return redactAccount(value);
  if (/amount_minor/i.test(field) && /^\d+$/.test(value)) {
    const n = Number(value);
    return `${value} (${(n / 100).toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })})`;
  }
  return value;
}

export function FieldDiff({ envelope }: { envelope: ScenarioEnvelope }) {
  const deltas: FieldDelta[] = (envelope.signals.fingerprint?.field_deltas ?? [])
    .slice()
    .sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9));
  const verdict = envelope.signals.fingerprint?.verdict;
  const fp = envelope.intent.fingerprint_hex ?? null;

  if (!deltas.length && !fp) return null;

  return (
    <div className="card">
      <h2>Intent vs request</h2>
      <table>
        <thead>
          <tr><th>Field</th><th>Authorized</th><th>Presented</th><th>Match</th></tr>
        </thead>
        <tbody>
          {deltas.map((d) => (
            <tr key={d.field}>
              <td className="mono-xs">{d.field}</td>
              <td className="mono-xs">{displayValue(d.field, d.expected)}</td>
              <td className="mono-xs">{displayValue(d.field, d.presented)}</td>
              <td>
                {d.severity === "critical"
                  ? <span className="chip block">✗ critical</span>
                  : d.severity === "warning"
                    ? <span className="chip challenge">⚠ differs</span>
                    : <span className="chip neutral">≈ cosmetic</span>}
              </td>
            </tr>
          ))}
          <tr style={verdict === "MISMATCH" ? { outline: "2px solid var(--block)", background: "#fff1f2" } : {}}>
            <td className="mono-xs">fingerprint</td>
            <td className="mono-xs" colSpan={2}>
              {verdict === "MISMATCH"
                ? <span className="chip block">✗ MISMATCH — the account changed after authorization</span>
                : <span className="chip approve">✓ {verdict}</span>}
              {fp && <span className="mono-xs" style={{ marginLeft: 8 }}>{shortHash(fp, 8, 6)}</span>}
            </td>
            <td>{fp ? <CopyButton text={shortHash(fp, 8, 6)} label="Copy truncated hash" /> : null}</td>
          </tr>
        </tbody>
      </table>
      <div className="xs" style={{ color: "var(--faint)", marginTop: 8 }}>
        Account values are shown as the last four digits only, everywhere — including copy payloads.
      </div>
    </div>
  );
}
