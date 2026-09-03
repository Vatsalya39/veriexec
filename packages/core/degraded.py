"""B18 — degraded mode. [NOVEL-N25a]

The claim: kill the language model and the decisions do not change. Only the prose does.
`MINIMAL` mode must still get S06 right — and it will, because S06 blocks on HO-1, which
needs nothing but the fingerprint and the request. Modes are served side (a POST to
`/v1/mode`), never client-only, so the change is real and lands in the audit log.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DegradedMode(str, Enum):
    FULL = "FULL"                 # LLM available
    NO_LLM = "NO_LLM"             # model dead/timeout -> template narratives
    NO_DETECTORS = "NO_DETECTORS"  # A's media detectors down -> abstain + renormalize
    MINIMAL = "MINIMAL"           # both -> fingerprint + rules + baselines only


@dataclass(frozen=True)
class ModeState:
    mode: DegradedMode = DegradedMode.FULL

    def banner(self) -> str:
        """The user-visible string C renders next to the kill switch."""
        return {
            DegradedMode.FULL: "All systems available.",
            DegradedMode.NO_LLM: "LLM: OFF — deterministic core only. Decisions unchanged.",
            DegradedMode.NO_DETECTORS: "Media detectors unavailable; authenticity evidence "
                                        "abstains and coverage is renormalised.",
            DegradedMode.MINIMAL: "MINIMAL: no LLM, no media detectors. Fingerprint, rules "
                                   "and baselines only — decisions unchanged.",
        }[self.mode]


_CURRENT = ModeState()


def current() -> DegradedMode:
    return _CURRENT.mode


def set_mode(mode: DegradedMode | str) -> DegradedMode:
    """Server-side state change; the service audits it as MODE_CHANGED."""
    global _CURRENT
    _CURRENT = ModeState(mode=DegradedMode(mode))
    return _CURRENT.mode


def reset(mode: DegradedMode | str = DegradedMode.FULL) -> None:
    """Tests and service restarts."""
    set_mode(mode)


def detector_scores_abstain() -> bool:
    """In NO_DETECTORS/MINIMAL, every media score reads as an abstention — Invariant 3's
    sharpest form: the control keeps working, it just stops claiming evidence it lost."""
    return _CURRENT.mode in (DegradedMode.NO_DETECTORS, DegradedMode.MINIMAL)


def llm_enabled() -> bool:
    return _CURRENT.mode in (DegradedMode.FULL, DegradedMode.NO_DETECTORS)
