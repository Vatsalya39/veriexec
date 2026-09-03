"""The frozen wire shapes — `00_SHARED_CONTEXT.md §6` — and nothing else.

Three rules govern this file, and they are why integration is cheap:

1. **Base fields are byte-frozen.** Never rename, retype or drop one. When a base field is
   the wrong type for arithmetic — `amount` is `number|null`, so possibly a float — the fix
   is a derived accessor (`to_paise`), never a change to the field.
2. **Extensions are new top-level keys with mandatory defaults.** Producers always emit
   every extension key, using the default when the feature did not apply, so a consumer
   still on the base shape never breaks.
3. **Inbound models keep unknown keys.** Team A ships extensions on its own schedule;
   `extra="allow"` means their next field lands without a Team B release.

Score direction, since §6.2 warns that every team has inverted it at least once:
`identity_confidence`, `communication_authenticity`, `deepfake_*_score` and
`stylometry_match_score` are AUTHENTICITY — higher means more likely genuine.
`social_engineering_score`, `semantic_drift_score` and `risk_score` are RISK — higher is
worse. Nothing here converts between them; `scoring/fuse.py` does that, out loud.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .crypto.canonical import NonCanonicalValue, to_minor_units

#: Invariant 7 — "any score above a materiality threshold must emit at least one reason".
#: The strictest reading is also the easiest to defend: anything non-zero needs a reason.
MATERIALITY_THRESHOLD = 0


class Action(str, Enum):
    TRANSFER = "TRANSFER"
    CREDENTIAL_RESET = "CREDENTIAL_RESET"
    BENEFICIARY_CHANGE = "BENEFICIARY_CHANGE"
    PAYMENT_LIMIT_CHANGE = "PAYMENT_LIMIT_CHANGE"
    OTHER = "OTHER"


#: §6.5's token scope omits `OTHER` on purpose: there is no capability for "something".
TOKENABLE_ACTIONS = frozenset(a for a in Action if a is not Action.OTHER)

class Channel(str, Enum):
    PHONE = "PHONE"
    VIDEO = "VIDEO"
    EMAIL = "EMAIL"
    CHAT = "CHAT"
    COLLAB_PLATFORM = "COLLAB_PLATFORM"


class Urgency(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Decision(str, Enum):
    """The frozen §6.3 vocabulary. `policy/decide.py` owns the only writes to this."""

    APPROVE = "APPROVE"
    CHALLENGE = "CHALLENGE"
    BLOCK = "BLOCK"


class FingerprintStatus(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NOT_YET_VERIFIED = "NOT_YET_VERIFIED"


class BreakerState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class ExtractionMode(str, Enum):
    llm = "llm"
    deterministic = "deterministic"
    hybrid = "hybrid"
    failed = "failed"


class ChallengeType(str, Enum):
    """§11. Chosen deterministically from `sha256(transaction_id + policy_version)`."""

    AMOUNT_RECALL = "AMOUNT_RECALL"
    BENEFICIARY_SELECT = "BENEFICIARY_SELECT"
    ACCOUNT_TAIL = "ACCOUNT_TAIL"
    PURPOSE_MATCH = "PURPOSE_MATCH"

class VerificationMethod(str, Enum):
    OOB_APPROVAL = "OOB_APPROVAL"
    CHALLENGE_RESPONSE = "CHALLENGE_RESPONSE"
    SECONDARY_APPROVER = "SECONDARY_APPROVER"
    NONE = "NONE"


class VerificationResult(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    PENDING = "PENDING"


class FinalOutcome(str, Enum):
    EXECUTED = "EXECUTED"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"


# ------------------------------------------------------------------------ base classes

class Inbound(BaseModel):
    """A shape another team produces. Unknown keys are kept, never rejected (§6.6).

    Every base field also carries a default, because B must degrade safely when Team A's
    extraction fails rather than raise a validation error on the request path. Each default
    is chosen to be the *unfavourable* reading — absence is never evidence of innocence.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Outbound(BaseModel):
    """A shape B produces. Extra keys are a bug here, so they are forbidden."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, validate_assignment=True)

    def wire(self) -> dict[str, Any]:
        """The JSON-ready dict. `by_alias` matters: `FieldChange.from_` ships as `from`."""
        return self.model_dump(mode="json", by_alias=True)

def to_paise(amount: Any, currency: str | None = "INR") -> int | None:
    """The single door from `TransactionIntent.amount` to money B can compute with.

    The base field is a frozen `number|null`, so a float can legitimately arrive on the
    wire. A float is routed through its exact decimal text, which means `1500000.0`
    converts cleanly while `0.30000000000000004` is refused rather than quietly rounded.
    """
    if amount is None:
        return None
    if isinstance(amount, bool):
        raise NonCanonicalValue("bool is not an amount")
    if isinstance(amount, float):
        # repr() gives the shortest round-tripping digits; Decimal(...) then formats
        # without scientific notation so to_minor_units sees plain digits.
        amount = format(Decimal(repr(amount)), "f")
    return to_minor_units(amount, currency=(currency or "INR").upper())


# ------------------------------------------------------- §6.1 TransactionIntent (from A)

class DeterministicIntent(Inbound):
    """A's regex-only extraction of the same critical fields, for B6 divergence scoring."""

    action: str | None = None
    amount: Any | None = None
    currency: str | None = None
    beneficiary: str | None = None
    destination_account: str | None = None
    deadline: str | None = None


