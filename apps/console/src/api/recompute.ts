/**
 * The console's one sanctioned piece of arithmetic: recomputing a record hash in the
 * browser so a judge can verify the chain themselves (§21.2). The implementation mirrors
 * `services/audit/app/chain.py::compute_record_hash` exactly — sorted keys, no
 * whitespace, NFC, UTF-8 — and `chain_recompute.test.ts` asserts agreement with the
 * server's stored hash on a frozen vector.
 */

const HASHED_FIELDS = ["seq", "record_id", "timestamp", "event_type", "transaction_id",
  "actor", "payload", "policy_version", "policy_hash", "prev_hash"] as const;

function nfc(s: string): string {
  return s.normalize("NFC");
}

/** Canonical JSON: sorted keys at every depth, no whitespace, ensure_ascii=false. */
export function canonicalize(value: unknown): string {
  const out = canon(value);
  return JSON.stringify(out);
}

function canon(value: unknown): unknown {
  if (typeof value === "string") return nfc(value);
  if (value === null || typeof value === "number" || typeof value === "boolean") return value;
  if (Array.isArray(value)) return value.map(canon);
  if (typeof value === "object" && value !== null) {
    const sortedKeys = Object.keys(value as Record<string, unknown>).sort();
    const out: Record<string, unknown> = {};
    for (const k of sortedKeys) out[nfc(k)] = canon((value as Record<string, unknown>)[k]);
    return out;
  }
  throw new Error(`not canonically serializable: ${String(typeof value)}`);
}

export async function sha256Hex(text: string): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)));
  let hex = "";
  for (const b of digest) hex += b.toString(16).padStart(2, "0");
  return hex;
}

/** Recompute a record's hash over the hashed fields, excluding `record_hash` itself. */
export async function recomputeRecordHash(record: Record<string, unknown>): Promise<{ computed: string }> {
  const body: Record<string, unknown> = {};
  for (const f of HASHED_FIELDS) body[f] = record[f];
  return { computed: await sha256Hex(canonicalize(body)) };
}
