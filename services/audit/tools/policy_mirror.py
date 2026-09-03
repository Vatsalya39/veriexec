"""Arithmetic mirror of Team B's published policy, used **only** to generate fixtures.

This file is not a decision engine and nothing in the running system imports it. It exists so
that `contracts/golden/` contains internally consistent numbers: a fixture whose contribution
table does not sum to its own risk score is a fixture that will embarrass us on stage.

Every constant below is copied from `02_TEAM_B_RISK_FUSION_CORE.md` (§10.1 weights, §10.4 intent
penalties, §16 bands and hard overrides). If B changes a weight, this file is stale and the
fixtures are regenerated — it is never the other way round.

At integration, `POST /v1/assess-risk` on :8002 replaces every value this module derives.

# MOCKED — replace with real inference in production
"""

from __future__ import annotations

RISK_WEIGHTS = {                      # sums to 1.00
    "communication_authenticity": 0.15,
    "identity_confidence": 0.10,
    "social_engineering": 0.15,
    "behavioural": 0.15,
    "beneficiary": 0.20,
    "semantic_drift": 0.15,
    "device_channel": 0.10,
}
assert abs(sum(RISK_WEIGHTS.values()) - 1.0) < 1e-9

INTENT_PENALTY_WEIGHTS = {            # sums to 1.00
    "semantic_drift": 0.35,
    "fingerprint": 0.20,
    "behavioural": 0.15,
    "device_channel": 0.15,
    "beneficiary": 0.10,
    "extraction_inverse": 0.05,
}
assert abs(sum(INTENT_PENALTY_WEIGHTS.values()) - 1.0) < 1e-9

BANDS = ((0, 29, "APPROVE"), (30, 69, "CHALLENGE"), (70, 100, "BLOCK"))
UNCERTAINTY_PENALTY = 0.30
MIN_COVERAGE = 0.55
REPLAY_FLOOR = 40          # §16.4 PC-5: replay_risk must be below this to approve
LOW_VALUE_EXEMPT = "₹50,000"   # §16.4 PC-4, display only — the threshold itself is B's

SEVERITY = {"APPROVE": 0, "CHALLENGE": 1, "BLOCK": 2}


def max_severity(a: str, b: str) -> str:
    """§16.2 step 7: never downgrade. There is no path from BLOCK to CHALLENGE or APPROVE."""
    return a if SEVERITY[a] >= SEVERITY[b] else b

# Fingerprint verdict -> intent-confidence penalty (§10.4). UNVERIFIABLE is not a pass.
FP_PENALTY = {"MATCH": 0, "UNVERIFIABLE": 60, "NOT_YET_VERIFIED": 60, "MISMATCH": 100}

# An abstained dimension carries this penalty inside intent_confidence. It is deliberately not
# zero: Invariant 3 says missing evidence may never be scored as favourable evidence, and that
# has to be true of the confidence number as well as of the risk number.
ABSTAIN_INTENT_PENALTY = 60

HARD_OVERRIDES = ("HO-1", "HO-2", "HO-3", "HO-4", "HO-5", "HO-6", "HO-7", "HO-8")

OVERRIDE_REASON = {
    "HO-1": ("The destination account in this request does not match the account bound to the "
             "captured authorization ({expected} vs {presented})."),
    "HO-2": ("Payment to an account not on record for {payee}, above the ₹20,00,000 "
             "single-transaction ceiling."),
    "HO-3": ("Payee name is visually identical to established payee {twin} but differs at one "
             "codepoint."),
    "HO-4": "This authorization was already consumed and cannot authorize a second payment.",
    "HO-5": "The approver could not confirm the {field} of this transaction in {n} attempts.",
    "HO-6": "The approving device's signature did not verify against its registered key.",
    "HO-7": "Beneficiary appears on a screening list; release requires compliance sign-off.",
    "HO-8": ("This authorization was issued under policy {old}; current policy is {new}. "
             "Re-authorization is required."),
}

OVERRIDE_COUNTERFACTUAL = {
    "HO-1": ("No change to risk scoring would approve this. The request must be re-issued so "
             "the account it pays matches the account authorized."),
    "HO-2": ("This would have been approved if the payment went to the account of record for "
             "{payee}."),
    "HO-3": ("No change to risk scoring would approve this. The payee name must resolve to a "
             "single registered vendor record."),
    "HO-4": "This authorization is spent. A new authorization must be captured from {executive}.",
    "HO-5": "No change to risk scoring would approve this. A fresh authorization is required.",
    "HO-6": ("No change to risk scoring would approve this. The approval must be signed by a "
             "device registered to the executive, from a channel independent of the request."),
    "HO-7": "Release requires compliance sign-off; risk scoring cannot substitute for it.",
    "HO-8": "Re-authorization under the current policy version is required.",
}