class AmountNormalization(Inbound):
    """`{raw_span, parsed_value, multiplier, rule}` — the lakh/crore parsing audit trail."""

    raw_span: str = ""
    parsed_value: Any | None = None
    multiplier: int | None = None
    rule: str = ""

class TransactionIntent(Inbound):
    """§6.1. Note what is NOT here: no `executive_id`, no `nonce`, no validity window.

    `requester` is a *claimed* name or role — resolving it to an `executive_id` is B's job
    (`scoring/identity.py`), and the nonce and window are minted by B2. That separation is
    the point: A reports what was said, B decides who that was and what it binds to.
    """

    # --- frozen base ------------------------------------------------------------------
    transaction_id: str
    requester: str = ""                        # CLAIMED name/role, never an identity
    action: Action = Action.OTHER
    amount: Any | None = None                  # rupees, `number|null` — see to_paise()
    currency: str | None = None
    beneficiary: str | None = None
    destination_account: str | None = None
    purpose: str | None = None
    deadline: str | None = None                # ISO datetime OR free text
    urgency: Urgency = Urgency.MEDIUM
    secrecy_flags: list[str] = Field(default_factory=list)
    channel: Channel = Channel.EMAIL
    raw_transcript_or_text: str = ""           # UNTRUSTED: never interpolated raw into a prompt
    timestamp: str = ""

    # --- A-owned extensions (§6.6), defaults exactly as tabled -------------------------
    extraction_confidence: float = 0
    extraction_mode: ExtractionMode = ExtractionMode.failed
    deterministic_intent: DeterministicIntent | None = None
    extraction_divergence: list[str] = Field(default_factory=list)
    injection_flags: list[str] = Field(default_factory=list)
    amount_normalization: AmountNormalization | None = None
    language_detected: str = "en"
    origin_session_id: str = ""
    sample_id: str | None = None

    def amount_minor_units(self) -> int | None:
        """Integer paise, or None when A could not extract an amount at all."""
        return to_paise(self.amount, self.currency)

# ----------------------------------------------------------- §6.2 SignalBundle (from A)

class ChannelEvent(Inbound):
    timestamp: str = ""
    event: str = ""
    channel: str = ""


class DeviceInfo(Inbound):
    device_id: str = ""
    known_device: bool = False                 # unknown is not trusted
    location: str = ""


class DetectorReport(Inbound):
    """Invariant 3 lives here: `abstain=True` contributes zero AUTHENTICITY evidence."""

    name: str = ""
    score: float | None = None                 # AUTHENTICITY, meaningless when abstain
    confidence: float = 0
    abstain: bool = False
    abstain_reason: str | None = None


