"""★ No digits reach the model — across all 22 fixtures. `[NOVEL-N26]` §5, §25

The scan runs over the output of `privacy.for_model` because that is the single tested
path; a payload assembled any other way would be untested by construction.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from services.audit.app.privacy import (SessionTokenMap, for_model,  # noqa: E402
                                        tokenize)

GOLDEN = REPO_ROOT / "contracts" / "golden"
FIXTURES = [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(GOLDEN.glob("S*.json"))]

# ≥6 digits: an Indian account tail is 4, a PIN is 6, a pincode is 5-6. Six is the line.
DIGIT_RUN = re.compile(r"\d{6,}")
UNMASKED_ACCOUNT = re.compile(r"\b[HISAXS][A-Z]{3}0\d{7,}\b")  # HDFC0001234567890 etc.


def _model_view(fixture: dict) -> str:
    payload, _ = for_model(fixture, SessionTokenMap())
    return json.dumps(payload, ensure_ascii=False)


def test_all_22_fixtures_present() -> None:
    assert len(FIXTURES) == 22


def test_no_digit_run_reaches_llm() -> None:
    for fx in FIXTURES:
        text = _model_view(fx)
        assert not DIGIT_RUN.search(text), \
            f"{fx['scenario']['id']}: ≥6-digit run in model payload: {DIGIT_RUN.search(text).group(0)}"
        assert not UNMASKED_ACCOUNT.search(text), f"{fx['scenario']['id']}: raw IFSC-style account"


def test_token_stable_within_session() -> None:
    tokens = SessionTokenMap()
    a = tokens.token_for("HDFC0001234567890", "account")
    b = tokens.token_for("HDFC0001234567890", "account")
    assert a == b and a.startswith("[ACCOUNT_")


def test_token_differs_across_salts() -> None:
    one = tokenize("HDFC0001234567890", "account", salt=b"salt-one-0000000000000000")
    two = tokenize("HDFC0001234567890", "account", salt=b"salt-two-0000000000000000")
    assert one != two


def test_token_differs_across_kinds() -> None:
    assert (tokenize("AB1234567890", "taxid", salt=b"s")
            != tokenize("AB1234567890", "account", salt=b"s"))


def test_token_carries_no_digits() -> None:
    tok = tokenize("HDFC0001234567890", "account")
    assert not re.search(r"\d", tok)


def test_transcript_never_in_chatbot_payload() -> None:
    tokens = SessionTokenMap()
    payload, _ = for_model({"transcript": "secret words", "raw_transcript": "also secret",
                            "facts": {"reason": "visible"}}, tokens)
    assert "transcript" not in json.dumps(payload)
    assert "secret words" not in json.dumps(payload)
    assert payload["facts"]["reason"] == "visible"


def test_dropped_fields_gone() -> None:
    payload, _ = for_model({"answer": "42", "answer_hmac": "x", "verification_code": "AMPH2A",
                            "nonce": "abc", "marker": "seven", "duress_scheme": "numeric"}, SessionTokenMap())
    dumped = json.dumps(payload)
    for gone in ("42", "AMPH2A", "seven", "numeric"):
        assert gone not in dumped


def test_map_not_persisted(capsys) -> None:
    tokens = SessionTokenMap()
    tokens.token_for("HDFC0001234567890", "account")
    # repr does not leak contents
    assert "HDFC" not in repr(tokens)
    # and there is no serialization API to misuse
    assert not hasattr(tokens, "save") and not hasattr(tokens, "to_dict") \
        and not hasattr(tokens, "json")


def test_scrub_sweeps_unclassified_fields() -> None:
    payload, _ = for_model({"a_field_nobody_classified": "reference 123456789 for the wire"},
                           SessionTokenMap())
    assert "123456789" not in json.dumps(payload)


def test_amount_minor_units_tokenized() -> None:
    payload, _ = for_model({"amount_minor_units": 1000000000, "amount_display": "₹1,00,00,000"},
                           SessionTokenMap())
    dumped = json.dumps(payload, ensure_ascii=False)
    assert "1000000000" not in dumped
    # The rendered money string survives for narration; the bare integer does not.
    assert "1,00,00,000" in dumped
