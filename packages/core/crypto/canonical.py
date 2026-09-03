"""B1 — canonical serialization. [NOVEL-N10a, first half]

Everything binds to this: the transaction fingerprint, the capability-token MAC, the
policy hash, and Team C's independent mirror in `contracts/CANONICAL_JSON_VECTORS.json`.
Freeze it early or every later module has to be rewritten (Team B §2).

Four rules, in the order they bite:

1. Money is an INTEGER number of minor units. A float anywhere in the pre-image is a
   TypeError, not a rounded value. 0.1 + 0.2 must never be able to change a hash.
2. Strings are Unicode NFC before they are hashed. "Kalyani" typed on macOS and on
   Windows are the same payee.
3. A key that is present-and-null hashes differently from a key that is absent: null
   becomes the explicit sentinel U+0000.
4. Key order, whitespace and escaping are fixed: sorted keys, `(",", ":")`,
   `ensure_ascii=False`. The bytes are the contract, not the dict.
"""

from __future__ import annotations

import json
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

#: A present-but-null value. Distinct from an absent key and from the empty string.
NULL_SENTINEL = chr(0)  # U+0000


class NonCanonicalValue(TypeError):
    """Raised for any value that cannot be canonicalised without losing information."""


def _norm(value: Any, *, path: str = "$") -> Any:
    """Normalise one value into a canonically-serialisable form."""
    # bool before int: isinstance(True, int) is True in Python.
    if isinstance(value, bool):
        return value

    if value is None:
        return NULL_SENTINEL

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        raise NonCanonicalValue(
            f"{path}: float {value!r} in a canonical pre-image. Money must be an integer "
            "number of minor units (paise); non-money reals must be pre-rounded to int."
        )

    if isinstance(value, Decimal):
        raise NonCanonicalValue(
            f"{path}: Decimal {value!r} in a canonical pre-image. Convert to integer "
            "minor units first."
        )

    if isinstance(value, Enum):
        return _norm(value.value, path=path)

    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)

    if isinstance(value, datetime):
        raise NonCanonicalValue(
            f"{path}: datetime {value!r} must be rendered as an ISO-8601 string with an "
            "explicit UTC offset before canonicalisation (see clock.iso)."
        )

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, bytes):
        raise NonCanonicalValue(f"{path}: raw bytes are not canonicalisable; hex-encode first.")

    if isinstance(value, (list, tuple)):
        return [_norm(v, path=f"{path}[{i}]") for i, v in enumerate(value)]

    if isinstance(value, dict):
        out = {}
        for k in sorted(value):
            if not isinstance(k, str):
                raise NonCanonicalValue(f"{path}: non-string key {k!r}")
            out[unicodedata.normalize("NFC", k)] = _norm(value[k], path=f"{path}.{k}")
        return out

    raise NonCanonicalValue(f"{path}: {type(value).__name__} is not canonicalisable")


def canonical_str(obj: Any) -> str:
    """The canonical text form. Team C mirrors this; it does not import it."""
    return json.dumps(
        _norm(obj),
        separators=(",", ":"),
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )


def canonical_bytes(obj: Any) -> bytes:
    """The canonical byte form — the only thing that is ever hashed or MAC'd."""
    return canonical_str(obj).encode("utf-8")


def project(fields: dict, keys: tuple[str, ...]) -> dict:
    """Pick exactly `keys` out of `fields`.

    A missing key is an error, not an implicit null: rule 3 above only holds if the
    caller has to say `None` out loud.
    """
    missing = [k for k in keys if k not in fields]
    if missing:
        raise KeyError(
            f"canonical pre-image is missing required field(s): {', '.join(sorted(missing))}. "
            "Pass an explicit None if the value is genuinely absent."
        )
    return {k: fields[k] for k in keys}


def to_minor_units(amount, *, currency: str = "INR") -> int:
    """Convert a rupee-denominated value to integer paise, refusing anything lossy.

    Accepts int/str only. A float is refused on purpose (Team B §26 trap #2): callers
    that have a float have already lost precision somewhere upstream.
    """
    exponent = 0 if currency.upper() in _ZERO_DECIMAL else 2
    factor = 10**exponent
    if isinstance(amount, bool):
        raise NonCanonicalValue("bool is not an amount")
    if isinstance(amount, int):
        return amount * factor
    if isinstance(amount, str):
        s = amount.strip().replace(",", "").replace("_", "")
        if "." not in s:
            return int(s) * factor
        whole, _, frac = s.partition(".")
        if len(frac) > exponent:
            raise NonCanonicalValue(
                f"{amount!r} has more precision than {currency} minor units allow; "
                "never silently round money."
            )
        frac = frac.ljust(exponent, "0")
        sign = -1 if whole.startswith("-") else 1
        return sign * (abs(int(whole or 0)) * factor + int(frac or 0))
    raise NonCanonicalValue(
        f"{type(amount).__name__} is not an accepted amount type; pass int paise or a string."
    )


_ZERO_DECIMAL = {"JPY", "KRW", "VND", "CLP", "ISK"}