class ReplaySimilarity(Inbound):
    """Near-duplicate detection. `max_similarity` is 0-1, NOT 0-100 — B2 rescales it."""

    max_similarity: float = 0.0
    matched_utterance_id: str | None = None
    method: str = ""

class SignalBundle(Inbound):
    """§6.2. Defaults are deliberately pessimistic: 0 authenticity, not 100.

    A missing bundle must never read as a clean bundle. That is Invariant 3 expressed as a
    default value, which is the cheapest place to express it.
    """

    # --- frozen base — AUTHENTICITY unless the comment says RISK -----------------------
    transaction_id: str
    identity_confidence: float = 0             # AUTHENTICITY 0-100
    communication_authenticity: float = 0      # AUTHENTICITY 0-100
    deepfake_voice_score: float | None = None  # AUTHENTICITY; null = no evidence
    deepfake_video_score: float | None = None  # AUTHENTICITY; null = no evidence
    stylometry_match_score: float | None = None  # AUTHENTICITY; text channels only
    social_engineering_score: float = 0        # RISK 0-100, higher = worse
    social_engineering_indicators: list[str] = Field(default_factory=list)
    duress_flag: bool = False
    duress_reason: str | None = None           # must never name the scheme, marker or position
    channel_timeline: list[ChannelEvent] = Field(default_factory=list)
    device_info: DeviceInfo = Field(default_factory=DeviceInfo)

    # --- A-owned extensions (§6.6) -----------------------------------------------------
    detector_reports: list[DetectorReport] = Field(default_factory=list)
    detector_disagreement: float = 0
    voice_abstain: bool = False
    video_abstain: bool = False
    replay_similarity: ReplaySimilarity | None = None
    freshness_token_echoed: bool | None = None  # None = never issued, False = issued and missed
    channel_switch_flags: list[str] = Field(default_factory=list)
    origin_channel_id: str = ""
    stylometry_features: dict[str, Any] | None = None

    def media_scores_present(self) -> bool:
        """True when any media modality actually scored. Used only for coverage, never
        for `intent_confidence` — that exclusion is the product (§6.6)."""
        return any(
            s is not None
            for s in (self.deepfake_voice_score, self.deepfake_video_score)
        )

# --------------------------------------------------- §6.3 RiskAssessment parts (B emits)

class RiskDimension(Outbound):
    """§6.3's `{score, reasons}` pair, with Invariant 7 enforced at construction time."""

    score: float = 0
    reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _invariant_7(self) -> RiskDimension:
        if self.score > MATERIALITY_THRESHOLD and not self.reasons:
            raise ValueError(
                f"Invariant 7: score {self.score} is populated but reasons is empty."
            )
        return self


class ContributionRow(Outbound):
    """The frozen `{factor, raw_score, weight, points, evidence[]}` plus B audit columns.

    C renders `points` as the bar chart. `abstained` rows carry `weight 0` and are still
    emitted — showing what did *not* count is most of the abstention story.
    """

    factor: str
    raw_score: float
    weight: float
    points: float
    evidence: list[str] = Field(default_factory=list)
    # additive, safe to ignore
    dimension: str = ""
    reason: str = ""
    evidence_ref: str = ""
    effective_weight: float = 0.0              # weight renormalised over present coverage
    abstained: bool = False
    abstain_reason: str = ""


class FieldChange(Outbound):
    """One `{field, from, to}` inside a counterfactual. `from` is a Python keyword."""

    field: str
    from_: Any = Field(default=None, alias="from", serialization_alias="from")
    to: Any = None

class Counterfactual(Outbound):
    """"This would have APPROVED if…" — greedy arithmetic over the contribution table."""

    would_be_decision: Decision
    changes: list[FieldChange] = Field(default_factory=list)
    points_delta: float = 0


class TopBlockingFactor(Outbound):
    factor: str
    points: float
    plain_english: str


