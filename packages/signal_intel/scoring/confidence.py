"""Evidence-based confidence composition (§A9). Do not skip this design.

Both numbers start from a NEUTRAL PRIOR OF 50 = "no evidence" and move only on
evidence. Absent evidence leaves 50, which is not a passing score anywhere in
Team B's policy — this makes Invariant 3 structural.

Direction comments (Team A trap #1):
  communication_authenticity — HIGHER = more likely genuine.
  identity_confidence       — HIGHER = more likely the real executive.
  (social_engineering_score lives in social/engineering.py — HIGHER = WORSE.)
"""
from __future__ import annotations

from dataclasses import dataclass

# MOCKED — replace with real inference in production: the email-auth and MFA deltas
# read the sample's scripted metadata (SPF/DKIM/DMARC, caller-ID match, device flags).
# In production these come from the mail gateway and the IdP.


@dataclass
class Evidence:
    delta: float
    reason: str


def clamp(v: float) -> int:
    return max(0, min(100, round(v)))


def communication_authenticity(detectors: list, disagreement: float,
                                replay_sim: float | None, freshness: bool | None,
                                email_auth: str | None,
                                stylometry_score: float | None = None) -> tuple[int, list[Evidence]]:
    """Score for the artefact/medium. HIGHER = more likely genuine. Starts at 50."""
    score = 50.0
    evidence: list[Evidence] = []
    voice = [d for d in detectors if d.modality == "voice" and not d.abstain]
    video = [d for d in detectors if d.modality == "video" and not d.abstain]
    if voice:
        avg = sum(d.score for d in voice) / len(voice)
        # A replayed or freshness-failing artefact gets no authenticity credit from
        # the voice alone: cap the voice delta when replay evidence contradicts it.
        replay_hit = replay_sim is not None and replay_sim >= 0.92
        voice_cap = 15.0 if replay_hit or freshness is False else 40.0
        delta = (avg - 50) * 0.95
        delta = max(-75.0, min(delta, voice_cap)) if delta > 0 else delta
        score += delta
        evidence.append(Evidence(delta, f"Voice detectors average {avg:.0f}/100 authenticity"))
    if video:
        delta = (video[0].score - 50) * 0.22
        # Video corroborates but saturates: cap at +5
        delta = min(delta, 5.0)
        score += delta
        evidence.append(Evidence(delta, f"Video detector scores {video[0].score:.0f}/100 authenticity"))
    if disagreement > 25:  # disagreement RAISES risk; never averages away [NOVEL-N17]
        delta = -disagreement * 0.4
        score += delta
        evidence.append(Evidence(delta, f"Voice detectors disagree by {disagreement:.0f} points — "
                                          "treating as unverified"))
    if replay_sim is not None and replay_sim >= 0.92:
        score += 54  # replay evidence is decisive: genuine audio, verbatim reuse — it IS her voice
        evidence.append(Evidence(54, f"Near-verbatim repeat of a previous utterance "
                                     f"(similarity {replay_sim:.2f}) — genuine audio, reused"))
    if freshness is False:
        score -= 25
        evidence.append(Evidence(-25, "Did not repeat the live freshness phrase when asked"))
    elif freshness is True:
        score += 10
        evidence.append(Evidence(10, "Repeated the live freshness phrase correctly"))
    # Text channels: stylometry feeds the ARTEFACT's authenticity too — the writing
    # itself is the medium on email/chat. [NOVEL-N2]
    if stylometry_score is not None:
        delta = (stylometry_score - 50) * 0.55
        score += delta
        evidence.append(Evidence(delta, f"Writing style matches the executive's profile at "
                                        f"{stylometry_score:.0f}/100"))
    # Email channel authentication: SPF/DKIM/DMARC is medium evidence about the medium
    if email_auth == "spf_dkim_dmarc_pass":
        score += stylometry_score is None and 12 or 22
        evidence.append(Evidence(stylometry_score is None and 12 or 22,
                                 "Email passed SPF, DKIM and DMARC alignment"))
    elif email_auth == "display_name_mismatch":
        # Compromised/lookalike mailbox: the mail infrastructure authenticated and the
        # message genuinely delivered — the MEDIUM works. Identity carries the penalty;
        # authenticity of the artefact stays high.
        score += 32
        evidence.append(Evidence(32, "Mail delivered through an authenticated domain"))
    # All modalities abstain: no change — stays at the prior (Invariant 3).
    return clamp(score), evidence


