"""The two beneficiary registries must not drift. `00_SHARED_CONTEXT.md` §8 [FROZEN]

`contracts/beneficiary_master.json` says of itself: "ids and canonical_name MUST match
contracts/beneficiaries.json byte for byte — a conformance test asserts it." No such test
existed, and the two files had drifted on three names and all seven account numbers, which
is why every payment A extracted read as "account not on record" to B and why the exact
name lookup returned no beneficiary at all for BEN-002, BEN-005 and BEN-007.

§8 names `contracts/beneficiaries.json` as the frozen source, so it wins every tie.
`beneficiary_master.json` is the derived scoring view: it may hold *more* than the frozen
file (aliases, bank codes, dispute counts) but never something different.
"""

from __future__ import annotations

import json
from pathlib import Path

from packages.signal_intel.extract.deterministic import extract_deterministic

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
SAMPLES = Path(__file__).resolve().parents[2] / "packages" / "signal_intel" / "samples"

FROZEN = json.loads((CONTRACTS / "beneficiaries.json").read_text(encoding="utf-8"))
DERIVED = json.loads((CONTRACTS / "beneficiary_master.json").read_text(encoding="utf-8"))
SCENARIOS = json.loads((CONTRACTS / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]

BY_ID = {r["beneficiary_id"]: r for r in FROZEN["beneficiaries"]}
MASTER = {r["id"]: r for r in DERIVED["beneficiaries"]}


def test_both_registries_describe_the_same_beneficiaries():
    assert sorted(MASTER) == sorted(BY_ID), "the two registries list different beneficiary ids"


def test_canonical_names_match_the_frozen_source_byte_for_byte():
    drift = {bid: (rec["name"], MASTER[bid]["canonical_name"])
             for bid, rec in BY_ID.items()
             if rec["name"] != MASTER[bid]["canonical_name"]}
    assert not drift, f"canonical_name drifted from frozen §8: {drift}"


def test_the_frozen_account_is_on_record_in_the_scoring_view():
    """The account string A extracts from a transcript must resolve for B.

    Without this, a routine payment to the payee's own account scores as a payment to an
    account nobody has on file — maximum beneficiary risk on the most ordinary scenario in
    the corpus.
    """
    missing = {bid: (rec["account"], MASTER[bid]["registered_accounts"])
               for bid, rec in BY_ID.items()
               if rec["account"] not in MASTER[bid]["registered_accounts"]}
    assert not missing, f"frozen account absent from registered_accounts: {missing}"


def test_org_payment_count_and_country_match_the_frozen_source():
    """§8's prose makes `org_payment_count` load-bearing for the web of trust, so a second
    copy of it that says something else is a second answer to "has anyone paid this payee"."""
    drift = {}
    for bid, rec in BY_ID.items():
        for frozen_key, derived_key in (("org_payment_count", "org_payment_count"),
                                        ("country", "country")):
            if rec[frozen_key] != MASTER[bid][derived_key]:
                drift[f"{bid}.{frozen_key}"] = (rec[frozen_key], MASTER[bid][derived_key])
    assert not drift, f"derived view disagrees with frozen §8: {drift}"


def test_the_typosquat_stays_a_separate_registered_payee():
    """BEN-004 is the homoglyph of BEN-001 (§8 `SUSPECTED_TYPOSQUAT_OF:BEN-001`).

    Reconciling the registries must not merge them, and must not hand BEN-004 any of
    BEN-001's accounts — that would turn S11's detection into an approval.
    """
    assert MASTER["BEN-004"]["canonical_name"] != MASTER["BEN-001"]["canonical_name"]
    assert not (set(MASTER["BEN-004"]["registered_accounts"])
                & set(MASTER["BEN-001"]["registered_accounts"]))
    assert MASTER["BEN-004"]["org_payment_count"] == 0, "the typosquat has no payment history"


def test_the_new_to_org_payee_has_no_history_to_borrow():
    """BEN-003 is the hero attack's destination. Its account is *registered* (it was created
    minutes ago — that is the story), but nobody has ever paid it."""
    assert MASTER["BEN-003"]["org_payment_count"] == 0
    assert MASTER["BEN-003"]["distinct_org_payers"] == 0


def test_distinct_org_payers_counts_the_frozen_paid_by_list():
    """§8: "`org_payment_count` and `paid_by` are what make the org-wide web of trust
    different from per-executive history."

    `distinct_org_payers` is that list's length and nothing else. A derived view that claims
    six payers where §8 names three is a second answer to the one question the web of trust
    exists to ask, and it feeds `trust_tier()`'s `>= 3` test directly — the difference between
    `established` (base 5) and `emerging` (base 30) on a payee nobody re-counted.
    """
    drift = {bid: (len(rec["paid_by"]), MASTER[bid]["distinct_org_payers"])
             for bid, rec in BY_ID.items()
             if len(rec["paid_by"]) != MASTER[bid]["distinct_org_payers"]}
    assert not drift, f"distinct_org_payers disagrees with len(paid_by) in frozen §8: {drift}"


def test_a_routine_payment_is_not_oversized_against_its_own_payee_history():
    """`largest_historical_minor_units` is mock data — it is absent from frozen §8 — so
    nothing stops it from being set below the corpus's own ordinary payment to that payee.

    BEN-005 is the "Meridian Employee Payroll Pool": 1180 payments, four org payers, TRUSTED.
    Its largest historical payment was recorded as ₹2.9 lakh, while S19 — the monthly payroll
    run its own narration calls "boring in exactly the right way" — moves ₹2.4 crore. That
    scored +25 for "amount is over three times the largest payment ever made to this payee" on
    the scenario §10 lists as frictionless. A payroll pool whose biggest-ever payment is one
    eightieth of the monthly payroll is not a payroll pool.

    The amount compared here is the one B actually scores: the amount A extracts from the
    transcript. `scenarios.json` declares its own `amount_inr` values "synthetic" (they are
    built to sum to a slide figure over the ATTACK rows), so they are the wrong number for
    this test even though they are the convenient one.
    """
    over = {}
    for s in SCENARIOS:
        if s.get("expected_decision") != "APPROVE" or s.get("class") != "LEGIT":
            continue
        rec = MASTER.get(s.get("beneficiary_id") or "")
        sample = SAMPLES / f"{s['id']}.json"
        if rec is None or not sample.is_file():
            continue
        text = json.loads(sample.read_text(encoding="utf-8"))["raw_text_or_transcript"]
        amount = extract_deterministic(text).amount
        largest = int(rec.get("largest_historical_minor_units", 0))
        if amount and largest > 0 and int(amount * 100) > 3 * largest:
            over[s["id"]] = (int(amount), largest // 100)
    assert not over, (
        "expected-APPROVE scenarios trip the oversize_vs_history modifier "
        f"(transcript amount_inr, payee largest_inr): {over}")