class ComprehensionChallenge(Outbound):
    """§6.6. `expected_answer_hash` carries a KEYED HMAC, not a bare digest.

    A plain sha256 of "640000" is a rainbow table with six entries. The key name stays
    `expected_answer_hash` because the contract is frozen; the value is
    `hmac_sha256(server secret, canonical(answer))`, which is useless without the secret.
    The cleartext answer is never stored and never returned.
    """

    type: ChallengeType
    prompt: str
    options: list[str] = Field(default_factory=list)
    expected_answer_hash: str = ""
    ttl_seconds: int = 0
    # additive
    challenge_id: str = ""
    attempts_allowed: int = 2


class ChannelIndependence(Outbound):
    """`satisfied` is machine-checked by B11, never asserted by a caller."""

    origin_channel_id: str = ""
    required_verification_class: str = "first_party"
    satisfied: bool = False
    # additive
    verification_channel_id: str = ""
    code: str = ""                             # SAME_CHANNEL | SAME_DEVICE_FAMILY |
    explanation: str = ""                      # UNTRUSTED_VERIFIER | INDEPENDENT | PENDING

class GraphNode(Outbound):
    """B19 caps a graph at 14 nodes with exactly one `emphasis: true`."""

    id: str
    label: str
    kind: str = "beneficiary"                  # executive | beneficiary | bank | org
    emphasis: bool = False
    trust: str = ""                            # trusted | established | emerging | unknown


class GraphEdge(Outbound):
    source: str
    target: str
    label: str = ""
    weight: float = 0
    kind: str = ""


class BeneficiaryGraph(Outbound):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class FingerprintDelta(Outbound):
    """`crypto.fingerprint.FieldDelta` on the wire. Values are already redacted."""

    field: str
    expected: str
    presented: str
    severity: str                              # critical | material | cosmetic


class ReasonDetail(Outbound):
    """§16.7's structured reason. `risk_reasons` stays the frozen array of plain strings."""

    code: str
    severity: str                              # critical | material | cosmetic | info
    text: str
    evidence_ref: str = ""

# ---------------------------------------------------------------- §6.5 CapabilityToken

class TokenScope(Outbound):
    """`max_amount` is the reviewed amount in minor units. It is a ceiling, not headroom."""

    action: Action
    destination_account: str                   # exact match required at redemption
    max_amount: int                            # integer minor units
    currency: str = "INR"


class CapabilityToken(Outbound):
    """§6.5 — Invariant 9 made concrete. One payment, one redemption, one window.

    "The CFO approved something" becomes "this exact payment, once, before 14:32, up to
    ₹10,00,000". The MAC pre-image is the canonical form of every field except `mac` and
    `redeemed_at`; `contracts/CANONICAL_JSON_VECTORS.json` pins that rule for Team C.
    """

    token_id: str
    transaction_id: str
    transaction_fingerprint: str
    scope: TokenScope
    issued_at: str
    expires_at: str
    single_use: bool = True
    redeemed_at: str | None = None
    policy_version: str = "0.0.0"
    mac: str = ""

    #: Excluded from the MAC pre-image: `mac` cannot cover itself, and `redeemed_at`
    #: is written after issuance, so covering it would invalidate the token on redemption.
    MAC_EXCLUDED: ClassVar[frozenset[str]] = frozenset({"mac", "redeemed_at"})

    def mac_preimage(self) -> dict[str, Any]:
        return {k: v for k, v in self.wire().items() if k not in self.MAC_EXCLUDED}

# ------------------------------------------------------------------ §6.3 RiskAssessment

