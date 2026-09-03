"""LLM output parser paranoia — every malformed shape must degrade, never raise."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.signal_intel.extract.llm import (coerce_extract, llm_extract,  # noqa: E402
                                          NullClient, parse_llm_json)

GOOD = '{"action": "TRANSFER", "urgency": "HIGH", "beneficiary": "Kalyani Forge", "secrecy_flags": ["confidential"]}'


def test_fenced_output():
    assert parse_llm_json(f"```json\n{GOOD}\n```") is not None


def test_fenced_no_lang():
    assert parse_llm_json(f"```\n{GOOD}\n```") is not None


def test_prose_preamble():
    assert parse_llm_json(f"Here is the extraction:\n{GOOD}") is not None


def test_trailing_text():
    assert parse_llm_json(f"{GOOD}\nHope that helps!") is not None


def test_truncated_json():
    assert parse_llm_json('{"action": "TRANSFER", "urgency":') is None


def test_wrong_types_coerced():
    obj = parse_llm_json('{"action": 42, "urgency": "EXTREME", "beneficiary": 7, "secrecy_flags": "x"}')
    c = coerce_extract(obj)
    assert c["action"] == "OTHER" and c["urgency"] == "LOW"
    # primitives are string-cast, not dropped (resilience fix)
    assert c["beneficiary"] == "7"
    assert c["secrecy_flags"] == ["x"] or c["secrecy_flags"] == []  # string input coerced-or-dropped


def test_numeric_primitives_cast_not_dropped():
    c = coerce_extract({"action": "TRANSFER", "urgency": "HIGH",
                        "beneficiary": 123, "amount_raw_span": 2.5})
    assert c["beneficiary"] == "123"
    assert c["amount_raw_span"] == "2.5"


def test_junk_types_still_none():
    c = coerce_extract({"action": "TRANSFER", "urgency": "HIGH",
                        "beneficiary": ["Global"], "destination_account": {"a": 1},
                        "purpose": True})
    assert c["beneficiary"] is None and c["destination_account"] is None
    assert c["purpose"] is None  # bools are junk, not strings


def test_empty_string():
    assert parse_llm_json("") is None


def test_none_raw():
    assert parse_llm_json(None) is None  # type: ignore[arg-type]


def test_null_client_unavailable():
    res, status = llm_extract(NullClient(), "transfer Rs 10 lakh", "n1")
    assert res is None and status == "unavailable"


def test_coerce_clamps_secrecy_list():
    c = coerce_extract({"action": "TRANSFER", "urgency": "HIGH",
                        "secrecy_flags": [f"flag{i}" for i in range(50)]})
    assert len(c["secrecy_flags"]) <= 10
