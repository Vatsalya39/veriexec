"""B4 — beneficiary risk, the org-wide web of trust, and homoglyph detection.

[NOVEL-N5a] Every other system asks "has *this executive* paid this payee before?" We ask
"has *anyone in the organization* paid this payee, how recently, how much, and did those
payments settle without dispute?" That widening converts a first-time-for-one-person
payment into a known-good payment for the org — which is what kills false challenges.

[NOVEL-N20] The homoglyph half is in `homoglyph.py`, no external dependency, so the
confusable table is auditable and offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .. import contracts_io
from ..contracts_io import as_date
from ..policy.constants import (
    BENEFICIARY_BASE,
    BENEFICIARY_MODIFIERS,
    NEW_PAYEE_DORMANT_DAYS,
)
from .fusion import DimensionScore
from .homoglyph import ConfusionReport, confusion_report

#: §7.1's exact table. trust_tier is DERIVED, never hand-written — a stored tier is a
#: stored lie the moment the payment count changes.


@dataclass(frozen=True)
class BeneficiaryFacts:
    beneficiary_id: str | None
    canonical_name: str
    tier: str
    score: float
    reasons: tuple[str, ...]
    account_on_record: bool
    sanctions_screen: str
    confusion: ConfusionReport | None


def trust_tier(rec: dict, now: date) -> str:
    """§7.1. Derived from counts and dates — never read from the file."""
    if int(rec.get("disputed_payment_count", 0)) > 0:
        return "disputed"
    if int(rec.get("org_payment_count", 0)) == 0:
        return "unknown"
    first = as_date(rec.get("first_seen"))
    if (int(rec.get("org_payment_count", 0)) >= 10
            and int(rec.get("distinct_org_payers", 0)) >= 3
            and first is not None and (now - first).days >= 180):
        return "established"
    if int(rec.get("org_payment_count", 0)) >= 3:
        return "emerging"
    return "provisional"


def _bank_prefix(account: str) -> str:
    return "".join(c for c in (account or "") if c.isalpha())[:4].upper()


def _digits(account: str) -> str:
    return "".join(c for c in (account or "") if c.isdigit())


def account_matches(reference: str, registered: str) -> bool:
    """Does a spoken or written account reference name this registered account?

    Exact first. Failing that, a *shorter* reference is treated as a suffix of the full
    number, because that is how account numbers are confirmed out loud: `"ICIC account
    ending 776655"` is not a different account from `ICIC0009988776655`, and A cannot invent
    the digits the speaker never said.

    The guard is deliberately narrow, because a loose rule here approves fraud:
      * at least 4 digits, so a stray `"3312"`-style reference cannot match everything;
      * strictly shorter than the registered number, so two *full* numbers must be equal —
        `ADCB0000099287` (S09's account) still does not match `ADCB0000099281`, which is
        exactly the near-miss the corpus is testing;
      * digits only, so a bank-code prefix never carries the match on its own.
    """
    if not reference or not registered:
        return False
    if reference == registered:
        return True
    ref, reg = _digits(reference), _digits(registered)
    if len(ref) < 4 or len(ref) >= len(reg):
        return False
    return reg.endswith(ref)


def score(
    *,
    beneficiary_label: str,
    destination_account: str,
    amount_minor_units: int | None,
    now: datetime,
) -> BeneficiaryFacts:
    """The beneficiary dimension, plus the facts HO-2/HO-3/HO-7 act on."""
    label = (beneficiary_label or "").strip()
    account = (destination_account or "").strip()
    master = contracts_io.beneficiary_master(now)
    today = now.date()

    # --- registry lookup, exact name or alias, never fuzzy (that is homoglyph's job) ----
    rec: dict | None = None
    bid: str | None = None
    folded = label.casefold()
    for k in sorted(master):
        names = {str(master[k].get("canonical_name", "")).strip().casefold()}
        names.update(str(a).strip().casefold() for a in master[k].get("aliases", ()))
        if folded and folded in names:
            rec, bid = master[k], k
            break

    reasons: list[str] = []
    confusion: ConfusionReport | None = None
    if label:
        # An unmatched name is compared against every payee. A *matched* name with no payment
        # history is compared against every OTHER payee, because a typosquat can be registered
        # under its own misspelling: BEN-004's canonical_name IS the misspelling, so the exact
        # lookup above finds it, and the confusable check used to be skipped entirely — the one
        # fact that makes S11 an attack was dropped and the payee read as merely unknown.
        if rec is None:
            confusion = confusion_report(label, master)
        elif int(rec.get("org_payment_count", 0)) == 0:
            confusion = confusion_report(label, {k: v for k, v in master.items() if k != bid})
    if confusion is not None and account:
        # §7.2 rule 4, which `confusion_report` documents as the caller's job: money moving to
        # an account the impersonated payee already banks at is a data-entry variant, not a
        # diversion. Nothing leaves the organization that was not already leaving it.
        target_accounts = master.get(confusion.target_id, {}).get("registered_accounts", ())
        if any(account_matches(account, str(a)) for a in sorted(target_accounts)):
            confusion = None

    # --- base score from the derived tier -------------------------------------------------
    if rec is None:
        base = BENEFICIARY_BASE["unknown"]
        if confusion is not None:
            base = max(base, confusion.risk_floor)
        reasons.append(
            "no payee in the organization's vendor master matches this name"
            if confusion is None
            else f"payee name is a near-duplicate of established payee {confusion.target_name}"
        )
        if confusion is not None:
            reasons.append(confusion.reason)
        tier = "unknown"
    else:
        tier = trust_tier(rec, today)
        base = BENEFICIARY_BASE[tier]
        reasons.append(f"payee is {tier} in the organization's payment history")

    # --- modifiers (§7.1 table) -----------------------------------------------------------
    delta = 0.0
    account_on_record = False
    if rec is not None:
        registered = {str(a) for a in rec.get("registered_accounts", ())}
        account_on_record = bool(account) and any(
            account_matches(account, r) for r in sorted(registered))
        if account and not account_on_record:
            delta += BENEFICIARY_MODIFIERS["unregistered_account"]
            reasons.append("the destination account is not on record for this payee")
        if amount_minor_units is not None:
            largest = int(rec.get("largest_historical_minor_units", 0))
            if largest > 0 and amount_minor_units > 3 * largest:
                delta += BENEFICIARY_MODIFIERS["oversize_vs_history"]
                reasons.append("amount is over three times the largest payment ever made to "
                               "this payee")
        last_paid = as_date(rec.get("last_paid"))
        first = as_date(rec.get("first_seen"))
        if (last_paid is not None and (today - last_paid).days > NEW_PAYEE_DORMANT_DAYS
                and int(rec.get("org_payment_count", 0)) > 0):
            delta += BENEFICIARY_MODIFIERS["dormant_reappears"]
            reasons.append("payee has been dormant for over a year and just reappeared")
        if account and not account_on_record and registered:
            reg_banks = {_bank_prefix(a) for a in registered}
            if _bank_prefix(account) and _bank_prefix(account) not in reg_banks:
                delta += BENEFICIARY_MODIFIERS["different_bank"]
                reasons.append("destination account is at a different bank from every "
                               "registered account")
        if confusion is not None:
            # The payee we matched is itself a confusable variant of an established payee —
            # that is the S11 shape, and its own registry entry must not launder it.
            base = max(base, 90.0)
            reasons.insert(0, confusion.reason)

    total = max(0.0, min(100.0, base + delta))
    # Sanctions is checked even on unmatched names: HO-7 must not depend on the fuzzy
    # lookup having succeeded — but an unknown payee gets `clear`, never a fabricated hit.
    if rec is not None:
        sanctions = str(rec.get("sanctions_screen", "clear"))
    else:
        sanctions = "clear"
    if sanctions != "clear":
        reasons.append("beneficiary appears on a sanctions screening list")
        total = 100.0

    return BeneficiaryFacts(
        beneficiary_id=bid,
        canonical_name=str((rec or {}).get("canonical_name", label)),
        tier=tier,
        score=round(total, 2),
        reasons=tuple(reasons),
        account_on_record=account_on_record,
        sanctions_screen=sanctions,
        confusion=confusion,
    )


def dimension(facts: BeneficiaryFacts) -> DimensionScore:
    """`BeneficiaryFacts` -> the fusion dimension, with the §10.3 evidence trail."""
    ev = [f"contracts/beneficiary_master.json#{facts.beneficiary_id or 'unmatched'}"]
    if facts.confusion is not None:
        ev.append(f"beneficiary.confusable:{facts.confusion.target_id}")
    return DimensionScore(
        dimension="beneficiary",
        score=facts.score,
        reason="; ".join(facts.reasons[:3]).capitalize() + ".",
        evidence_ref=ev[0],
        evidence=tuple(ev),
    )