class RiskAssessment(Outbound):
    """§6.3 base + §6.6 B extensions + a small additive set §16.7 asks for.

    `decision` is written by `policy/decide.py` and by nothing else (Invariant 2).
    `investigation_summary` is the only field an LLM may author.
    """

    # --- frozen base ------------------------------------------------------------------
    transaction_id: str
    risk_score: float = 0                      # RISK 0-100
    risk_reasons: list[str] = Field(default_factory=list)
    identity_confidence: float = 0             # AUTHENTICITY passthrough from SignalBundle
    communication_authenticity: float = 0      # AUTHENTICITY passthrough
    intent_confidence: float = 0               # NOT identity. No media score feeds this.
    semantic_drift_score: float = 0            # RISK, higher = bigger mismatch
    transaction_fingerprint: str = ""
    fingerprint_status: FingerprintStatus = FingerprintStatus.NOT_YET_VERIFIED
    beneficiary_risk: RiskDimension = Field(default_factory=RiskDimension)
    behavioral_risk: RiskDimension = Field(default_factory=RiskDimension)
    decision: Decision = Decision.CHALLENGE    # safe default: never APPROVE by omission
    recommended_action: str = ""
    investigation_summary: str = ""            # LLM-authored, decision-irrelevant
    requires_out_of_band_verification: bool = False
    duress_escalation: bool = False

    # --- frozen §6.6 extensions, defaults exactly as tabled ----------------------------
    contribution_table: list[ContributionRow] = Field(default_factory=list)
    counterfactuals: list[Counterfactual] = Field(default_factory=list)
    top_blocking_factor: TopBlockingFactor | None = None
    intent_confidence_components: dict[str, float] = Field(default_factory=dict)
    hard_overrides_fired: list[str] = Field(default_factory=list)
    policy_version: str = "0.0.0"
    policy_hash: str = ""
    capability_token: CapabilityToken | None = None
    cooldown_seconds: int = 0
    breaker_state: BreakerState = BreakerState.CLOSED
    secondary_approver_required: bool = False
    secondary_approver_id: str | None = None
    secondary_approver_rationale: str = ""
    comprehension_challenge: ComprehensionChallenge | None = None
    channel_independence: ChannelIndependence = Field(default_factory=ChannelIndependence)
    extraction_divergence_penalty: float = 0
    degraded_mode: bool = False
    latency_ms: dict[str, float] = Field(default_factory=dict)
    beneficiary_graph: BeneficiaryGraph | None = None

    # --- B additive (§16.7 plus B internals). Every one has a default, so C may ignore
    #     the whole block and still render a correct console. ------------------------------
    band_outcome: Decision = Decision.CHALLENGE   # what the score alone would have said
    override_applied: str | None = None           # "HO-1".."HO-8" | "BREAKER" | "DURESS"
    coverage: float = 0.0                         # 0-1 fraction of weight actually present
    required_actions: list[str] = Field(default_factory=list)
    reasons_detailed: list[ReasonDetail] = Field(default_factory=list)
    fingerprint_deltas: list[FingerprintDelta] = Field(default_factory=list)
    intent_confidence_excluded_signals: list[str] = Field(default_factory=list)
    replay_risk: float = 0                        # RISK 0-100
    freshness_status: str = "NOT_APPLICABLE"
    nonce: str = ""                               # minted by B2; C echoes it in the record
    validity_window: dict[str, str] = Field(default_factory=dict)  # {start_iso, end_iso}
    amount_minor_units: int | None = None         # integer paise, so C never parses a float
    beneficiary_id: str | None = None             # resolved registry id, if any
    executive_id: str | None = None               # `requester` resolved to an actor id
    degraded_reason: str = ""
    assessed_at: str = ""
    deterministic: bool = True

    @model_validator(mode="after")
    def _invariants(self) -> RiskAssessment:
        # Invariant 7 — a populated score with an empty reasons array fails validation.
        if self.risk_score > MATERIALITY_THRESHOLD and not self.risk_reasons:
            raise ValueError("Invariant 7: risk_score is populated but risk_reasons is empty.")
        # Invariant 4 — a mismatch is fatal. Belt-and-braces on top of HO-1 so that no
        # future edit to decide.py can smuggle an approval past a broken binding.
        if self.fingerprint_status is FingerprintStatus.MISMATCH and self.decision is not Decision.BLOCK:
            raise ValueError(
                f"Invariant 4: fingerprint_status MISMATCH must BLOCK, got {self.decision.value}."
            )
        # Invariant 9 — no capability without an approval, and never a reusable one.
        if self.capability_token is not None:
            if self.decision is not Decision.APPROVE:
                raise ValueError("Invariant 9: capability token minted without APPROVE.")
            if not self.capability_token.single_use:
                raise ValueError("Invariant 9: capability tokens are single-use by definition.")
            # Invariant 5's teeth. The duress path must *look* routine to the requester,
            # which means `decision` may be APPROVE — but nothing may actually execute.
            # Withholding the capability is what makes the flow safe and silent at once.
            if self.duress_escalation:
                raise ValueError(
                    "Invariant 5: a duress escalation must never mint a capability token."
                )
        return self

