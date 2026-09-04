/**
 * `components/ThemeToggle.tsx` — the persistent light/dark control.
 *
 * Icons are inline SVG: this repo has no icon package and venue wifi is not a dependency
 * we accept. The button states what it will do, not what it is (`Switch to dark`), which
 * is the one phrasing that never confuses anyone reading it out loud on stage.
 *
 * `compact` is the collapsed-rail form: same button, label hidden, title carries the text.
 */

import { useTheme } from "../state/useTheme";

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { theme, followsSystem, toggle } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  const label = `Switch to ${next} mode`;

  return (
    <button
      type="button"
      className="ghost row"
      onClick={toggle}
      title={followsSystem ? `${label} — currently following your system setting` : label}
      aria-label={label}
      style={{ width: "100%", justifyContent: compact ? "center" : "flex-start", gap: 8 }}
    >
      {theme === "dark" ? <SunIcon /> : <MoonIcon />}
      {!compact && <span className="rail-label">{theme === "dark" ? "Light" : "Dark"}</span>}
      {!compact && followsSystem && (
        <>
          <span className="grow" />
          <span className="chip neutral rail-label" style={{ fontSize: 9 }}>auto</span>
        </>
      )}
    </button>
  );
}

const ICON = {
  width: 15, height: 15, viewBox: "0 0 24 24", fill: "none",
  stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const, "aria-hidden": true,
};

function MoonIcon() {
  return (
    <svg {...ICON}>
      <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a6.6 6.6 0 0 0 10.5 10.5Z" />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg {...ICON}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4" />
    </svg>
  );
}
