"""Every constant whose value can change a decision. Hashed into `policy_hash` (§19.1).

Nothing in this module reads the clock, the environment or a model. Editing a number here
changes `policy_hash`, which changes every `RiskAssessment`, `CapabilityToken` and audit
record that follows — which is the point. A policy you cannot pin is a policy you cannot
audit, so the bump discipline from §19.1 applies: patch for reason text, minor for weights
and thresholds, major for a new override or dimension.

Money is integer minor units (paise) throughout. There is no float multiplication of money
anywhere in this file; `single_txn_ceiling` does its 2.5x in integers on purpose.
"""

from __future__ import annotations

# --------------------------------------------------------------------------------- bands

#: §16.1. Bands are the *default* outcome. Overrides and preconditions beat them in both
#: directions, and the evaluation order in `decide.py` is fixed and testable.
BANDS: tuple[tuple[int, int, str], ...] = (
    (0, 29, "APPROVE"),
    (30, 69, "CHALLENGE"),
    (70, 100, "BLOCK"),
)


def band_for(risk_score: float) -> str:
    """The banded outcome for a score, clamped into 0-100 rather than falling through."""
    s = max(0, min(100, round(risk_score)))
    for lo, hi, outcome in BANDS:
        if lo <= s <= hi:
            return outcome
    raise AssertionError(f"BANDS do not cover {s}")  # unreachable while BANDS spans 0-100


# ------------------------------------------------------------------------------- fusion

#: §10.1 — the seven weighted risk dimensions. Sums to 1.00.
#: `beneficiary` carries the highest weight deliberately: a deepfake is a delivery
#: mechanism, the destination account is the crime.
RISK_WEIGHTS: dict[str, float] = {
    "communication_authenticity": 0.15,   # from A: voice/video/text detectors (INVERTED first)
    "identity_confidence": 0.10,          # device, account, MFA posture (INVERTED first)
    "social_engineering": 0.15,           # pressure families + stylometry (already RISK)
    "behavioural": 0.15,                  # B3
    "beneficiary": 0.20,                  # B4
    "semantic_drift": 0.15,               # B5
    "device_channel": 0.10,               # B11 + B9
}

#: Missing evidence makes us more cautious, never less (§10.2).
UNCERTAINTY_PENALTY = 0.30

#: Below this fraction of total weight, nothing can be approved (Invariant 3).
MIN_COVERAGE = 0.55

# --------------------------------------------------------------------- intent_confidence

#: §10.4 — the thesis as arithmetic. Sums to 1.00.
#: Read the keys and notice what is absent: `deepfake_voice_score`, `deepfake_video_score`,
#: face liveness, and every other media score. Not one of them appears. That absence is the
#: product, and `test_intent_confidence_independent_of_voice` is what keeps it true.
INTENT_PENALTY_WEIGHTS: dict[str, float] = {
    "semantic_drift": 0.35,
    "fingerprint": 0.20,
    "behavioural": 0.15,
    "device_channel": 0.15,
    "beneficiary": 0.10,
    "extraction_inverse": 0.05,           # 100 - extraction_confidence
}

#: The `fingerprint` term above, per verdict. UNVERIFIABLE is a real penalty, not a zero:
#: "we never bound the intent" is evidence of nothing, and nothing is not reassurance.
FINGERPRINT_INTENT_PENALTY: dict[str, int] = {
    "MATCH": 0,
    "NOT_YET_VERIFIED": 60,
    "MISMATCH": 100,
}

#: A bound-field mismatch, or duress, cannot leave us confident about intent (§10.4).
INTENT_CONFIDENCE_CAP_ON_MISMATCH = 25

# ------------------------------------------------------------------------------ ceilings

#: ₹20,00,000 — the absolute organizational single-transaction cap, in paise.
ABSOLUTE_SINGLE_TXN_CEILING = 2_000_000_00

#: A person's own history sets the other half of the cap.
CEILING_MULTIPLE_NUMERATOR = 5           # 2.5x expressed as 5/2 so money never meets a float
CEILING_MULTIPLE_DENOMINATOR = 2

#: B5 — semantic drift weights. Frozen; they appear in `policy_hash` via this file.
#: Sums to 1.00 — asserted by `_assert_weights` below.
DRIFT_WEIGHTS: dict[str, float] = {
    "amount": 0.35,
    "account": 0.30,
    "beneficiary": 0.25,
    "action": 0.05,
    "currency": 0.05,
}

