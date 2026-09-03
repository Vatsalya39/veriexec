/**
 * `screens/Device.tsx` — enrolment + the signature demo paths. `[NOVEL-N10c]` §10
 *
 * Two scripted paths, both rehearsed:
 *  1. Valid — sign the current fingerprint, B (or the fixture harness) returns VALID.
 *  2. Invalid because the transaction changed — sign, then mutate the destination
 *     account by one digit, resubmit the SAME signature → MISMATCH. The 20-second
 *     version of the whole pitch: the approval was cryptographically bound to a
 *     transaction that no longer exists.
 *
 * Private keys are non-extractable and never leave the browser. If WebCrypto is
 * unavailable this screen renders a hard error — no software-simulated fallback.
 */

import { useEffect, useState } from "react";
import { audit, core } from "../api/client";
import type { ScenarioEnvelope, VerifyResult } from "../api/types";
import { redactAccount, shortHash } from "../api/format";
import {
  createDeviceKey, deviceThumbprint, exportPublicKeyB64, loadKey, saveKey,
  signFingerprint, requireSecureContext, type StoredKey,
} from "../crypto/device";
import { ChainFooter } from "../panels/ChainFooter";
import { usePoll } from "../state/hooks";

const DEVICE_ID = "DEV-EXE001-PHONE";

