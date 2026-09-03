"""B11 — channel-independence enforcement. [NOVEL-N21a]

The channel that requests a transaction may never be the channel that verifies it.
Independence is at the FAMILY level, not the id level: replying from a second WhatsApp
account on the same handset is not independence, and comparing raw ids would call it one
— which is worse than not checking.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..policy.constants import CHANNEL_PENALTIES, CHANNEL_SWITCH_FLAG_POINTS

#: Family map. Verification must land in a FIRST-PARTY surface (console / mobile_app),
#: because those are the only channels whose integrity B can reason about.
CHANNEL_FAMILIES: dict[str, str] = {
    "voice_call": "telephony", "phone": "telephony", "whatsapp_call": "telephony",
    "sip": "telephony",
    "email": "messaging", "whatsapp_text": "messaging", "sms": "messaging",
    "chat": "messaging",
    "teams_call": "conferencing", "zoom": "conferencing", "video": "conferencing",
    "collab_platform": "conferencing",
    "console": "first_party", "mobile_app": "first_party",
}

FIRST_PARTY = ("console", "mobile_app")


@dataclass(frozen=True)
class ChannelVerdict:
    independent: bool
    code: str              # INDEPENDENT | SAME_CHANNEL | SAME_DEVICE_FAMILY | UNTRUSTED_VERIFIER | PENDING
    explanation: str


def _family(channel: str) -> str:
    return CHANNEL_FAMILIES.get((channel or "").strip().lower(), "unmapped")


def origin_channel_id(channel: str, session_id: str, device_id: str, identity: str) -> str:
    """A's formula, mirrored exactly (§14 of Team A's brief) so both teams hash alike."""
    import hashlib
    return hashlib.sha256(
        f"{channel}|{session_id}|{device_id}|{identity}".encode()
    ).hexdigest()[:32]


def verdict(
    origin_channel: str,
    verification_channel: str,
    *,
    origin_device_id: str = "",
    verification_device_id: str = "",
) -> ChannelVerdict:
    """Machine-checked independence. A blank verification channel is PENDING, not a pass."""
    o = (origin_channel or "").strip().lower()
    v = (verification_channel or "").strip().lower()
    if not v:
        return ChannelVerdict(
            False, "PENDING",
            "Approval has not completed on a second channel yet; confirmation must arrive "
            "on a first-party surface in a different channel family from the request.",
        )
    if _family(o) == "messaging" and _family(v) == "messaging" and o == v:
        return ChannelVerdict(
            False, "SAME_CHANNEL",
            "Verification arrived on the same channel that made the request; complete the "
            "approval in the console instead of replying to the message.",
        )
    if o == v:
        return ChannelVerdict(
            False, "SAME_CHANNEL",
            "Verification arrived on the same channel that made the request; complete the "
            "approval in the console instead of answering on the same call.",
        )
    if (_family(o) == _family(v) and _family(o) not in ("first_party", "unmapped")
            and (not origin_device_id or not verification_device_id
                 or origin_device_id == verification_device_id)):
        return ChannelVerdict(
            False, "SAME_DEVICE_FAMILY",
            "Verification used a different app on the same device and channel family; use "
            "the console on a separate registered device.",
        )
    if v not in FIRST_PARTY:
        return ChannelVerdict(
            False, "UNTRUSTED_VERIFIER",
            "Verification must complete in a first-party channel (console or registered "
            "mobile app), not over a channel the requester controls.",
        )
    return ChannelVerdict(
        True, "INDEPENDENT",
        f"Request arrived on {o or 'an unknown channel'}; verification completed on {v}, "
        f"a first-party channel in a different family.",
    )


def dimension(
    *, channel_verdict_code: str, channel_switch_flags: tuple[str, ...] = ()
) -> float:
    """The `device_channel` risk contribution (§14): penalty + 12 per switch flag."""
    base = float(CHANNEL_PENALTIES.get(channel_verdict_code, 45.0))
    return max(0.0, min(100.0, base + CHANNEL_SWITCH_FLAG_POINTS * len(channel_switch_flags)))