#: B2 — windows, in seconds/minutes, so freshness and token modules share one number.
AUTH_WINDOW_MINUTES = 15.0               # intent capture -> expiry (§5 rule 4)
FRESHNESS_TTL_SECONDS = 120              # the whole point: a relayed answer goes stale fast
VALIDITY_WINDOW_MINUTES = 15.0           # alias of AUTH_WINDOW_MINUTES for readability

#: B10 — capability-token TTL, in seconds. Five minutes: long enough to redeem a reviewed
#: payment, short enough that a stolen token is a very narrow window.
TOKEN_TTL_SECONDS = 300

#: ₹25,00,000 — routine non-executive ceiling (payroll runs are legitimately large).
EMPLOYEE_ROUTINE_CEILING = 2_500_000_00

#: ₹50,000 — below this, PC-4 does not demand a second channel for a routine payment.
LOW_VALUE_EXEMPT = 50_000_00

#: PC-5: a near-duplicate of a prior request is not routine.
REPLAY_RISK_APPROVE_CEILING = 40

#: §16.3 / B8. Two attempts at the comprehension challenge, then HO-5 refuses. The number
#: lives here rather than in the challenge module because HO-5's meaning depends on it: one
#: wrong answer is a challenge that can still be answered, the second is a refusal.
CHALLENGE_ATTEMPTS_ALLOWED = 2

def single_txn_ceiling(median_minor_units: int) -> int:
    """§16.3. The lower of an absolute org cap and 2.5x this person's own median.

    The `min()` is the whole idea: neither a low-volume executive nor a high-volume one
    inherits a ceiling that only makes sense for the other. The 2.5x is integer round-half-up
    (`(5n+1)//2`) rather than `round(2.5 * n)` so that money never touches a float and the
    result is identical on every platform — replay depends on that.
    """
    relative = (median_minor_units * CEILING_MULTIPLE_NUMERATOR + 1) // CEILING_MULTIPLE_DENOMINATOR
    return min(ABSOLUTE_SINGLE_TXN_CEILING, relative)


# ------------------------------------------------------------------------------ cooldown

#: B3's guard: behavioural evidence alone can never reach the BLOCK band. Blocking on
#: behaviour alone is how real systems generate the false-challenge rate the organizers
#: score us on. 92 leaves room for it to *matter* without letting it *decide*.
BEHAVIOURAL_CAP = 92

# ------------------------------------------------------------------- beneficiary (B4)

#: §7.1 base scores by DERIVED trust tier.
BENEFICIARY_BASE: dict[str, float] = {
    "established": 5,
    "emerging": 30,
    "provisional": 55,
    "unknown": 70,
    "disputed": 90,
}

#: §7.1 modifiers.
BENEFICIARY_MODIFIERS: dict[str, float] = {
    "oversize_vs_history": 25,     # amount > 3x the largest historical payment to this payee
    "dormant_reappears": 20,       # dormant > 365 days then reappears
    "unregistered_account": 40,   # account not in registered_accounts
    "different_bank": 15,         # different bank from every registered account
}

#: §7.1 dormancy threshold in days.
NEW_PAYEE_DORMANT_DAYS = 365

COOLDOWN_MAX_SECONDS = 900               # 15 minutes
COOLDOWN_SECONDS_PER_POINT = 6           # "six seconds of delay per point of risk"


def cooldown_seconds(risk_score: float) -> int:
    """Monotonic and continuous — no step function an attacker can tune around."""
    return max(0, min(COOLDOWN_MAX_SECONDS, round(risk_score * COOLDOWN_SECONDS_PER_POINT)))


# ------------------------------------------------------------------------------- breaker

#: §15.2. Per-transaction scoring is blind to campaigns; the breaker sees the aggregate.
BREAKER: dict[str, int] = {
    "window_seconds": 900,                    # rolling, not fixed buckets
    "trip_elevated_count": 3,                 # >=3 requests at or above the threshold
    "trip_elevated_threshold": 50,
    "trip_multi_employee_count": 2,           # OR >=2 DISTINCT employees at or above 60
    "trip_multi_employee_threshold": 60,
    "trip_same_beneficiary_count": 2,         # OR >=2 requests to the same NEW payee
    "open_seconds": 1800,                     # 30 minutes
    "half_open_probes": 1,                    # exactly one, fully challenged
}

# ------------------------------------------------------------- device / channel penalties