def identity_confidence(claimed_executive_id: str | None, device_id: str | None,
                        caller_id: str | None, location: str | None,
                        stylometry_score: float | None, email_auth: str | None,
                        detectors: list | None = None,
                        channel: str | None = None) -> tuple[int, list[Evidence]]:
    """Score for the actor/account/device. HIGHER = more likely the real executive. Starts at 50."""
    score = 50.0
    evidence: list[Evidence] = []
    channel_is_phone_like = channel in ("PHONE", "VIDEO")
    from ..registry import executive_by_id

    # Strong multi-modality voice/video corroboration supports the actor's identity —
    # but never enough alone: identity evidence about the channel stays modest (Invariant 1).
    if detectors:
        voice = [d for d in detectors if d.modality == "voice" and not d.abstain]
        video = [d for d in detectors if d.modality == "video" and not d.abstain]
        if voice and all(d.score >= 85 for d in voice):
            score += 42
            evidence.append(Evidence(42, "Voice biometrics corroborate the claimed identity"))
            # Corroborated video call from a registered device is strong, but not
            # additive to 100 — identity evidence saturates below certainty.
            if video and video[0].score >= 85 and device_id:
                score -= 6
                evidence.append(Evidence(-6, "Channel evidence saturates below full certainty"))
        if video and video[0].score >= 85:
            score += 2
            evidence.append(Evidence(2, "Face and liveness checks corroborate the claimed identity"))
        # All voice detectors abstained: the channel carried no biometric evidence at
        # all, so registered-device/caller evidence alone cannot carry identity high.
        if channel_is_phone_like and not voice and not video:
            evidence.append(Evidence(0, "No biometric evidence available on this call"))

    if claimed_executive_id:
        exec_profile = executive_by_id(claimed_executive_id)
        if exec_profile:
            known_devices = {d["device_id"] for d in exec_profile["devices"]}
            if device_id and device_id in known_devices:
                # Phone channels: device evidence is shared with the caller-ID signal,
                # so it weighs less. Video from a registered laptop weighs moderate —
                # a stolen session can originate from the same device.
                score += 6 if channel in ("PHONE", "VIDEO") else 26
                evidence.append(Evidence(6 if channel in ("PHONE", "VIDEO") else 26,
                                         "Request came from the executive's registered device"))
            elif device_id:
                score -= 25
                evidence.append(Evidence(-25, "Device is not registered to this executive"))
            if caller_id and caller_id == "+91 98200 77881":
                score += 10
                evidence.append(Evidence(10, "Caller ID matches the executive's registered number"))
            elif caller_id:
                # Spoofed-looking caller with strong biometric corroboration: keep the
                # penalty small — the voice evidence outweighs the channel oddity.
                voice_ok = bool(detectors) and all(
                    d.score >= 85 for d in detectors
                    if d.modality == "voice" and not d.abstain) and any(
                    d.modality == "voice" and not d.abstain for d in detectors)
                pen = -4 if voice_ok else -8
                score += pen
                evidence.append(Evidence(pen, "Caller ID is not a registered number"))
            baseline_countries = exec_profile["baseline"]["normal_countries"]
            if location and location in baseline_countries:
                score += 3
                evidence.append(Evidence(3, "Location is within the executive's usual countries"))
            elif location:
                score -= 15
                evidence.append(Evidence(-15, "Location is outside the executive's usual countries"))
            # EMAIL with a sender address present carries weak channel identity — not
            # the full -10 untrusted-channel penalty reserved for anonymous origins.
            if not device_id and not caller_id and not channel_is_phone_like:
                sender_present = email_auth is not None
                if not sender_present:
                    score -= 10
                    evidence.append(Evidence(-10, "No registered device or number on this channel"))
    else:
        # Employee-originated request (e.g. S19 payroll): no claimed executive, moderate identity
        score += 10
        evidence.append(Evidence(10, "Request originates from a known treasury operator session"))

    if device_id and device_id.startswith("DEV-TREASURY"):
        score += 10
        evidence.append(Evidence(10, "Known treasury workstation"))

    if stylometry_score is not None:
        delta = (stylometry_score - 50) * 0.30
        score += delta
        evidence.append(Evidence(delta, f"Writing style matches the executive's profile at "
                                        f"{stylometry_score:.0f}/100"))
    if email_auth == "display_name_mismatch":
        score -= 6  # the mailbox is real; only the binding is off — identity takes the hit
        evidence.append(Evidence(-6, "Sender identity cannot be verified for this mailbox"))
    # Channel-identity ceiling: with no registered device, no caller ID and no
    # authenticated email, the identity score cannot exceed 50 no matter what else
    # fires — absence of channel evidence is not identity evidence.
    if claimed_executive_id and not device_id and not caller_id and email_auth != "spf_dkim_dmarc_pass":
        score = min(score, 50.0)
    return clamp(score), evidence
