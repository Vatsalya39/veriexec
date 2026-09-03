# CRYPTO_WIRE_FORMAT — frozen at G0

Shared contract. Team B verifies, Team C's browser signs. Both sides implement this
document, not each other's code. Any change needs all three teams.

## 1. Algorithm

ECDSA over NIST **P-256** (`prime256v1` / `secp256r1`) with **SHA-256**.
Browser: `{ name: "ECDSA", namedCurve: "P-256" }`, sign with `{ name: "ECDSA", hash: "SHA-256" }`.

## 2. What gets signed — the 32 RAW digest bytes

The signed message is the **32-byte transaction fingerprint digest**, *not* its
64-character hex string.

```js
// Team C (browser)
const fpHex   = assessment.transaction_fingerprint;              // 64 hex chars
const fpBytes = Uint8Array.from(fpHex.match(/../g).map(h => parseInt(h, 16)));  // 32 bytes
const raw     = await crypto.subtle.sign({name:"ECDSA", hash:"SHA-256"}, privKey, fpBytes);
```

```python
# Team B (packages/core/crypto/device_sig.py)
digest = bytes.fromhex(fingerprint_hex)      # 32 bytes
assert len(digest) == 32
```

> WebCrypto hashes the message itself, so it computes `SHA-256(digest_bytes)` and signs
> that. Python must therefore also pass the 32 digest bytes through `ec.ECDSA(SHA256())`
> — i.e. `pub.verify(der_sig, digest, ec.ECDSA(hashes.SHA256()))`. Do **not**
> pre-hash on either side and do **not** use `Prehashed`.

## 3. Signature encoding — base64url of raw `r||s`, no padding

WebCrypto emits the **raw 64-byte concatenation** `r || s` (32 bytes each, big-endian,
left zero-padded). `cryptography` expects **DER**. The wire format is the raw pair;
Team B converts.

```
signature_b64u = base64url_nopad( r(32) || s(32) )     # 86 chars
```

```python
raw = base64.urlsafe_b64decode(sig_b64u + "=" * (-len(sig_b64u) % 4))
if len(raw) != 64:
    return MALFORMED            # never "assume DER", never fall through to VALID
r = int.from_bytes(raw[:32], "big")
s = int.from_bytes(raw[32:], "big")
der = encode_dss_signature(r, s)
```

Rules:
- base64**url** alphabet (`-` and `_`), padding **stripped**. Verifiers must
  re-pad tolerantly; producers must not emit `=`.
- Length `!= 64` after decode ⇒ `MALFORMED` (penalty 60, routes to CHALLENGE).
  Never DER on the wire.

## 4. Public key encoding — SPKI DER, base64url, no padding

This resolves the contradiction between the PEM sample in
`02_TEAM_B_RISK_FUSION_CORE.md §12` and `public_key_spki_b64u` in that same
document's `/v1/device/enrol` signature. **SPKI DER base64url wins**; the PEM sample
is illustrative only.

```js
const spki = await crypto.subtle.exportKey("spki", pubKey);   // ArrayBuffer, DER
const b64u = b64urlNoPad(new Uint8Array(spki));               // ~124 chars for P-256
```

```python
der = base64.urlsafe_b64decode(b64u + "=" * (-len(b64u) % 4))
pub = load_der_public_key(der)          # NOT load_pem_public_key
if not isinstance(pub.curve, ec.SECP256R1):
    return MALFORMED
```

`contracts/device_keys.json` stores `public_key_spki_b64u` only. **No private key ever
leaves the browser.** Dev key material lives in gitignored `dev/keys/`.

## 5. Verdicts and penalties (Team B owns the mapping)

| verdict | when | `device_channel` penalty | effect |
|---|---|---|---|
| `VALID` | signature verifies against an ACTIVE registered key | 0 | — |
| `UNKNOWN_DEVICE` | `device_id` not in the registry | 70 | CHALLENGE at best |
| `REVOKED` | key present, `status != "active"` | 100 | HO-6 ⇒ BLOCK |
| `INVALID` | well-formed but does not verify | 100 | HO-6 ⇒ BLOCK |
| `MALFORMED` | wrong length, bad base64, wrong curve | 60 | CHALLENGE |
| absent | no signature supplied at all | 0 | not evidence either way |

A client-supplied `signature_verified: true` is treated as **absent**. Trust only a
signature this service verified itself.

## 6. Canonical JSON and MACs

Fingerprint pre-images and `CapabilityToken.mac` pre-images use the canonical form in
`contracts/CANONICAL_JSON_VECTORS.json`: sorted keys, `separators=(",", ":")`,
`ensure_ascii=false`, Unicode NFC, integers only for money, and a null rendered as the
explicit sentinel string U+0000 (JSON-escapes to `"\u0000"`) so that a key which is
present-and-null can never hash the same as a key that was absent.

`mac = HMAC-SHA256(key=INTENTLOCK_HMAC_SECRET, msg=canonical(token_without_mac_and_redeemed_at))`,
lower-case hex. Compare with a constant-time compare, never `==`.

Mirror these rules; do not import across the package boundary.