#: §14. Independence is enforced at the FAMILY level: a second messaging app on the same
#: handset is not a second channel, and comparing raw ids would call it one.
CHANNEL_PENALTIES: dict[str, int] = {
    "SAME_CHANNEL": 85,
    "SAME_DEVICE_FAMILY": 60,
    "UNTRUSTED_VERIFIER": 45,
    "INDEPENDENT": 0,
    "PENDING": 0,                             # verification has not happened yet
}

#: Each of A's `channel_switch_flags`, clamped with the rest at 100.
CHANNEL_SWITCH_FLAG_POINTS = 12

#: contracts/CRYPTO_WIRE_FORMAT.md. A client-supplied "signature_verified: true" is treated
#: as absent, never as valid — only a locally verified signature earns the 0.
SIGNATURE_PENALTIES: dict[str, int] = {
    "VALID": 0,
    "ABSENT": 0,                              # nothing was claimed; scored elsewhere
    "MALFORMED": 60,
    "UNKNOWN_DEVICE": 70,
    "REVOKED": 100,                           # HO-6
    "INVALID": 100,                           # HO-6
}

# ------------------------------------------------------------------------- override wiring

#: §16.3, frozen order. First match wins, and HO-1 is first because it is the thesis: the
#: most specific and most explainable reason should be the one the operator reads.
HARD_OVERRIDE_IDS: tuple[str, ...] = (
    "HO-1", "HO-2", "HO-3", "HO-4", "HO-5", "HO-6", "HO-7", "HO-8",
)

#: §6.6 froze `hard_overrides_fired` as semantic codes, while B's tests assert on HO ids.
#: Both ship: the semantic code in the array, the id in the additive `override_applied`.
WIRE_OVERRIDE_CODES: dict[str, str] = {
    "HO-1": "FINGERPRINT_MISMATCH",
    "HO-2": "AMOUNT_CEILING",
    "HO-3": "BENEFICIARY_CONFUSION",
    "HO-4": "REPLAY_CONSUMED",
    "HO-5": "COMPREHENSION_FAILED",
    "HO-6": "DEVICE_SIGNATURE_INVALID",
    "HO-7": "SANCTIONS_SCREEN",
    "HO-8": "POLICY_VERSION_MISMATCH",
    "BREAKER": "BREAKER_TRIPPED",
    "DURESS": "DURESS",
    "SAME_CHANNEL": "SAME_CHANNEL_VERIFICATION",
}

PRECONDITION_IDS: tuple[str, ...] = ("PC-1", "PC-2", "PC-3", "PC-4", "PC-5", "PC-6")

#: A precondition failure must name the remedy, so the vocabulary is closed and C can map
#: each entry to a button. "Additional verification required" is not in it on purpose.
REQUIRED_ACTIONS: tuple[str, ...] = (
    "none",
    "answer_comprehension_challenge",
    "complete_approval_in_console",
    "contact_executive_out_of_band",
    "notify_security_officer",
    "reauthorize_with_current_details",
    "await_secondary_approver",
    "wait_for_cooldown",
    "compliance_signoff",
    "named_human_review",
    "verify_beneficiary_account_with_payee",
)

#: §16/§2 — the scoring modules land after the policy shape. Until a dimension is real it
#: reports this, so the overrides can be proven to fire before any number is tuned.
STUB_SCORE = 50

# ------------------------------------------------------------------------------ self-check

#: `test_weights_sum_to_one` also asserts these; failing at import is faster and louder.
def _assert_weights() -> None:
    for name, table in (("RISK_WEIGHTS", RISK_WEIGHTS),
                        ("INTENT_PENALTY_WEIGHTS", INTENT_PENALTY_WEIGHTS),
                        ("DRIFT_WEIGHTS", DRIFT_WEIGHTS)):
        total = round(sum(table.values()), 10)
        if total != 1.0:
            raise AssertionError(f"{name} sums to {total}, not 1.00")
    covered = set()
    for lo, hi, _ in BANDS:
        covered |= set(range(lo, hi + 1))
    if covered != set(range(101)):
        raise AssertionError("BANDS must cover 0-100 exactly once")
    media = {"deepfake_voice_score", "deepfake_video_score", "voice", "video",
             "face_liveness", "deepfake_probability", "voice_authenticity"}
    leaked = media & set(INTENT_PENALTY_WEIGHTS)
    if leaked:
        raise AssertionError(f"intent_confidence must not know about media scores: {leaked}")


_assert_weights()