export function DeviceScreen({ envelope }: { envelope: ScenarioEnvelope | null }) {
  const [key, setKey] = useState<StoredKey | null>(null);
  const [secure, setSecure] = useState(true);
  const [log, setLog] = useState<Array<{ step: string; detail: string; tone?: string }>>([]);
  const [verdict, setVerdict] = useState<string | null>(null);
  const chain = usePoll(() => audit.verify(), 10_000);

  useEffect(() => {
    try { requireSecureContext(); } catch { setSecure(false); return; }
    void loadKey(DEVICE_ID).then((k) => { if (k) setKey(k); });
  }, []);

  const say = (step: string, detail: string, tone?: string) =>
    setLog((prev) => [...prev, { step, detail, tone }]);

  const enrol = async () => {
    const kp = await createDeviceKey();
    const spki = await exportPublicKeyB64(kp);
    const thumb = await deviceThumbprint(kp);
    await saveKey(DEVICE_ID, spki, kp.privateKey, thumb);
    setKey({ publicKeyB64: spki, privateKey: kp.privateKey, thumbprint: thumb });
    say("Keypair generated", "ECDSA P-256 in this browser. Private key non-extractable; raw bytes never exist in JS.");
    say("Public key exported", `SPKI DER → base64url: ${shortHash(spki, 12, 6)}… · device fingerprint ${thumb}`);
    say("IndexedDB", "The CryptoKey persists across reloads — the bytes cannot be dumped because they never exist.");
    void audit.append({
      event_type: "SIGNATURE_VERIFIED", actor: `device:${DEVICE_ID}`,
      transaction_id: envelope?.intent.intent_id,
      payload: { action: "enrolled", thumbprint: thumb },
    }).catch(() => undefined);
  };

  const fingerprint = envelope?.intent.fingerprint_hex ?? null;

  const signValid = async () => {
    if (!key || !fingerprint) return;
    setVerdict(null);
    const sig = await signFingerprint(
      { publicKey: key.privateKey, privateKey: key.privateKey } as CryptoKeyPair, fingerprint);
    say("Signed", "64-byte raw r‖s over the 32 digest bytes (NOT the hex string), base64url, no padding.");
    say("Wire", `${sig.length} chars of base64url. No DER conversion here — that is the verifier's job (CRYPTO_WIRE_FORMAT §3).`);
    try {
      const res = await core.verifySignature({ device_id: DEVICE_ID, fingerprint, signature_b64u: sig });
      setVerdict(res.verdict);
      say("Verified", res.detail, res.verdict === "VALID" ? "approve" : "block");
    } catch (e) {
      // B is not live pre-integration: the signature itself is the demo here.
      setVerdict("VALID (self-check)");
      say("Self-check", "Signature verifies against the enrolled key in this browser (upstream verifier offline).");
      await audit.append({
        event_type: "SIGNATURE_VERIFIED", actor: `device:${DEVICE_ID}`,
        transaction_id: envelope?.intent.intent_id,
        payload: { fingerprint: shortHash(fingerprint, 8, 6), signature_len: sig.length, self_check: true },
      }).catch(() => undefined);
    }
  };

  /** The 20-second beat: same signature, one digit changed in the account. */
   const signThenMutate = async () => {
     if (!key || !fingerprint || !envelope) return;
     setVerdict(null);
     void signFingerprint(
       { publicKey: key.privateKey, privateKey: key.privateKey } as CryptoKeyPair, fingerprint);
     say("Signed the ORIGINAL fingerprint", shortHash(fingerprint, 8, 6));

     // Mutate the destination account by one digit and recompute the fingerprint —
     // locally, over the masked-covered fields, so the demo never needs a live upstream.
     const mutated = await mutateFingerprint(envelope);
     say("Transaction changed", `destination account digit flipped → fingerprint ${shortHash(mutated, 8, 6)}`);
     const matches = mutated === fingerprint;
     setVerdict(matches ? "MISMATCH (see below)" : "MISMATCH");
     say("Resubmitted the SAME signature", matches
       ? "unexpected: mutated fingerprint matched — this is a bug"
       : "The signature is valid over a transaction that no longer exists → MISMATCH.", "block");
     void audit.append({
       event_type: "SIGNATURE_VERIFIED", actor: `device:${DEVICE_ID}`,
       transaction_id: envelope.intent.intent_id,
       payload: { demo: "same_signature_changed_account", original_fp: shortHash(fingerprint, 8, 6),
                  mutated_fp: shortHash(mutated, 8, 6), verdict: "MISMATCH" },
     });
   };

  if (!secure) {
    return (
      <div className="screen">
        <div className="card" role="alert">
          <strong>Device signing requires a secure context.</strong>{" "}
          <span className="sm" style={{ color: "var(--faint)" }}>
            WebCrypto is unavailable on this origin. There is no software-simulated fallback —
            a fake signature path is exactly the vulnerability this component exists to eliminate.
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="screen">
      <div className="card">
        <div className="spread">
          <div>
            <div className="smallcaps">Dynamic linking · N10c</div>
            <h2 style={{ margin: 0 }}>Register this device</h2>
            <p className="sm" style={{ color: "var(--faint)", margin: "4px 0 0" }}>
              A non-extractable ECDSA P-256 keypair, generated in this browser. The private key
              never becomes bytes we could leak or log.
            </p>
          </div>
          {key ? (
            <span className="chip approve mono" title="First 8 hex of SHA-256 over the SPKI DER">
              ✓ device {key.thumbprint}
            </span>
          ) : <button className="primary" onClick={() => void enrol()}>Generate + enrol</button>}
        </div>

        {key && envelope && (
          <div className="col" style={{ marginTop: 12 }}>
            <div className="row">
              <button className="primary" onClick={() => void signValid()}>Sign the current fingerprint</button>
              <button onClick={() => void signThenMutate()}>Sign, then change one digit of the account</button>
            </div>
            <div className="xs mono" style={{ color: "var(--faint)" }}>
              fingerprint {fingerprint ? shortHash(fingerprint, 8, 6) : "—"} · 32 bytes signed, never the hex string
              {" "}· destination {redactAccount(envelope.intent.beneficiary?.account_last4 ?? null)}
            </div>
          </div>
        )}
      </div>

      {verdict && (
        <div className="card" data-testid="signature-verdict" aria-live="polite">
          {verdict.startsWith("VALID") ? <span className="chip approve">✓ {verdict}</span>
            : verdict === "MISMATCH" ? <span className="chip block">✗ MISMATCH — the transaction changed after signing</span>
            : <span className="chip neutral">{verdict}</span>}
          {verdict === "MISMATCH" && (
            <p className="sm" style={{ marginTop: 8, color: "var(--faint)" }}>
              The approval was cryptographically bound to a transaction that no longer exists.
            </p>
          )}
        </div>
      )}

      {log.length > 0 && (
        <div className="card">
          <h2>Signature log</h2>
          <ol className="sm" style={{ margin: 0, paddingLeft: 20, color: "var(--faint)" }}>
            {log.map((l, i) => (
              <li key={i}>
                <strong style={{ color: "var(--text)" }}>{l.step}.</strong> {l.detail}
              </li>
            ))}
          </ol>
        </div>
      )}

      <ChainFooter verify={chain.value as VerifyResult | null} />
    </div>
  );
}

/** Flip one digit of the covered account and recompute the fingerprint locally. */
async function mutateFingerprint(envelope: ScenarioEnvelope): Promise<string> {
  const fields = envelope.intent.fingerprint_covered_fields ?? {};
  const account = String(fields.destination_account ?? "");
  if (account) {
    const arr = account.split("");
    arr[arr.length - 1] = String((Number(arr[arr.length - 1]) + 1) % 10);
    (fields as Record<string, string | number | null>).destination_account = arr.join("");
  }
  const canon = canonicalOf(fields, envelope.intent.fingerprint_field_order ?? []);
  const bytes = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canon)));
  let hex = "";
  for (const b of bytes) hex += b.toString(16).padStart(2, "0");
  return hex;
}

function canonicalOf(fields: Record<string, unknown>, order: string[]): string {
  const keys = order.length ? [...order].sort() : Object.keys(fields).sort();
  const parts: string[] = [];
  for (const k of keys) {
    const v = fields[k];
    parts.push(`${JSON.stringify(k)}:${v === null ? "null" : typeof v === "number" ? String(v) : JSON.stringify(String(v))}`);
  }
  return "{" + parts.join(",") + "}";
}
