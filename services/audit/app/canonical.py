"""Canonical JSON — the one serialization the whole repo hashes over.

These rules are Team B's (`packages/core/crypto/canonical.py`); this file is a *copy*, not an
import, because C must not reach across an ownership boundary. `contracts/CANONICAL_JSON_VECTORS.json`
is the contract between the two copies: `test_canonical_json.py` reproduces every `canonical` string
and `sha256_c` digest in it, and B fills the `sha256_b` column from an independent run at G0. A
vector where the two disagree is an integration bug caught at hour 1 instead of hour 18.

The rules, all of which some implementation somewhere gets wrong:

1. Keys sorted lexicographically **at every depth**.
2. No whitespace — separators are `","` and `":"`.
3. `ensure_ascii=False`. Non-ASCII is emitted as UTF-8, never as `\\uXXXX`.
4. Strings are NFC-normalized before serialization.
5. Explicit nulls are preserved. A missing key and a null key must not serialize identically.
6. Money is integer minor units. **A float anywhere raises** — it never coerces.
7. Output is UTF-8 encoded, then SHA-256'd, then hex-encoded lowercase.

Rule 6 is the one that earns its keep. `0.1 + 0.2` is not `0.3`, and a fingerprint computed over a
float is a fingerprint that fails to verify on a different CPU for reasons nobody will find at 3 a.m.
Raising is louder than rounding and the caller always knows which field it is.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any


class NonCanonicalValue(ValueError):
    """A value that cannot be canonically serialized. Carries the JSON path to the offender."""


def _norm(obj: Any, path: str = "$") -> Any:
    """Recursively NFC-normalize strings and reject anything not canonically representable."""
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, bool) or obj is None:
        # bool before int: bool is a subclass of int and `True` must stay `true`, not become `1`.
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        raise NonCanonicalValue(
            f"float at {path}: money is integer minor units and hashes must be exact. "
            f"Convert to int minor units at the boundary, not here.")
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if not isinstance(k, str):
                raise NonCanonicalValue(f"non-string key at {path}: {k!r}")
            nk = unicodedata.normalize("NFC", k)
            if nk in out:
                # Two distinct keys that normalize to the same string would silently drop one.
                raise NonCanonicalValue(f"keys collide after NFC at {path}: {k!r}")
            out[nk] = _norm(v, f"{path}.{nk}")
        return out
    if isinstance(obj, (list, tuple)):
        return [_norm(v, f"{path}[{i}]") for i, v in enumerate(obj)]
    raise NonCanonicalValue(f"unserializable {type(obj).__name__} at {path}")


def canonical(obj: Any) -> str:
    """The canonical string form. Sorted, whitespace-free, NFC, UTF-8-literal."""
    return json.dumps(_norm(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_bytes(obj: Any) -> bytes:
    return canonical(obj).encode("utf-8")


def sha256_hex(obj: Any) -> str:
    """Lowercase hex SHA-256 over the canonical UTF-8 bytes."""
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def digest_bytes(obj: Any) -> bytes:
    """The raw 32 bytes. These — not the hex string — are what a device signs (CRYPTO_WIRE_FORMAT §2)."""
    return hashlib.sha256(canonical_bytes(obj)).digest()
