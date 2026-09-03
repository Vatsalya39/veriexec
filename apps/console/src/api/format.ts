/**
 * Indian money formatting and redaction. §12, §23
 *
 * The console renders; it never recomputes a number the backend already computed. These
 * helpers are presentation-only: grouping is display, the minor-unit integers underneath
 * are untouched. Never floats — `money_format.test.ts` asserts that.
 */

/** `45000000` paise → `₹4,50,000.00`. Indian grouping: last three, then pairs. */
export function formatInr(paise: number | null | undefined): string {
  if (paise === null || paise === undefined || Number.isNaN(paise)) return "—";
  const sign = paise < 0 ? "-" : "";
  const [whole, part] = divmod(Math.abs(Math.trunc(paise)), 100);
  let digits = String(whole);
  if (digits.length > 3) {
    const head = digits.slice(0, -3);
    const tail = digits.slice(-3);
    const pairs: string[] = [];
    let h = head;
    while (h.length > 2) { pairs.unshift(h.slice(-2)); h = h.slice(0, -2); }
    if (h) pairs.unshift(h);
    digits = [...pairs, tail].join(",");
  }
  return `${sign}₹${digits}.${String(part).padStart(2, "0")}`;
}

function divmod(n: number, d: number): [number, number] {
  return [Math.floor(n / d), n % d];
}

/** Lakh/crore live formatting for the sandbox input field. */
export function formatLakhCrore(paise: number | null | undefined): string {
  if (paise === null || paise === undefined) return "—";
  const rupees = paise / 100;
  if (rupees >= 1e7) return `${trimZeros(rupees / 1e7)} crore`;
  if (rupees >= 1e5) return `${trimZeros(rupees / 1e5)} lakh`;
  return formatInr(paise);
}

function trimZeros(n: number): string {
  const s = n.toFixed(2);
  return s.replace(/\.?0+$/, "");
}

/**
 * Account redaction: last 4 only, everywhere — including tooltips, copy payloads and the
 * evidence drawer. Full account numbers must not exist in the DOM; a judge with devtools
 * open is a real scenario. Idempotent on pre-masked values (`••••9281` stays itself).
 */
export function redactAccount(value: string | null | undefined): string {
  if (!value) return "—";
  const alnum = value.replace(/[^\p{L}\p{N}]/gu, "");
  const tail = alnum.slice(-4);
  return `••••${tail}`;
}

/** Hash truncation for display: `7f2a…91c`. Monospace, 8 characters. */
export function shortHash(hash: string | null | undefined, head = 4, tail = 3): string {
  if (!hash) return "—";
  if (hash.length <= head + tail + 1) return hash;
  return `${hash.slice(0, head)}…${hash.slice(-tail)}`;
}

/** `m:ss` for the cooldown bar. */
export function formatCountdown(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Seconds ago / duration phrasing for the timeline. */
export function formatAgo(iso: string | null | undefined, nowIso?: string): string {
  if (!iso) return "—";
  const then = Date.parse(iso);
  const now = nowIso ? Date.parse(nowIso) : Date.now();
  if (Number.isNaN(then)) return iso;
  const diffMs = now - then;
  const mins = Math.round(diffMs / 60000);
  if (Math.abs(mins) < 1) return "just now";
  if (Math.abs(mins) < 60) return `${mins}m ${mins < 0 ? "ahead" : "ago"}`;
  const hours = Math.round(mins / 60);
  if (Math.abs(hours) < 24) return `${hours}h ${hours < 0 ? "ahead" : "ago"}`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}
