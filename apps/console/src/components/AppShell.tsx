/**
 * `components/AppShell.tsx` — the chrome: a collapsible rail that is both the navigation
 * and the workflow phase monitor, and a topbar that names the screen you are on.
 *
 * The rail's two jobs share one column on purpose. A reviewer watching a verification run
 * should not have to choose between seeing where they are in the product and seeing where
 * the run is in the pipeline; the phase section sits directly under the links, tracks the
 * same snapshot the pipeline screen renders, and survives the collapse as three glyphs.
 *
 * Collapse state is persisted, because a reviewer who collapses the rail on a projector
 * means it for the rest of the session.
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { PhaseMonitor } from "../panels/PhaseMonitor";
import { ThemeToggle } from "./ThemeToggle";
import type { WorkflowSnapshot } from "../workflow/contract";

const STORAGE_KEY = "intentlock-rail";

export interface ShellRoute {
  id: string;
  label: string;
  /** Shown in the topbar under the screen name. */
  hint?: string;
}

function storedCollapsed(): boolean {
  try { return localStorage.getItem(STORAGE_KEY) === "1"; } catch { return false; }
}

/** The rail glyph: a chevron that points the way the click will move the rail. */
function RailChevron({ collapsed }: { collapsed: boolean }) {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden
         style={{ transform: collapsed ? "none" : "rotate(180deg)", transition: "transform 200ms ease-out" }}>
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

export function AppShell({
  routes, activeRoute, snapshot, activeStepId, onSelectStep, topbarRight, children,
}: {
  routes: readonly ShellRoute[];
  activeRoute: string;
  snapshot: WorkflowSnapshot;
  activeStepId?: string | null;
  onSelectStep?: (stepId: string | null) => void;
  topbarRight?: ReactNode;
  children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(storedCollapsed);

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0"); } catch { /* storage blocked */ }
  }, [collapsed]);

  const toggle = useCallback(() => setCollapsed((c) => !c), []);
  const active = routes.find((r) => r.id === activeRoute) ?? null;

  return (
    <div className="shell">
      <nav className="rail" data-collapsed={collapsed} aria-label="Screens and workflow phase">
        <div className="rail-head">
          <span className="brand-mark" aria-hidden>IL</span>
          <span className="rail-label grow" style={{ minWidth: 0 }}>
            <span className="sm" style={{ fontWeight: 700, letterSpacing: "-0.01em", display: "block" }}>INTENTLOCK</span>
            <span className="smallcaps">Verification console</span>
          </span>
          <button className="ghost xs" onClick={toggle} aria-expanded={!collapsed}
                  title={collapsed ? "Expand the rail" : "Collapse the rail"}
                  aria-label={collapsed ? "Expand the rail" : "Collapse the rail"}
                  style={{ padding: 4, flexShrink: 0 }}>
            <RailChevron collapsed={collapsed} />
          </button>
        </div>

        <div className="rail-body">
          <div className="railnav">
            {routes.map((r) => (
              <a key={r.id} href={`#/${r.id}`} className={activeRoute === r.id ? "active" : ""}
                 title={r.hint ?? r.label} aria-current={activeRoute === r.id ? "page" : undefined}>
                <span className="dot" aria-hidden />
                <span className="rail-label">{r.label}</span>
              </a>
            ))}
          </div>

          <span className="hairline" style={{ height: 1 }} aria-hidden />

          <PhaseMonitor snapshot={snapshot} activeStepId={activeStepId}
                        onSelectStep={onSelectStep} collapsed={collapsed} />
        </div>

        <div className="rail-foot">
          <ThemeToggle compact={collapsed} />
        </div>
      </nav>

      <div className="shell-main">
        <header className="topbar">
          <div className="col grow" style={{ gap: 0, minWidth: 0 }}>
            <h1 style={{ fontSize: 15 }}>{active?.label ?? "Verify"}</h1>
            {active?.hint && <span className="xs" style={{ color: "var(--faint)" }}>{active.hint}</span>}
          </div>
          {topbarRight}
        </header>
        <div className="routed">{children}</div>
      </div>
    </div>
  );
}
