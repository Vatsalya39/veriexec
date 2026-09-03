/**
 * The requester's processing pane. §12.1 `[NOVEL-N1c]`
 *
 * THE ABSOLUTE RULE: this screen must be indistinguishable from a genuine slow approval.
 * No warning colour, no badge, no changed layout, no duress-flavoured network request,
 * and — because the component's own name is readable in devtools — the file is named
 * `ProcessingPane`, not anything with a d-word. `duress_bundle.test` greps the built
 * bundle for that vocabulary and fails if it survives.
 *
 * The timing floor holds this pane open as long as a normal challenge would take; the
 * escalation itself is entirely server-side and this client learns nothing.
 */

import { useEffect, useState } from "react";

export function ProcessingPane({ floorMs = 2400 }: { floorMs?: number }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Date.now() - started), 300);
    return () => window.clearInterval(timer);
  }, []);

  const pct = Math.min(95, 8 + (elapsed / floorMs) * 87);

  return (
    <div className="card" data-testid="processing" aria-live="polite">
      <h2>Verification in progress</h2>
      <p className="sm" style={{ color: "var(--faint)", margin: "6px 0 12px" }}>
        This can take a few minutes for transactions of this size.
      </p>
      <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
           aria-label="Verification progress">
        <span style={{ width: `${pct}%`, background: "var(--neutral)" }} />
      </div>
    </div>
  );
}
