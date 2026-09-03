"""Error taxonomy (00_SHARED_CONTEXT.md §14).

The fail-safe direction is always toward friction. `safe_outcome` is CHALLENGE or BLOCK
and never APPROVE — `test_no_error_path_approves` asserts that over every member of the
taxonomy, and the constructor asserts it again at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IntentLockError(Exception):
    """Base for every taxonomy error. Serialises to the frozen §14 error body."""

    error_code: str = "INTERNAL"
    message: str = "Unclassified failure"
    safe_outcome: str = "CHALLENGE"
    detail: dict = field(default_factory=dict)
    http_status: int = 422

    def __post_init__(self) -> None:
        if self.safe_outcome == "APPROVE":
            raise AssertionError(
                f"{self.error_code}: safe_outcome may never be APPROVE. "
                "Any code path that turns an error into APPROVE is a critical bug (§14)."
            )
        Exception.__init__(self, f"{self.error_code}: {self.message}")

    def body(self) -> dict:
        out = {
            "error_code": self.error_code,
            "message": self.message,
            "safe_outcome": self.safe_outcome,
        }
        if self.detail:
            out["detail"] = self.detail
        return out


def _err(code: str, default_message: str, safe: str = "CHALLENGE", status: int = 422):
    class _E(IntentLockError):
        def __init__(self, message: str = default_message, **detail):
            super().__init__(
                error_code=code, message=message, safe_outcome=safe, detail=detail,
                http_status=status,
            )

    _E.__name__ = "".join(p.capitalize() for p in code.split("_")) + "Error"
    _E.error_code_value = code  # type: ignore[attr-defined]
    _E.safe_outcome_value = safe  # type: ignore[attr-defined]
    return _E


# --- §14, verbatim codes. safe_outcome is per §14's "degrade toward friction" column. ---
LlmUnavailable = _err("LLM_UNAVAILABLE", "Narrative unavailable; decision unaffected.", "CHALLENGE")
ExtractionMalformed = _err("EXTRACTION_MALFORMED", "Extraction output failed schema validation.")
IntentIncomplete = _err("INTENT_INCOMPLETE", "A critical intent field is missing.")
DetectorAbstain = _err("DETECTOR_ABSTAIN", "A detector could not score this sample.")
UpstreamUnavailable = _err("UPSTREAM_UNAVAILABLE", "An upstream service did not respond.", "CHALLENGE", 503)
FingerprintMismatch = _err("FINGERPRINT_MISMATCH", "Executed transaction differs from the approved one.", "BLOCK")
SameChannelVerification = _err("SAME_CHANNEL_VERIFICATION", "Verification arrived on the channel that raised the request.", "CHALLENGE")
NonceReplay = _err("NONCE_REPLAY", "This authorization nonce was already consumed.", "BLOCK")
AuthExpired = _err("AUTH_EXPIRED", "The authorization window has expired.", "CHALLENGE")
TokenScopeViolation = _err("TOKEN_SCOPE_VIOLATION", "Capability token presented outside its scope.", "BLOCK")
AuditChainBroken = _err("AUDIT_CHAIN_BROKEN", "The audit chain failed verification.", "BLOCK")
PromptInjectionSuspected = _err("PROMPT_INJECTION_SUSPECTED", "Instruction-like content found in untrusted input.", "BLOCK")

# --- Team B internals that still owe callers a safe outcome. ---
ExtractionUnavailable = _err("EXTRACTION_UNAVAILABLE", "The deterministic parser could not read a hard field.")
PolicyVersionMismatch = _err("POLICY_VERSION_MISMATCH", "Artefact was produced under a different policy version.", "BLOCK")
SchemaViolation = _err("SCHEMA_VIOLATION", "Payload failed contract schema validation.", "CHALLENGE", 400)
NotApproved = _err("NOT_APPROVED", "Refusing to mint a capability token for a non-APPROVE decision.", "BLOCK", 409)
BreakerOpen = _err("BREAKER_OPEN", "The organisation-level velocity breaker is open.", "BLOCK", 409)

TAXONOMY = (
    LlmUnavailable, ExtractionMalformed, IntentIncomplete, DetectorAbstain,
    UpstreamUnavailable, FingerprintMismatch, SameChannelVerification, NonceReplay,
    AuthExpired, TokenScopeViolation, AuditChainBroken, PromptInjectionSuspected,
    ExtractionUnavailable, PolicyVersionMismatch, SchemaViolation, NotApproved, BreakerOpen,
)
