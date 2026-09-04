/**
 * `workflow/mode.ts` — which transport the workflow layer uses.
 *
 * One boolean, read from the environment once. `VITE_INTENTLOCK_MOCK=0` switches the
 * console onto the real run API; anything else (including an unset variable) keeps the
 * replay engine, because the default has to be the mode that works with no services up.
 */

export function isMockMode(): boolean {
  const raw = import.meta.env?.VITE_INTENTLOCK_MOCK as string | undefined;
  if (raw === undefined || raw === null || raw === "") return true;
  return raw !== "0" && raw.toLowerCase() !== "false";
}

/** Human-readable, for the chip the console shows so no one has to guess. */
export function modeLabel(): string {
  return isMockMode() ? "replay" : "live";
}
