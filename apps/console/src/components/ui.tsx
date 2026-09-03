/**
 * Small shared pieces every screen uses. One file so a change to error styling, say,
 * happens once — §23's "restrained system executed consistently".
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import type { ApiError } from "../api/client";

/** The typed error pane. Never a blank pane, never an optimistic default. §23 */
export function ErrorPane({ error, retry }: { error: ApiError | Error; retry?: () => void }) {
  const e = error as ApiError & Partial<Error>;
  const detail = e.code === "TIMEOUT"
    ? "The scoring service did not respond in 3 seconds. This transaction has not been approved."
    : (e.detail ?? e.message ?? "Something failed.");
  return (
    <div className="card" role="alert" aria-live="polite">
      <div className="row" style={{ gap: 8 }}>
        <span aria-hidden>⚠</span>
        <div className="grow">
          <strong>Unavailable, not clean.</strong>{" "}
          <span className="sm" style={{ color: "var(--faint)" }}>{detail}</span>
        </div>
        {retry && <button onClick={retry}>Retry</button>}
      </div>
    </div>
  );
}

/** Loading with a stage label — no spinner longer than 400 ms without one. §8.3 */
export function Loading({ label }: { label: string }) {
  return (
    <div className="card" aria-live="polite">
      <span className="sm" style={{ color: "var(--faint)" }}>{label}…</span>
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return (
    <button
      className="xs"
      aria-label={`${label}: ${text}`}
      onClick={() => {
        void navigator.clipboard?.writeText(text);
        setCopied(true);
        timer.current = window.setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? "Copied ✓" : label}
    </button>
  );
}

export function Badge({ tone, children }: { tone: "approve" | "challenge" | "block" | "system" | "neutral"; children: ReactNode }) {
  return <span className={`chip ${tone}`}>{children}</span>;
}

/**
 * The evidence drawer: the one elevated surface (§23), used by both the score rows and
 * the graph node click — one component, two entry points (§13.1).
 */
export function EvidenceDrawer({
  title, reference, evidence, onClose,
}: { title: string; reference: string; evidence: unknown; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="drawer-veil" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="drawer" role="dialog" aria-modal="true" aria-label={`Evidence: ${title}`}>
        <div className="spread" style={{ marginBottom: 12 }}>
          <div>
            <div className="smallcaps">Evidence</div>
            <strong>{title}</strong>
            <div className="mono-xs" style={{ color: "var(--faint)" }}>{reference}</div>
          </div>
          <div className="row">
            <CopyButton text={JSON.stringify(evidence, null, 2)} label="Copy JSON" />
            <button onClick={onClose} aria-label="Close evidence drawer">✕</button>
          </div>
        </div>
        <pre>{JSON.stringify(evidence, null, 2)}</pre>
      </div>
    </div>
  );
}

/** Graph/Table toggle — a canvas is not accessible; the table is the substance. §13.1 */
export function ViewToggle({ view, onChange }: { view: "graph" | "table"; onChange: (v: "graph" | "table") => void }) {
  return (
    <div className="row" role="tablist" aria-label="View mode">
      {(["graph", "table"] as const).map((v) => (
        <button key={v} role="tab" aria-selected={view === v}
                style={view === v ? { background: "var(--text)", color: "#fff", borderColor: "var(--text)" } : {}}
                onClick={() => onChange(v)}>{v === "graph" ? "Graph" : "Table"}</button>
      ))}
    </div>
  );
}

export function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  return <a href={href} target="_blank" rel="noreferrer" style={{ color: "#2563eb" }}>{children}</a>;
}
