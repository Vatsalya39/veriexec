"""Pipeline orchestrator: raw communication -> (TransactionIntent, SignalBundle).

Builds the two frozen-contract artefacts with every v1.1 extension key present,
always, with defaults when not applicable (shared context §6.6). This is the only
module Teams B and C need to understand.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid

from .config import now
from .detectors.harness import (detector_disagreement, score_all, video_abstain,
                                voice_abstain)
from .duress.detector import detect_duress
from .extract.deterministic import (ExtractionResult, build_deterministic_intent_object,
                                    extract_deterministic)
from .extract.llm import get_client, llm_extract
from .replay.replay import check_replay, freshness_echoed, issue_freshness
from .registry import resolve_beneficiary_dates
from .scoring.confidence import (communication_authenticity, identity_confidence)
from .security.injection import detect_injection
from .social.engineering import merge_with_llm, rule_pass
from .stylometry.twin import score_stylometry
from .timeline.analyze import analyze_timeline, build_timeline

TEXT_CHANNELS = ("EMAIL", "CHAT", "COLLAB_PLATFORM")


def origin_channel_id(channel: str, session_id: str | None, device_id: str | None,
                     caller_id: str | None, sender_email: str | None) -> str:
    """Concrete channel/session/device identity hash — Team B refuses a verification
    whose channel identity equals this (Invariant 6 made enforceable)."""
    raw = f"{channel}|{session_id or ''}|{device_id or ''}|{caller_id or sender_email or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _extraction_confidence(critical_present: bool, paths_agree: bool, injection_free: bool) -> int:
    """40 x (critical fields present) + 30 x (paths agree) + 30 x (no injection flags).
    Documented for Team B; they consume this number directly."""
    return min(100, 40 * int(critical_present) + 30 * int(paths_agree) + 30 * int(injection_free))


def process_communication(payload: dict) -> dict:
    """Main entry: the request body of POST /v1/process-communication."""
    resolve_beneficiary_dates()
    channel = payload.get("channel", "EMAIL")
    raw_text = payload.get("raw_text_or_transcript", "") or ""
    metadata = payload.get("metadata", {}) or {}
    sample_id = payload.get("sample_id")
    detector_script = payload.get("detector_script", {}) or {}
    freshness_token = payload.get("freshness_token")

    transaction_id = str(uuid.uuid4())
    timestamp = metadata.get("timestamp") or now().isoformat()

    # ---------------- A4: injection hardening FIRST (pre-LLM) [NOVEL-N14]
    injection = detect_injection(raw_text)
    injection_flags = injection["flags"]
    working_text = injection["neutralized"]

    # ---------------- A2: deterministic extraction (the floor; authoritative on money/accounts)
    det = extract_deterministic(raw_text, claimed_executive_id=metadata.get("claimed_executive_id"),
                                channel=channel)

    # ---------------- A3: LLM enrichment (never load-bearing)
    llm_res, llm_status = llm_extract(get_client(), working_text, secrets.token_hex(8))
    if injection_flags:
        llm_res, llm_status = None, "unavailable"  # flagged input may not use the model path

    # ---------------- merge policy: deterministic wins on money and accounts
    intent_fields = _merge_intent(det, llm_res, raw_text, channel, metadata, transaction_id,
                                  timestamp, sample_id, injection_flags)

    # ---------------- A5: detectors [NOVEL-N16a] [NOVEL-N17]
    # seed jitter on the stable sample_id so Invariant 8 (replay determinism) holds
    reports = score_all(detector_script, sample_id or transaction_id, channel)
    disagreement = detector_disagreement(reports)
    v_abstain = voice_abstain(reports)
    vid_abstain = video_abstain(reports)

    # ---------------- A6: stylometry (text channels only) [NOVEL-N2]
    claimed = metadata.get("claimed_executive_id")
    sty = score_stylometry(raw_text, claimed, channel) if channel in TEXT_CHANNELS else None
    sty_score = sty.score if sty else None
    sty_features = sty.features if sty else None

    # ---------------- A10: replay + freshness [NOVEL-N18a]
    replay = check_replay(raw_text, claimed)
    replay_obj = None
    if replay.is_replay:
        replay_obj = {"max_similarity": replay.max_similarity,
                      "matched_utterance_id": replay.matched_utterance_id,
                      "method": replay.method}
    fresh = None
    if freshness_token:
        fresh = freshness_echoed(raw_text, freshness_token)
    elif payload.get("freshness_echoed") is not None:
        # The sample (or any caller) states the freshness fact directly. Previously this
        # branch was three hard-coded sample ids, so the corpus could not grow and a real
        # caller had no way to report "the voice on the line did answer the phrase".
        fresh = bool(payload["freshness_echoed"])

    # ---------------- A9: confidence composition (evidence-based, prior = 50)
    auth_score, auth_evidence = communication_authenticity(
        reports, disagreement,
        replay_obj["max_similarity"] if replay_obj else None,
        fresh, detector_script.get("email_auth"), stylometry_score=sty_score)
    ident_score, ident_evidence = identity_confidence(
        claimed, metadata.get("device_id"), metadata.get("caller_id"), metadata.get("location"),
        sty_score, detector_script.get("email_auth"), detectors=reports, channel=channel)

    # ---------------- A8: social engineering (rule pass authoritative offline)
    se_rule, se_indicators = rule_pass(raw_text)
    se_score, se_indicators, _ = merge_with_llm(se_rule, se_indicators, None)

    # ---------------- A9a: duress [NOVEL-N1a]
    duress_flag, duress_reason = detect_duress(intent_fields, claimed)

    # ---------------- A11: timeline
    timeline = build_timeline(metadata.get("prior_events", []),
                              {"timestamp": timestamp, "event": "current communication received",
                               "channel": channel})
    switch_flags, switch_indicators = analyze_timeline(timeline, claimed)
    se_indicators = se_indicators + switch_indicators
    if disagreement > 25:
        se_indicators.append(f"Voice detectors disagree by {disagreement:.0f} points — "
                             "treating as unverified")
    if replay_obj:
        se_indicators.append(f"Utterance is a near-verbatim repeat of a previous "
                             f"communication (similarity {replay_obj['max_similarity']:.2f})")

    # ---------------- assemble SignalBundle (base + all extensions, defaults always)
    signals = {
        "transaction_id": transaction_id,
        "identity_confidence": ident_score,      # HIGHER = more likely the real executive
        "communication_authenticity": auth_score,  # HIGHER = more likely genuine artefact
        "deepfake_voice_score": _avg_voice(reports),  # HIGHER = more likely genuine
        "deepfake_video_score": _avg_video(reports),  # HIGHER = more likely genuine
        "stylometry_match_score": sty_score,    # HIGHER = more likely genuine writing
        "social_engineering_score": se_score,    # HIGHER = WORSE (risk score)
        "social_engineering_indicators": se_indicators,
        "duress_flag": duress_flag,
        "duress_reason": duress_reason,
        "channel_timeline": timeline,
        "device_info": {
            "device_id": metadata.get("device_id") or "",
            "known_device": _known_device(claimed, metadata.get("device_id")),
            "location": metadata.get("location") or "",
        },
        # v1.1 extensions (owner: A)
        "detector_reports": [
            {"name": r.name, "score": r.score, "confidence": r.confidence,
             "abstain": r.abstain, "abstain_reason": r.abstain_reason}
            for r in reports
        ],
        "detector_disagreement": disagreement,
        "voice_abstain": v_abstain,
        "video_abstain": vid_abstain,
        "replay_similarity": replay_obj,
        "freshness_token_echoed": fresh,
        "channel_switch_flags": switch_flags,
        "origin_channel_id": origin_channel_id(
            channel, metadata.get("session_id"), metadata.get("device_id"),
            metadata.get("caller_id"), metadata.get("sender_email")),
        "stylometry_features": sty_features,
    }

    # evidence for C's render of the derivations
    signals["identity_evidence"] = [{"delta": round(e.delta, 1), "reason": e.reason}
                                    for e in ident_evidence]
    signals["authenticity_evidence"] = [{"delta": round(e.delta, 1), "reason": e.reason}
                                        for e in auth_evidence]

    return {"intent": intent_fields, "signals": signals}


def _avg_voice(reports) -> float | None:
    voice = [r.score for r in reports if r.modality == "voice" and not r.abstain]
    return round(sum(voice) / len(voice), 1) if voice else None


def _avg_video(reports) -> float | None:
    video = [r.score for r in reports if r.modality == "video" and not r.abstain]
    return round(sum(video) / len(video), 1) if video else None


def _known_device(claimed_executive_id, device_id) -> bool:
    if not device_id or not claimed_executive_id:
        return False
    from .registry import executive_by_id
    exec_profile = executive_by_id(claimed_executive_id)
    if not exec_profile:
        return False
    return device_id in {d["device_id"] for d in exec_profile["devices"]}


def _cmp_text(value) -> str:
    return " ".join(str(value or "").casefold().split())


def _cmp_account(value) -> str:
    return "".join(c for c in str(value or "") if c.isalnum()).upper()


def _divergent_fields(det: ExtractionResult, llm_res: dict) -> list[str]:
    """Field names where the two extraction paths disagree (§6.6 `extraction_divergence`).

    Only fields both paths actually emit are compared, and only when both produced a
    value — a silent LLM is an abstention, not a disagreement, and must not be priced as
    one. The deterministic reading still wins the merge for money and accounts (§9); this
    list exists so that B can see the paths disagreed at all, which was previously
    impossible because the array was shipped hard-coded empty.
    """
    out: list[str] = []
    pairs = (
        ("action", det.action if det.action != "OTHER" else None, llm_res.get("action")
         if llm_res.get("action") != "OTHER" else None, _cmp_text),
        ("beneficiary", det.beneficiary, llm_res.get("beneficiary"), _cmp_text),
        ("destination_account", det.destination_account,
         llm_res.get("destination_account"), _cmp_account),
        ("urgency", det.urgency, llm_res.get("urgency"), _cmp_text),
        ("deadline", det.deadline, llm_res.get("deadline_text"), _cmp_text),
    )
    for name, det_value, llm_value, norm in pairs:
        a, b = norm(det_value), norm(llm_value)
        if a and b and a != b:
            out.append(name)
    return out


def _merge_intent(det: ExtractionResult, llm_res: dict | None, raw_text: str, channel: str,
                  metadata: dict, transaction_id: str, timestamp: str, sample_id,
                  injection_flags: list) -> dict:
    """Deterministic wins on money/accounts; LLM enriches purpose/deadline nuance."""
    if llm_res:
        action = det.action if det.action != "OTHER" else llm_res.get("action", "OTHER")
        beneficiary = det.beneficiary or llm_res.get("beneficiary")
        purpose = llm_res.get("purpose") or det.purpose
        deadline = det.deadline or llm_res.get("deadline_text")
        urgency = det.urgency if det.urgency != "LOW" else llm_res.get("urgency", "LOW")
        secrecy = det.secrecy_flags + [f for f in llm_res.get("secrecy_flags", [])
                                       if f not in det.secrecy_flags]
        mode = "hybrid" if (det.action != "OTHER" or det.amount) else "llm"
    else:
        action, beneficiary, purpose = det.action, det.beneficiary, det.purpose
        deadline, urgency, secrecy = det.deadline, det.urgency, det.secrecy_flags
        mode = "deterministic"

    if not raw_text.strip():
        mode = "failed"

    # Only a two-path run can disagree. With one path there is nothing to compare, so
    # `paths_agree` stays true and contributes its 30 confidence points — the same value
    # the hard-coded `True` used to produce, but now for a stated reason.
    divergence = _divergent_fields(det, llm_res) if llm_res else []
    paths_agree = not divergence
    critical_present = bool(action != "OTHER" and (det.amount or action in
                                                   ("CREDENTIAL_RESET", "PAYMENT_LIMIT_CHANGE")))
    conf = _extraction_confidence(critical_present, paths_agree, not injection_flags)

    return {
        # base contract (frozen)
        "transaction_id": transaction_id,
        "requester": det.requester or (metadata.get("claimed_executive_id") or "unknown"),
        "action": action,
        "amount": det.amount,
        "currency": det.currency,
        "beneficiary": beneficiary,
        "destination_account": det.destination_account,
        "purpose": purpose,
        "deadline": deadline,
        "urgency": urgency,
        "secrecy_flags": secrecy,
        "channel": channel,
        "raw_transcript_or_text": raw_text,
        "timestamp": timestamp,
        # v1.1 extensions (owner: A)
        "extraction_confidence": conf,
        "extraction_mode": mode,
        "deterministic_intent": build_deterministic_intent_object(det, transaction_id, timestamp),
        "extraction_divergence": divergence,
        "injection_flags": injection_flags,
        "amount_normalization": det.amount_normalization,
        "language_detected": "en-IN-hinglish" if _hinglish(raw_text) else "en",
        "origin_session_id": metadata.get("session_id") or "",
        "sample_id": sample_id,
    }


def _hinglish(text: str) -> bool:
    # "pls" is universal corporate chat English, not Hinglish — excluded deliberately
    markers = ["pandrah", "lac", "lakh to", "karod", "crore to", "jaldi",
               "pandhra", "teen", "do lakh", "karo", "nahi", "haan"]
    t = text.lower()
    return any(m in t for m in markers)
