"""Canonical JSON against the shared vector file. §25

`contracts/CANONICAL_JSON_VECTORS.json` is the contract between C's copy of `canonical.py`
and B's. Every `canonical` string and `sha256_c` digest must reproduce byte for byte; the
`sha256_b` column stays null until B fills it from an independent run (C-8 in CHANGES.md —
copying C's digest across would defeat the file's entire purpose).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from services.audit.app.canonical import (NonCanonicalValue, canonical,  # noqa: E402
                                          canonical_bytes, sha256_hex)

VECTORS = json.loads((REPO_ROOT / "contracts" / "CANONICAL_JSON_VECTORS.json")
                     .read_text(encoding="utf-8"))["vectors"]


@pytest.mark.parametrize("vector", VECTORS, ids=[v["name"] for v in VECTORS])
def test_vector_reproduces(vector: dict) -> None:
    assert canonical(vector["input"]) == vector["canonical"]
    assert sha256_hex(vector["input"]) == vector["sha256_c"]


def test_b_columns_still_null() -> None:
    """If B has filled `sha256_b`, delete this test and add one asserting agreement — the
    vector file is doing its job the moment this fails."""
    for v in VECTORS:
        assert v["sha256_b"] is None, f"{v['name']}: B filled the column; update this suite"


def test_float_raises_with_path() -> None:
    with pytest.raises(NonCanonicalValue) as exc:
        canonical({"weights": {"beneficiary": 0.20}})
    assert "weights.beneficiary" in str(exc.value)


def test_keys_sorted_at_every_depth() -> None:
    assert canonical({"b": {"d": 1, "c": 2}, "a": 3}) == '{"a":3,"b":{"c":2,"d":1}}'


def test_no_whitespace() -> None:
    assert " " not in canonical({"a": [1, 2], "b": {"c": None}})


def test_explicit_null_preserved() -> None:
    assert canonical({"x": None}) == '{"x":null}'


def test_bool_stays_bool_not_int() -> None:
    assert canonical({"a": True, "b": 1}) == '{"a":true,"b":1}'


def test_nfc_normalization_applied() -> None:
    # U+0041 U+030A decomposes to U+00C5 under NFC.
    assert canonical({"k": "A\u030A"}) == '{"k":"Å"}'


def test_bytes_are_utf8_of_the_string() -> None:
    assert canonical_bytes({"beneficiary": "Rüdiger"}) == '{"beneficiary":"Rüdiger"}'.encode("utf-8")
