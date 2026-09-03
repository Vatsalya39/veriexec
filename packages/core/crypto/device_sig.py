"""B9 — device-signature verification. [NOVEL-N10b]

Team C's console signs the fingerprint with a WebCrypto ECDSA P-256 key held in the
browser. B verifies it server-side. **B verifies; it never generates the signature, and it
never trusts a client-supplied "verified: true".**

The interop trap (§12): WebCrypto `ECDSA` produces a raw `r||s` pair; `cryptography`
expects DER. The wire format is frozen in `contracts/CRYPTO_WIRE_FORMAT.md`:
base64url of the 64-byte raw pair, no padding, signing the 32 raw digest bytes.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

from ..contracts_io import device_keys
from ..config import settings
from datetime import datetime


@dataclass(frozen=True)
class SigVerdict:
    verdict: str            # VALID | INVALID | REVOKED | UNKNOWN_DEVICE | MALFORMED | ABSENT
    reason: str
    device_id: str = ""


#: The ECDSA P-256 `r||s` raw pair, in bytes, before DER conversion.
RAW_SIG_BYTES = 64


def _b64u_decode(s: str) -> bytes:
    """base64url, no padding — re-pad defensively then decode strictly."""
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def verify_device_signature(
    *,
    device_id: str,
    fingerprint_hex: str,
    signature_b64u: str,
    now: datetime,
) -> SigVerdict:
    """Verify against the registered key. Unknown/revoked/malformed are named verdicts
    that policy (HO-6, PC-4) acts on — never silent passes."""
    if not signature_b64u:
        return SigVerdict("ABSENT", "No device signature was presented.", device_id)

    registry = device_keys(now)
    dev = registry.get(device_id)
    if dev is None:
        return SigVerdict("UNKNOWN_DEVICE",
                          f"Device {device_id} is not registered.", device_id)
    if dev.get("revoked"):
        return SigVerdict("REVOKED",
                          f"Device {device_id} was revoked on {dev.get('revoked_at', '?')}.",
                          device_id)

    try:
        raw = _b64u_decode(signature_b64u)
    except (binascii.Error, ValueError):
        return SigVerdict("MALFORMED", "Signature is not valid base64url.", device_id)
    if len(raw) != RAW_SIG_BYTES:
        return SigVerdict("MALFORMED",
                          f"ECDSA P-256 signature must be {RAW_SIG_BYTES} bytes (r||s); "
                          f"got {len(raw)}.", device_id)
    try:
        digest = bytes.fromhex(fingerprint_hex)
    except (binascii.Error, ValueError):
        return SigVerdict("MALFORMED", "Fingerprint is not hex.", device_id)
    if len(digest) != 32:
        return SigVerdict("MALFORMED", "Fingerprint digest must be 32 bytes.", device_id)

    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import (
            decode_dss_signature,
            encode_dss_signature,
        )
        from cryptography.exceptions import InvalidSignature

        spki = _b64u_decode(dev["public_key_spki_b64u"])
        pub = serialization.load_der_public_key(spki)
        r = int.from_bytes(raw[:32], "big")
        s = int.from_bytes(raw[32:], "big")
        try:
            pub.verify(encode_dss_signature(r, s), digest, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature:
            # Some clients emit DER; accept it only when it verifies as DER, so a real
            # signature never fails for format reasons alone (test_der_vs_raw_handled).
            try:
                pub.verify(raw, digest, ec.ECDSA(hashes.SHA256()))
            except InvalidSignature:
                return SigVerdict("INVALID",
                                  "Signature does not verify against the registered key.",
                                  device_id)
        return SigVerdict("VALID",
                          f"Signed by {dev.get('label', device_id)} ({device_id}).",
                          device_id)
    except ImportError:
        # No crypto stack available: NOT a pass. Integration-error, priced as MALFORMED,
        # never silent — a lab without the library must not become an approval.
        return SigVerdict("MALFORMED",
                          "The cryptography library is unavailable; cannot verify locally.",
                          device_id)


def enrol(device_id: str, public_key_spki_b64u: str, *, label: str = "") -> dict:
    """Register a device's public key. Public keys only — private keys never leave the
    browser's non-extractable CryptoKey, and B never stores key material beyond SPKI.

    # MOCKED — in production this writes to the enrolled-device store behind the same
    # interface and requires an operator confirmation; the hackathon build keeps the
    # registry in contracts/device_keys.json for determinism.
    """
    import hashlib
    spki = _b64u_decode(public_key_spki_b64u)
    key_fp = hashlib.sha256(spki).hexdigest()[:16]
    return {
        "device_id": device_id,
        "key_fingerprint": key_fp,
        "label": label or f"Enrolled device {device_id}",
        "note": "MOCKED registry write for the demo build; production persists operator-confirmed enrolment.",
    }
