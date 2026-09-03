"""Detector harness: abstention + ensemble disagreement [NOVEL-N16a] [NOVEL-N17].

Every detector is MOCKED and shaped exactly like a real one, so a real model drops in
without touching a caller. Scores are AUTHENTICITY: higher = more likely genuine.

Abstention is honest: score=None, abstain=True, abstain_reason set. NEVER a default
score — not 50, not 100, not the mean (Invariant 3; Team A trap #2).
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from ..config import CONFIG

# MOCKED — replace with real inference in production
# Scripted detector outputs come from the sample's detector_script block so the demo
# is deterministic. When no script is given, small seeded jitter models detector noise.

MIN_CLIP_SECONDS = 4.0
MIN_SNR_DB = 12.0
KNOWN_CODECS = {"opus", "aac", "pcm", "mp3", "wav", "amr-wideband"}


@dataclass(frozen=True)
class DetectorReport:
    name: str            # "spectral_v1"
    modality: str        # "voice" | "video" | "text"
    score: float | None  # 0-100 AUTHENTICITY (higher = more likely genuine). None if abstain.
    confidence: float    # 0-100 — detector's certainty about its own score
    abstain: bool
    abstain_reason: str | None  # CLIP_TOO_SHORT | LOW_SNR | UNKNOWN_CODEC | NO_MODALITY
    latency_ms: int


_ABSTAIN_REASON_BY_CONDITION = [
    ("CLIP_TOO_SHORT", lambda ctx: ctx.get("clip_duration_s") is not None and ctx["clip_duration_s"] < MIN_CLIP_SECONDS),
    ("LOW_SNR", lambda ctx: ctx.get("snr_db") is not None and ctx["snr_db"] < MIN_SNR_DB),
    ("UNKNOWN_CODEC", lambda ctx: ctx.get("codec") is not None and ctx["codec"] not in KNOWN_CODECS),
    ("NO_MODALITY", lambda ctx: ctx.get("modality_present") is False),
]


def _abstain_reason(ctx: dict) -> str | None:
    for reason, test in _ABSTAIN_REASON_BY_CONDITION:
        try:
            if test(ctx):
                return reason
        except Exception:
            continue
    return None


def _seeded_jitter(base: float, name: str, tx_id: str) -> float:
    """Deterministic per-detector jitter (seeded RNG — shared-context rule 11).
    Seeded on the stable sample_id when present so replays are byte-identical."""
    h = hashlib.sha256(f"{CONFIG.seed}|{name}|{tx_id}".encode()).digest()
    r = random.Random(int.from_bytes(h[:8], "big"))
    return max(0.0, min(100.0, base + r.uniform(-2.0, 2.0)))


def _report(name: str, modality: str, base: float | None, ctx: dict, tx_id: str) -> DetectorReport:
    # A detector abstains when: clip too short, SNR too low, unknown codec, or modality absent.
    reason = _abstain_reason({**ctx, "modality_present": base is not None})
    if base is None or reason:
        # NEVER substitute a default score for an abstention (Invariant 3).
        return DetectorReport(name=name, modality=modality, score=None, confidence=0.0,
                               abstain=True, abstain_reason=reason or "NO_MODALITY", latency_ms=1)
    score = _seeded_jitter(base, name, tx_id)
    return DetectorReport(name=name, modality=modality, score=round(score, 1),
                          confidence=90.0, abstain=False, abstain_reason=None, latency_ms=120)


def score_all(detector_script: dict, tx_id: str, channel: str) -> list[DetectorReport]:
    """Run the two independent voice detectors + one video detector.

    Two independent detectors on the same modality is the entire point of [NOVEL-N17]:
    disagreement RAISES risk; it never averages away.
    """
    reports = []
    voice_present = detector_script.get("spectral_v1") is not None or detector_script.get("prosody_v2") is not None
    audio_ctx = {
        "clip_duration_s": detector_script.get("clip_duration_s"),
        "snr_db": detector_script.get("snr_db"),
        "codec": detector_script.get("codec"),
    }
    video_ctx = {**audio_ctx, "modality_present": detector_script.get("video_v1") is not None}

    if channel in ("PHONE", "VIDEO"):
        reports.append(_report("spectral_v1", "voice",
                               detector_script.get("spectral_v1"), audio_ctx, tx_id))
        reports.append(_report("prosody_v2", "voice",
                               detector_script.get("prosody_v2"), audio_ctx, tx_id))
    if channel == "VIDEO":
        reports.append(_report("video_v1", "video",
                               detector_script.get("video_v1"), video_ctx, tx_id))
    if not voice_present and channel not in ("PHONE", "VIDEO"):
        # text channels: no audio modality at all
        reports.append(DetectorReport(name="spectral_v1", modality="voice", score=None,
                                      confidence=0.0, abstain=True, abstain_reason="NO_MODALITY",
                                      latency_ms=0))
    return reports


def detector_disagreement(reports: list[DetectorReport]) -> float:
    """|spectral_v1 - prosody_v2| when both score; 0 if either abstains. Raises risk, never averages."""
    by_name = {r.name: r.score for r in reports if r.name in ("spectral_v1", "prosody_v2") and not r.abstain}
    if len(by_name) < 2:
        return 0.0
    return round(abs(by_name["spectral_v1"] - by_name["prosody_v2"]), 1)


def voice_abstain(reports: list[DetectorReport]) -> bool:
    voice = [r for r in reports if r.modality == "voice"]
    return bool(voice) and all(r.abstain for r in voice)


def video_abstain(reports: list[DetectorReport]) -> bool:
    video = [r for r in reports if r.modality == "video"]
    return bool(video) and all(r.abstain for r in video)
