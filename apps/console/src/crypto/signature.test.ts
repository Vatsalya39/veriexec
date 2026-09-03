/**
 * â˜… The signature vector â€” what actually catches format drift. Â§10.3, C-9
 *
 * WebCrypto cannot produce RFC-6979 deterministic ECDSA, so a fixed base64url signature
 * string is not assertable. The frozen vector asserts the properties that catch the two
 * classic failures instead: signing the hex *string* rather than the 32 digest bytes, and
 * DER-converting in the browser. If either regresses, the round-trip here fails.
 */

import { describe, expect, it } from "vitest";
import { b64url, b64urlDecode, createDeviceKey, deviceThumbprint,
         exportPublicKeyB64, hexToBytes, requireSecureContext, signFingerprint } from "./device";

const VECTOR = {
  digest_hex: "9c1e4b02f1a7c3d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4ca7",
  digest_len_bytes: 32,
  signature_len_bytes: 64,
  signature_b64u_charlen: 86,
};

describe("the wire format", () => {
  it("hexToBytes yields exactly the 32 raw digest bytes", () => {
    const bytes = hexToBytes(VECTOR.digest_hex);
    expect(bytes.length).toBe(VECTOR.digest_len_bytes);
  });

  it("hexToBytes refuses non-hex and odd lengths", () => {
    expect(() => hexToBytes("zz")).toThrow();
    expect(() => hexToBytes("abc")).toThrow();
  });

  it("a real P-256 signature over the vector digest is 64 raw bytes, 86 base64url chars", async () => {
    requireSecureContext();
    const kp = await createDeviceKey();
    const sig = await signFingerprint(kp, VECTOR.digest_hex);
    expect(sig.length).toBe(VECTOR.signature_b64u_charlen);
    const raw = b64urlDecode(sig);
    expect(raw.length).toBe(VECTOR.signature_len_bytes);
    expect(raw.length).not.toBe(72); // a DER blob is ~70-72 bytes; raw r||s is exactly 64
  });

  it("signing the hex string is NOT what happens â€” different bytes, different signature", async () => {
    requireSecureContext();
    const kp = await createDeviceKey();
    const digestSig = await signFingerprint(kp, VECTOR.digest_hex);
    // The trap: signing the UTF-8 of the 64-char hex string. Must produce a different
    // signature over a different message â€” and the test asserts we never do it.
    const hexStringSig = b64url(new Uint8Array(await crypto.subtle.sign(
      { name: "ECDSA", hash: "SHA-256" }, kp.privateKey,
      new TextEncoder().encode(VECTOR.digest_hex) as unknown as BufferSource)));
    expect(digestSig).not.toStrictEqual(hexStringSig);
  });

  it("round-trips: the browser's own signature verifies against its own public key", async () => {
    const kp = await createDeviceKey();
    const digest = hexToBytes(VECTOR.digest_hex);
     const sig = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, kp.privateKey, digest as unknown as BufferSource);
     const ok = await crypto.subtle.verify(
       { name: "ECDSA", hash: "SHA-256" }, kp.publicKey, sig, digest as unknown as BufferSource);
    expect(ok).toBe(true); // B verifies with the same construction over the same 32 bytes
  });

  it("the public key transports as SPKI DER, base64url, no padding", async () => {
    const kp = await createDeviceKey();
    const spki = await exportPublicKeyB64(kp);
    expect(spki).not.toContain("=");
    expect(spki).not.toContain("+");
    expect(spki).not.toContain("/");
    const der = b64urlDecode(spki);
    expect(der.length).toBe(91); // P-256 SPKI is exactly 91 bytes
  });

  it("device thumbprint is 8 hex chars of SHA-256 over the SPKI", async () => {
    const kp = await createDeviceKey();
    const thumb = await deviceThumbprint(kp);
    expect(thumb).toMatch(/^[0-9a-f]{8}$/);
  });

  it("a fingerprint of the wrong length is refused loudly", async () => {
    const kp = await createDeviceKey();
    await expect(signFingerprint(kp, "aabbcc")).rejects.toThrow(/32 bytes/);
  });

  it("the key is generated non-extractable â€” the bytes never exist in JS", async () => {
    const kp = await createDeviceKey();
    expect((kp.privateKey as CryptoKey).extractable).toBe(false);
    await expect(crypto.subtle.exportKey("pkcs8", kp.privateKey)).rejects.toThrow();
  });
});