# Team B's §16.2 step 5 applies abstention/coverage floors *before* the band is trusted, and its
# step 6 checks six APPROVE preconditions with frozen ids PC-1..PC-6 (§16.4). Step 5 is unlabelled
# in B's brief, so C assigns `FC-*` ids purely so the console has a stable reason key and a fixture
# can say which floor fired. The PC-* ids and predicates below are B's, copied verbatim; if B
# publishes ids for step 5 these are renamed, never re-decided. Recorded in docs/CHANGES.md.
FORCED_REASON = {
    "FC-1": ("Only {coverage:.0%} of risk dimensions could be evaluated. Below {floor:.0%} "
             "nothing is approved."),
    "FC-2": ("A detector that received input could not score it, so no authenticity evidence "
             "was contributed. Unavailable is not clean."),
    "FC-3": ("The transaction fingerprint has not been verified against a captured "
             "authorization, so intent cannot be confirmed."),
    "PC-1": ("The transaction fingerprint is {fp}, not MATCH: this request was never bound to a "
             "captured authorization."),
    "PC-2": ("Only {coverage:.0%} of risk dimensions could be evaluated. Below {floor:.0%} "
             "nothing is approved."),
    # Unreachable by construction: step 3 returns SILENT_ESCALATION before step 6 runs. Kept
    # because B keeps it, and worded so that rendering it would still leak nothing.
    "PC-3": "This request is completing out-of-band verification.",
    "PC-4": ("₹{amount} is above the ₹50,000 low-value exemption and the approval channel is not "
             "independent of the channel the request arrived on, so out-of-band confirmation is "
             "mandatory."),
    "PC-5": ("This request is a near-duplicate of one already seen ({replay:.0%} similarity), "
             "which is not routine."),
    "PC-6": ("The organisation-level velocity breaker is open: {flags}. While it is open no "
             "payment to a non-established payee is released."),
}


def band(score: float) -> str:
    for lo, hi, name in BANDS:
        if lo <= score <= hi:
            return name
    raise ValueError(score)


def r1(x: float) -> float:
    """Two decimal places.

    Every weight is a multiple of 0.05 and every raw score is an integer, so `weight * raw`
    is exactly representable at 2 dp — this rounding removes IEEE-754 noise (0.15 * 7 comes
    back as 1.0499999999999998) and loses nothing. It matters because the contribution table
    is rendered and has to add up on screen: `sum(points)` must equal the subtotal exactly,
    not to within a rounding tolerance.
    """
    return round(x + 1e-9, 2)


def fuse(raw: dict[str, float | None]) -> dict:
    """Abstention-aware weighted fusion (§10.2).

    `raw` maps every one of the seven dimension names to a RISK value 0-100, or to None when
    the dimension could not be evaluated. Returns the subtotal, the coverage, the
    renormalized score, the uncertainty penalty and the final score, all separately — the
    console renders each step, because a single fused number is not an explanation.
    """
    missing = [k for k, v in raw.items() if v is None]
    unknown = set(raw) - set(RISK_WEIGHTS)
    if unknown:
        raise KeyError(f"not a fusion dimension: {sorted(unknown)}")
    if set(RISK_WEIGHTS) - set(raw):
        raise KeyError(f"missing dimension: {sorted(set(RISK_WEIGHTS) - set(raw))}")

    coverage = sum(w for k, w in RISK_WEIGHTS.items() if k not in missing)
    # Summed from the rounded per-dimension points, not from the unrounded products, so the
    # published subtotal is the sum of the published contributions.
    subtotal = r1(sum(r1(RISK_WEIGHTS[k] * v) for k, v in raw.items() if v is not None))

    # Renormalize over what was actually measured, then add the uncertainty penalty. The two
    # steps pull in opposite directions and both are shown: dividing by coverage alone would
    # let an abstention *lower* the score, which is exactly what Invariant 3 forbids.
    renormalized = subtotal / coverage if coverage else 0.0
    penalty = UNCERTAINTY_PENALTY * (1.0 - coverage) * 100.0
    score = min(100.0, renormalized + penalty)

    return {
        "subtotal": r1(subtotal),
        "coverage": round(coverage, 4),
        "renormalized": r1(renormalized),
        "uncertainty_penalty": r1(penalty),
        "score": int(round(score)),
        "abstained": missing,
    }


def intent_confidence(raw: dict[str, float | None], fp_verdict: str,
                      extraction_confidence: int, duress: bool) -> int:
    """§10.4. Deliberately independent of voice and video: a perfect clone must not raise it."""
    parts = {
        "semantic_drift": raw["semantic_drift"],
        "fingerprint": FP_PENALTY[fp_verdict],
        "behavioural": raw["behavioural"],
        "device_channel": raw["device_channel"],
        "beneficiary": raw["beneficiary"],
        "extraction_inverse": 100 - extraction_confidence,
    }
    penalty = sum(INTENT_PENALTY_WEIGHTS[k] * (ABSTAIN_INTENT_PENALTY if v is None else v)
                  for k, v in parts.items())
    c = int(round(max(0.0, 100.0 - penalty)))
    # A coerced approval and a rebound fingerprint are both "the words are right, the intent is
    # not". Neither may present as confident.
    if duress or fp_verdict == "MISMATCH":
        c = min(c, 25)
    return c


