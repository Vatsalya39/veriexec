# CRYPTO_WIRE_FORMAT — frozen at G0

Owner of this file: **Team C drafts, Team B signs off.** Both halves of `N10` depend on it.
Nothing here may change after G1 without a `docs/CHANGES.md` entry initialled by both teams.

## 1. Key material

| Item | Format |
|---|---|
| Curve | ECDSA **P-256** (`prime256v1` / `secp256r1`) |
| Hash | SHA-256 |
| Private key | Generated in the browser, `extractable: false`, stored as a `CryptoKey` in IndexedDB. Never serialized, never logged. |
| Public key transport | **SPKI DER, base64url, no padding.** Team B loads it with `load_der_public_key(b64url_decode(s))`. |
| Device fingerprint (display only) | First 8 hex characters of `SHA-256(SPKI DER bytes)`. Rendered so a human can match a device across screens. It is **not** an identifier B trusts. |

## 2. The signed bytes

> The signed message is the **32 raw bytes** of the transaction fingerprint digest.

Team B transports the fingerprint as a 64-character lowercase hex string (`fingerprint_hex`).
The console converts it with `hexToBytes()` and signs the resulting 32-byte `Uint8Array`.

Explicitly **not** signed: the 64-character hex string, its UTF-8 encoding, the assessment JSON,
any canonical serialization. Signing the hex string produces a cryptographically valid signature
over the wrong message; it verifies as `INVALID` and looks like a key-handling bug for two hours.

WebCrypto note: `crypto.subtle.sign({name:"ECDSA", hash:"SHA-256"}, key, digest)` hashes its input.
So the value actually signed is `SHA-256(digest_bytes)`. That is fine and it is **deliberate** — B
verifies with the same construction (`ec.ECDSA(hashes.SHA256())` over the same 32 bytes). What
matters is that both sides feed in the identical 32 bytes. Do not "fix" this by pre-hashing on
one side only.

## 3. The signature

| Property | Value |
|---|---|
| Encoding on the wire | base64url of the **64-byte raw `r‖s` pair**, no padding |
| Produced by | `crypto.subtle.sign` — WebCrypto returns exactly this raw pair |
| Consumed by | Team B, which converts to DER before verifying |

```python
# Team B side — the only place a conversion happens.
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
raw = b64url_decode(signature_b64u)
if len(raw) != 64:
    return SigVerdict("MALFORMED", "ECDSA P-256 signature must be 64 bytes (r||s)")
der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
```

**The browser must not convert to DER.** If both sides convert, B re-wraps a DER blob as if it
were a raw pair and every signature fails with no useful error.

## 4. Request and response shapes

```
POST /v1/device/enrol
  { "device_id": "DEV-EXE001-PHONE", "executive_id": "EXE-001",
    "public_key_spki_b64u": "...", "label": "iPhone 15 (registered authenticator)" }
  -> { "device_id": "...", "thumbprint": "9f3c1a02", "enrolled_at": "ISO-8601 +05:30" }

POST /v1/signature/verify
  { "device_id": "DEV-EXE001-PHONE", "fingerprint": "<64 hex>", "signature_b64u": "<86 chars>" }
  -> { "verdict": "VALID | INVALID | MALFORMED | UNKNOWN_DEVICE | REVOKED | MISMATCH",
       "detail": "human-readable sentence",
       "field_deltas": [ { "field": "...", "expected": "...", "presented": "...", "severity": "critical" } ] }
```

`MISMATCH` is returned when the signature verifies against the registered key but the fingerprint
it covers is not the fingerprint of the transaction now being executed. That is the demo beat: the
approval was cryptographically bound to a transaction that no longer exists.

## 5. Frozen cross-language test vector

`test_signature_roundtrip` (Team B owns the runner) signs this digest with the fixed development
key under `dev/keys/` and asserts the exact base64url string. Any drift in encoding, curve or
signed-bytes choice fails this test loudly instead of failing at demo time.

```json
{
  "digest_hex": "9c1e4b02f1a7c3d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4ca7",
  "digest_len_bytes": 32,
  "signature_len_bytes": 64,
  "signature_b64u_charlen": 86,
  "note": "ECDSA is randomized: r||s differs per signature. The test asserts verify(pub, sig, digest) is true and that len(raw)==64 — it does not assert a fixed signature string. A fixed string is only assertable with RFC-6979 deterministic ECDSA, which WebCrypto does not expose."
}
```

That last note is the honest version. An earlier draft of this file promised a fixed signature
string; WebCrypto cannot produce one, so the vector asserts the properties that actually catch
format drift: byte length, encoding alphabet, and a successful cross-language verify.
