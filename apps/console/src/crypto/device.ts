/**
 * WebCrypto device keys — real cryptography, not a mocked button. `[NOVEL-N10c]` §10
 *
 * Wire format frozen in `contracts/CRYPTO_WIRE_FORMAT.md` (C-9): SPKI DER base64url for
 * the public key, 64-byte raw `r||s` base64url for the signature, and the **32 raw
 * digest bytes** as the signed message — never the hex string.
 *
 * Private keys are non-extractable (`extractable: false`): the raw bytes never exist in
 * JavaScript, and a non-extractable CryptoKey survives a reload in IndexedDB. If
 * WebCrypto is unavailable (insecure origin) this module throws — there is no software-
 * simulated fallback, because a fake signature path left in is exactly the vulnerability
 * this component exists to eliminate.
 */

const ALG = { name: "ECDSA", namedCurve: "P-256" } as const;

export function requireSecureContext(): void {
  if (typeof crypto === "undefined" || !crypto.subtle) {
    throw new Error("Device signing requires a secure context");
  }
}

export async function createDeviceKey(): Promise<CryptoKeyPair> {
  requireSecureContext();
  // extractable: false — the private key never becomes bytes we could leak or log.
  return crypto.subtle.generateKey(ALG, false, ["sign", "verify"]);
}

export function b64url(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

export function b64urlDecode(s: string): Uint8Array {
  const norm = s.replace(/-/g, "+").replace(/_/g, "/");
  const pad = norm.length % 4 === 0 ? "" : "=".repeat(4 - (norm.length % 4));
  const raw = atob(norm + pad);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export async function exportPublicKeyB64(kp: CryptoKeyPair): Promise<string> {
  const spki = await crypto.subtle.exportKey("spki", kp.publicKey);
  return b64url(new Uint8Array(spki));           // SPKI DER, base64url, no padding
}

export function hexToBytes(hex: string): Uint8Array {
  const clean = hex.trim().toLowerCase().replace(/^0x/, "");
  if (!/^[0-9a-f]*$/.test(clean) || clean.length % 2 !== 0) {
    throw new Error("not a hex string");
  }
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(clean.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

/** Device fingerprint: first 8 hex of SHA-256 over the SPKI DER bytes. Display only. */
export async function deviceThumbprint(kp: CryptoKeyPair): Promise<string> {
  const spki = new Uint8Array(await crypto.subtle.exportKey("spki", kp.publicKey));
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", spki as unknown as BufferSource));
  return b16(digest).slice(0, 8);
}

function b16(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += b.toString(16).padStart(2, "0");
  return s;
}

export async function signFingerprint(kp: CryptoKeyPair, fingerprintHex: string): Promise<string> {
  requireSecureContext();
  const digest = hexToBytes(fingerprintHex);     // 32 bytes, NOT the hex string
  if (digest.length !== 32) throw new Error("fingerprint must be 32 bytes");
  const raw = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, kp.privateKey, digest as unknown as BufferSource);
  const sig = new Uint8Array(raw);
  if (sig.length !== 64) throw new Error(`ECDSA P-256 signature must be 64 bytes, got ${sig.length}`);
  return b64url(sig);                           // 64-byte r||s, base64url, no padding
}

// ---------------------------------------------------------------- IndexedDB persistence

const DB_NAME = "intentlock-device";
const STORE = "keys";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("IndexedDB unavailable"));
  });
}

async function idb<T>(mode: IDBTransactionMode, fn: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await openDb();
  return new Promise<T>((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    const req = fn(tx.objectStore(STORE));
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("IndexedDB request failed"));
    tx.oncomplete = () => db.close();
  });
}

export interface StoredKey {
  publicKeyB64: string;
  privateKey: CryptoKey;
  thumbprint: string;
}

export async function saveKey(deviceId: string, publicKeyB64: string, privateKey: CryptoKey, thumbprint: string): Promise<void> {
  await idb("readwrite", (s) => s.put({ publicKeyB64, privateKey, thumbprint }, deviceId));
}

export async function loadKey(deviceId: string): Promise<StoredKey | null> {
  return idb<StoredKey | null>("readonly", (s) => s.get(deviceId) as IDBRequest<StoredKey | null>);
}

export async function clearKeys(): Promise<void> {
  await idb("readwrite", (s) => s.clear());
}
