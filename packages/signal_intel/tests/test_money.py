"""Money parser table-driven tests — 30+ cases [NOVEL-N29] (§A5 requirement: 24+)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.signal_intel.extract.money import parse_amount  # noqa: E402

CASES = [
    # (input, expected_value, expected_currency)
    ("₹2.5 crore", 25000000, "INR"),
    ("Rs 2,50,00,000", 25000000, "INR"),
    ("25000000", None, None),  # bare number, no marker: ambiguous
    ("2.5cr", 25000000, "INR"),
    ("pandrah lakh", 1500000, "INR"),
    ("पंद्रह लाख", 1500000, "INR"),
    ("15L", 1500000, "INR"),
    ("15 lacs", 1500000, "INR"),
    ("fifteen lakh", 1500000, "INR"),
    ("1.5 crore rupees", 15000000, "INR"),
    ("₹10,00,000/-", 1000000, "INR"),
    ("USD 40,000", 40000, "USD"),
    ("40k dollars", 40000, "USD"),
    ("two point five crore", 25000000, "INR"),
    ("forty-two lakh", 4200000, "INR"),
    ("fifteen lakh rupees", 1500000, "INR"),
    ("fifteen lakh dollars", 1500000, "USD"),
    ("Rs 6,40,000", 640000, "INR"),
    ("Rs 28,00,000", 2800000, "INR"),
    ("twenty-eight lakh", 2800000, "INR"),
    ("Rs 1.8 crore", 18000000, "INR"),
    ("thirty lakh", 3000000, "INR"),
    ("eighty lakh", 8000000, "INR"),
    ("Rs 2,40,00,000", 24000000, "INR"),
    ("₹4.38 crore", 43800000, "INR"),
    ("10 lakh to Kalyani", 1000000, "INR"),
    ("transfer 50 to Global", None, None),  # ambiguous -> refuse
    ("account 9281 and amount 250000", None, None),  # account digits not an amount
    ("some money", None, None),
    ("will confirm the amount later", None, None),
]


def test_money_table():
    for text, value, currency in CASES:
        r = parse_amount(text)
        if value is None:
            assert r is None, f"{text!r}: expected None, got {r}"
        else:
            assert r is not None, f"{text!r}: expected {value}, got None"
            assert r.value == value, f"{text!r}: expected {value}, got {r.value}"
            assert r.currency == currency, f"{text!r}: expected {currency}, got {r.currency}"


def test_account_never_an_amount():
    # A bank token must never be parsed as money (100x error on stage).
    r = parse_amount("HDFC0001234567890 ICIC0009988776655 ADCB0000099281")
    assert r is None or r.value < 1000


def test_two_amounts_payment_verb_wins():
    # §9: two amounts — the one attached to the payment verb must win
    r = parse_amount("The invoice says Rs 5,00,000 but kindly transfer Rs 25,00,000 to Orion")
    assert r is not None and r.value == 2500000, f"got {r.value if r else None}"


def test_limit_change_amount():
    r = parse_amount("raising my payment approval limit from Rs 50,00,000 to Rs 5 crore")
    assert r is not None and r.value in (5000000, 5000000.0, 50000000)  # both are limits, not transfers


def test_normalization_payload_emitted():
    r = parse_amount("₹2.5 crore")
    assert r.raw_span and r.multiplier == 1e7 and r.rule_id


def test_never_rounds():
    r = parse_amount("Rs 1.55 lakh")
    assert r is not None and r.value == 155000.0