# --------------------------------------------- §6.4 AuthorizationRecord (C produces it)

class DeviceSignature(Inbound):
    """C's WebCrypto signature. Wire format is frozen in contracts/CRYPTO_WIRE_FORMAT.md."""

    alg: str = "ECDSA_P256_SHA256"
    public_key_thumbprint: str = ""
    signature_b64: str = ""                    # base64url of raw r||s, 64 bytes, no padding
    signed_payload_sha256: str = ""


class ComprehensionChallengeResult(Inbound):
    type: ChallengeType | None = None
    answered_correctly: bool = False
    attempts: int = 0
    elapsed_ms: int = 0


class AuthorizationRecord(Inbound):
    """B does not produce this — it validates it at redemption and replay.

    Defined here so B can parse C's payload without importing anything C owns. Every field
    keeps a default because a partial record must be rejected by policy with a reason, not
    by a 422 with a stack trace.
    """

    # --- frozen base ------------------------------------------------------------------
    transaction_id: str
    executive_id: str = ""
    transaction_fingerprint: str = ""
    verification_method: VerificationMethod = VerificationMethod.NONE
    verification_result: VerificationResult = VerificationResult.PENDING
    nonce: str = ""
    issued_at: str = ""
    expires_at: str = ""
    final_outcome: FinalOutcome | None = None
    audit_notes: str = ""

    # --- C-owned extensions (§6.6) -----------------------------------------------------
    comprehension_challenge_result: ComprehensionChallengeResult | None = None
    device_signature: DeviceSignature | None = None
    origin_channel: str = ""
    verification_channel: str = ""
    channel_independent: bool = False
    audit_seq: int = 0
    prev_hash: str = ""
    record_hash: str = ""
    redaction_applied: bool = False
    capability_token_id: str | None = None
    silent_escalation: bool = False


# ----------------------------------------------------------------- B-internal only

class AssessInput(Inbound):
    """What `POST /v1/assess-risk` accepts. Not a shared contract — B owns this shape.

    `authorization` and `verification_channel_id` are only present on the second pass,
    after C has collected a human response, which is when PC-1 and PC-4 can actually pass.
    """

    intent: TransactionIntent
    signals: SignalBundle | None = None
    authorization: AuthorizationRecord | None = None
    presented_fingerprint: str | None = None
    presented_token: CapabilityToken | None = None
    verification_channel_id: str = ""
    verification_channel: str = ""
    verification_device_id: str = ""
    challenge_answer: str | None = None        # never logged, never echoed back
    challenge_id: str = ""
    now_iso: str | None = None                 # replay only; the clock is injected otherwise
    scenario_id: str | None = None

__all__ = [
    "MATERIALITY_THRESHOLD",
    "TOKENABLE_ACTIONS",
    "Action",
    "AmountNormalization",
    "AssessInput",
    "AuthorizationRecord",
    "BeneficiaryGraph",
    "BreakerState",
    "CapabilityToken",
    "ChallengeType",
    "Channel",
    "ChannelEvent",
    "ChannelIndependence",
    "ComprehensionChallenge",
    "ComprehensionChallengeResult",
    "ContributionRow",
    "Counterfactual",
    "Decision",
    "DetectorReport",
    "DeterministicIntent",
    "DeviceInfo",
    "DeviceSignature",
    "ExtractionMode",
    "FieldChange",
    "FinalOutcome",
    "FingerprintDelta",
    "FingerprintStatus",
    "GraphEdge",
    "GraphNode",
    "Inbound",
    "Outbound",
    "ReasonDetail",
    "ReplaySimilarity",
    "RiskAssessment",
    "RiskDimension",
    "SignalBundle",
    "TokenScope",
    "TopBlockingFactor",
    "TransactionIntent",
    "Urgency",
    "VerificationMethod",
    "VerificationResult",
    "to_paise",
]