# §16.2 step 5. Abstention and coverage floors, applied via max_severity at *any* band — not only
# to an APPROVE. B's brief checks `coverage < MIN_COVERAGE or fingerprint is UNVERIFIABLE`; FC-2 is
# the third floor Team C's §6.6 requires and B's step-5 condition does not yet cover: a modality
# that was present and could not be scored. Ordered — the first is the one the console names,
# because "held for four different reasons" is not an explanation a human can act on.
def forced_challenge_floors(coverage: float, fp_verdict: str,
                           modality_unscoreable: bool) -> list[str]:
    out = []
    if modality_unscoreable:
        out.append("FC-2")
    if coverage < MIN_COVERAGE:
        out.append("FC-1")
    if fp_verdict in ("UNVERIFIABLE", "NOT_YET_VERIFIED"):
        out.append("FC-3")
    return out


# §16.4 step 6, in B's frozen id order. Evaluated only when the outcome is still APPROVE; a failure
# degrades it to CHALLENGE with a reason that names the remedy.
def approve_preconditions(coverage: float, fp_verdict: str, over_ceiling: bool,
                          replay_similarity: dict | None, breaker_open: bool,
                          duress: bool) -> list[str]:
    out = []
    if fp_verdict != "MATCH":
        out.append("PC-1")
    if coverage < MIN_COVERAGE:
        out.append("PC-2")
    if duress:
        out.append("PC-3")
    if over_ceiling:
        out.append("PC-4")
    if replay_similarity and replay_similarity["max_similarity"] * 100 >= REPLAY_FLOOR:
        out.append("PC-5")
    if breaker_open:
        out.append("PC-6")
    return out


def decide(score: int, override: str | None, floors: list[str], preconds: list[str],
           duress: bool, breaker_open: bool) -> dict:
    """Resolve B's §16.2 decision function, step for step.

    1 breaker · 2 hard override · 3 duress · 4 band · 5 abstention/coverage floors ·
    6 APPROVE preconditions · 7 never downgrade.

    `forced_by` names a floor or precondition only when it actually *changed* the outcome. A floor
    that fires under an already-CHALLENGE band is reported in `floors_failed` and explains the
    coverage note, but it did not decide anything and must not be presented as if it had.
    """
    band_outcome = band(score)
    base = {"band_outcome": band_outcome, "floors_failed": list(floors),
            "preconditions_failed": [], "duress_escalation": False,
            "visible_to_requester": None, "control_label": None}

    if breaker_open:
        # Step 1, ahead of the hard overrides. An open breaker is an org-level stop, not a
        # per-request opinion: it blocks whatever the band said.
        return {**base, "decision": "BLOCK", "override_applied": "BREAKER",
                "forced_by": "PC-6", "outcome": "BLOCK", "control_label": "BREAKER_TRIPPED"}
    if override:
        return {**base, "decision": "BLOCK", "override_applied": override,
                "forced_by": None, "outcome": "BLOCK"}
    if duress:
        # Invariant 4: the requester must see something indistinguishable from ordinary
        # verification. The escalation rides alongside, never in `decision`.
        return {**base, "decision": "CHALLENGE", "override_applied": "DURESS",
                "forced_by": None, "outcome": "SILENT_ESCALATION",
                "duress_escalation": True, "visible_to_requester": "PROCESSING"}

    outcome, forced_by = band_outcome, None
    if floors:
        escalated = max_severity(outcome, "CHALLENGE")
        if escalated != outcome:
            forced_by = floors[0]
        outcome = escalated
    if outcome == "APPROVE" and preconds:
        outcome, forced_by = "CHALLENGE", preconds[0]
        base["preconditions_failed"] = list(preconds)
    return {**base, "decision": outcome, "override_applied": None,
            "forced_by": forced_by, "outcome": outcome}


def counterfactual_numeric(contributions: list[dict], score: int, target: int = 29) -> dict:
    """Greedy largest-contributor-first: the smallest set of dimensions that, zeroed, would
    have landed inside APPROVE. Reported as *what would have to be true*, never as advice on
    how to get a payment through.
    """
    need = score - target
    if need <= 0:
        return {"kind": "already_approvable", "dimensions": [], "narrative":
                "This request is inside the approve band as scored."}
    freed, picked = 0.0, []
    for c in sorted(contributions, key=lambda c: -c["points"]):
        if freed >= need:
            break
        picked.append(c)
        freed += c["points"]
    if freed < need:
        return {"kind": "not_reachable", "dimensions": [c["dimension"] for c in picked],
                "narrative": ("No combination of risk-score changes reaches the approve band; "
                              "the request itself has to change.")}
    names = [c["label"] for c in picked]
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return {"kind": "numeric", "dimensions": [c["dimension"] for c in picked],
            "points_freed": r1(freed), "target_band_max": target,
            "narrative": (f"This would have scored {target} or below — an approval — if "
                          f"{joined} had contributed nothing. It contributed "
                          f"{r1(freed)} of the {score} points.")}
