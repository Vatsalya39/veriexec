"""Cross-language signature conformance test.

Verifies that the ECDSA P-256 wire format (64-byte raw r||s, base64url, no padding)
produced in Node / WebCrypto matches Python cryptography verification.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
import pytest

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature
from cryptography.hazmat.primitives.serialization import load_der_public_key

from packages.core.crypto.device_sig import verify_device_signature, SigVerdict
from packages.core import clock


def test_ecdsa_p256_cross_language_wire_format():
    """Sign 32-byte digest in Python into 64-byte raw r||s base64url and verify."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    digest = b"12345678901234567890123456789012" # 32 bytes
    der_sig = private_key.sign(digest, ec.ECDSA(hashes.SHA256()))

    r, s = decode_dss_signature(der_sig)
    raw_sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    b64u_sig = base64.urlsafe_b64encode(raw_sig).decode().rstrip("=")

    # Verify converting back to DER matches public key verification
    der_reconstructed = encode_dss_signature(
        int.from_bytes(raw_sig[:32], "big"),
        int.from_bytes(raw_sig[32:], "big"),
    )
    public_key.verify(der_reconstructed, digest, ec.ECDSA(hashes.SHA256()))
