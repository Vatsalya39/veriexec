"""The world state a scenario implies, read out of the sample rather than hardcoded. §15, §17

Four of the twenty-two scenarios cannot reach their documented outcome from the current
request alone, because the thing that makes them attacks happened *earlier*:

    S06  the executive approved ₹10,00,000 to one account; ₹45,00,000 to another is executing
    S12  three near-identical requests went to three different employees in nine minutes
    S13  the "out-of-band" verification came back on the same phone session that asked
    S16  the authorization that this request cites expired fifteen minutes ago

None of that is in `TransactionIntent`, and none of it can be, because an intent is a
statement about one request. It is in `metadata.prior_events` — and in prose, because that
is how a real case file arrives.

So this module reads the prose with **A's own extractor**. `extract_deterministic` already
knows the amount grammar (`Rs 10,00,000`), the account grammar and the beneficiary registry;
re-implementing any of that here would create a second parser that can disagree with the
first one, and a pre-image is only as good as the guarantee that both sides were projected
the same way. Running A over the prior event and B's `preimage_fields` over the result means
the reference and the current pre-image differ **only where the facts differ**.

What stays hardcoded is nothing: no sample id appears in any predicate below. The
classifiers key on the words that carry the meaning — "approval"/"issued", "expired",
"verification ... same ... <session id>" — so a twenty-third scenario written in the same
register is handled without an edit here, and a scenario whose prose says nothing yields an
empty `WorldState` and a first pass with no world state at all, which is the honest default.

The nonce is derived, not drawn. `secrets.token_hex()` here would break Invariant 8 the
moment a replay compared two runs, so it is a hash of the transaction id and the issue
time: unpredictable to a caller who does not hold the sample, identical on every replay.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from packages.core import clock
from packages.signal_intel.extract.deterministic import extract_deterministic

#: An event that *created an authorization*: something the executive did that a later request
#: can cite. Both spellings appear in the corpus ("CFO video approval:", "authorization ...
#: issued for"), and both mean the same thing to the fingerprint.
_APPROVAL = re.compile(r"\b(approv\w*|authoriz\w+\s+\S+\s+issued|issued\s+for)\b", re.I)

#: The end of one. Note this must be tested *before* `_APPROVAL`, because the expiry line
#: names the authorization too ("authorization AUTH-7741-XYZ expired").
_EXPIRY = re.compile(r"\bexpir\w+\b", re.I)

#: A verification response that came back where the request came from. Invariant 6 calls
#: this "rejected, not merely penalised", so the pipeline has to be able to *see* it.
_SAME_CHANNEL_VERIFY = re.compile(r"\bverif\w+\b.*\bsame\b", re.I)

#: A prior attempt. These feed the breaker's rolling window; they are not approvals.
_REQUEST = re.compile(r"\brequest\b", re.I)

#: `AUTH-7741-XYZ` in "authorization AUTH-7741-XYZ issued". Only an id the prose actually
#: *calls* an authorization counts: S06's approval line also contains `INV-92014` and `PO
#: 4471`, and an invoice number is not a grant of authority.
_AUTH_ID = re.compile(r"\bauthoriz\w+\s+([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)", re.I)

#: `(TTL 600s)`. A fallback for the window end when no explicit expiry event exists.
_TTL = re.compile(r"\bTTL\s+(\d+)\s*s\b", re.I)

#: The kinds this module can tell apart. `OTHER` is not a failure — S04's "genuine CFO call:
#: Sundaram customs penalty release" is a real prior event that states no amount and no
#: account, so it establishes no pre-image, and saying so is the correct answer.
KINDS = ("APPROVAL", "EXPIRY", "VERIFICATION_ON_ORIGIN", "REQUEST", "OTHER")


@dataclass(frozen=True)
class PriorEvent:
    """One line of `metadata.prior_events`, classified and (where possible) extracted."""

    at: str
    text: str
    channel: str
    kind: str
    #: A's reading of the prose. `None` for kinds where the fields carry no meaning.
    extracted: dict = field(default_factory=dict)
    authorization_id: str = ""
    ttl_seconds: int | None = None

    @property
    def states_transaction_facts(self) -> bool:
        """Did this event actually name money or a destination?

        An approval that names neither cannot be a pre-image: there is nothing for a later
        request to differ *from*, and manufacturing one out of the current request's own
        values would produce a MATCH that no executive ever granted.
        """
        return bool(self.extracted.get("amount") is not None
                    or self.extracted.get("destination_account"))


def classify(text: str) -> str:
    """Which kind of world-changing event this line describes.

    Order matters: expiry is tested first because an expiry line names its authorization,
    and a same-channel verification is tested before `REQUEST` because "verification
    response submitted" contains neither an approval nor a request but would otherwise fall
    through to `OTHER` and lose the one fact that makes S13 an attack.
    """
    if _EXPIRY.search(text):
        return "EXPIRY"
    if _SAME_CHANNEL_VERIFY.search(text):
        return "VERIFICATION_ON_ORIGIN"
    if _APPROVAL.search(text):
        return "APPROVAL"
    if _REQUEST.search(text):
        return "REQUEST"
    return "OTHER"


def _read_event(raw: dict) -> PriorEvent:
    text = str(raw.get("event") or "")
    kind = classify(text)
    extracted: dict = {}
    if kind in {"APPROVAL", "REQUEST"}:
        # A's extractor, not a second parser. `channel` is passed through because the
        # deterministic reader uses it for channel-specific grammar, and the event carries it.
        result = extract_deterministic(text, channel=str(raw.get("channel") or "EMAIL"))
        fields = getattr(result, "fields", result)
        extracted = {
            "action": getattr(fields, "action", None),
            "amount": getattr(fields, "amount", None),
            "currency": getattr(fields, "currency", None),
            "beneficiary": getattr(fields, "beneficiary", None),
            "beneficiary_id": getattr(fields, "beneficiary_matched_id", None),
            "destination_account": getattr(fields, "destination_account", None),
        }
    ttl = _TTL.search(text)
    auth_id = _AUTH_ID.search(text)
    return PriorEvent(
        at=str(raw.get("timestamp") or ""), text=text,
        channel=str(raw.get("channel") or ""), kind=kind, extracted=extracted,
        authorization_id=auth_id.group(1) if auth_id else "",
        ttl_seconds=int(ttl.group(1)) if ttl else None,
    )


@dataclass(frozen=True)
class WorldState:
    """Everything about a scenario that is true before its current request arrives.

    Deliberately flat and JSON-shaped: `run_pipeline.py` turns this into an `AssessContext`
    for the HTTP path and into `assess()` keyword arguments for the in-process path, and both
    must be able to produce it from the same sample without a second reading.
    """

    sample_id: str
    now: datetime
    events: tuple[PriorEvent, ...] = ()
    approval: PriorEvent | None = None
    authorization_id: str = ""
    #: The window of the authorization *this request cites*, and only when the case file
    #: stated an end for it. Empty is not "open forever" — it means no prior grant is being
    #: cited, so C's console mints a fresh window at signing time instead (`mint_window`).
    issued_at: str = ""
    expires_at: str = ""
    #: True when a prior event says the verification came back on the origin session (S13).
    verification_on_origin: bool = False
    #: Prior attempts, oldest first. These are what the breaker's window sees.
    prior_requests: tuple[PriorEvent, ...] = ()
    nonce: str = ""

    @property
    def has_reference(self) -> bool:
        """Is there an earlier, human-approved statement to compare this request against?"""
        return self.approval is not None and self.approval.states_transaction_facts

    @property
    def authorization_expired(self) -> bool:
        """Did the cited authorization's window close before the current request arrived?

        This is the whole of S16 as a fact rather than a label: 11:27 + 600s = 11:37, and the
        request that cites it arrived at 11:52. Note it is computed from the window, not from
        the presence of an `EXPIRY` event — an authorization with a stated TTL and no expiry
        line is just as expired once the clock passes it.

        The window has to come from *stated* evidence, never from a default. Giving S06's
        14:05 approval a house-default TTL and then reading 16:40 against it would report an
        expired authorization on a scenario whose case file never mentions one — and would
        make every scenario with an old approval "expired", which is how a real control turns
        into a rubber stamp that fires on everything.
        """
        if not self.expires_at:
            return False
        return clock.parse_iso(self.expires_at) < self.now

    def authorization_window(self, ttl_seconds: int = 900) -> tuple[str, str]:
        """The window that governs the request about to execute, as ISO start/end.

        A cited grant with a stated end is presented **as it stands, expired or not**. That is
        the point of S16: the request says "execute it now against the same reference", and
        minting a fresh window over a lapsed authorization would silently re-grant the
        authority the attack is trying to reuse. Whether a closed window may release money is
        a policy question, and policy can only answer it if the window reaches it intact.

        With no cited grant — or one whose end nobody recorded — the console signs a window
        here and now, because §16's approval is an act rather than a lookup. Both pre-images
        in a comparison then share it, so `deltas()` reports the fields that really changed
        instead of a window difference the pipeline itself introduced.
        """
        if self.issued_at and self.expires_at:
            return self.issued_at, self.expires_at
        return clock.iso(self.now), clock.iso(self.now + timedelta(seconds=ttl_seconds))


def _derive_nonce(transaction_id: str, issued_at: str) -> str:
    """A deterministic 16-hex nonce. §19.2's replay test forbids anything else here.

    The nonce exists so a captured approval cannot be re-presented for a second payment, so
    it must vary per authorization — but a pipeline that draws it from `secrets` produces a
    different fingerprint on every run and makes byte-identical replay impossible to check.
    Hashing the two things that already identify this authorization gives both properties.
    """
    seed = f"{transaction_id}|{issued_at}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:16]


def read(sample: dict) -> WorldState:
    """Build the `WorldState` a sample implies.

    A sample whose prose says nothing about the past yields an empty `WorldState`: no
    reference, no cited window, no prior requests. That is the correct answer, and it is why
    the seventeen scenarios that need no world state are unaffected by this module existing.
    """
    meta = sample.get("metadata") or {}
    sample_id = str(sample.get("sample_id") or "")
    now = clock.parse_iso(str(meta.get("timestamp") or "")) if meta.get("timestamp") \
        else clock.now()
    events = tuple(_read_event(e) for e in (meta.get("prior_events") or []))

    approval = next((e for e in events if e.kind == "APPROVAL"
                     and e.states_transaction_facts), None)
    expiry = next((e for e in reversed(events) if e.kind == "EXPIRY"), None)

    # The cited authorization's window. The start is the approval event's own timestamp; the
    # end comes from an explicit expiry event, else from a stated TTL, else *nowhere* — see
    # `authorization_expired` for why a default here would be a bug rather than a convenience.
    issued_at = approval.at if approval else ""
    expires_at = ""
    if issued_at:
        if expiry is not None and expiry.at:
            expires_at = expiry.at
        elif approval is not None and approval.ttl_seconds:
            expires_at = clock.iso(clock.parse_iso(issued_at)
                                   + timedelta(seconds=approval.ttl_seconds))

    # S13's "on the same phone session SES-7781" only means what it says if the session it
    # names is *this* session. Matching the id keeps the fact tied to the request in hand
    # rather than to any transcript that happens to contain the word "same".
    session_id = str(meta.get("session_id") or "").strip()
    same_channel = any(
        e.kind == "VERIFICATION_ON_ORIGIN"
        and (not session_id or session_id.casefold() in e.text.casefold())
        for e in events
    )

    authorization_id = (approval.authorization_id if approval else "") or \
                       (expiry.authorization_id if expiry else "")
    return WorldState(
        sample_id=sample_id, now=now, events=events,
        approval=approval if (approval and approval.states_transaction_facts) else None,
        authorization_id=authorization_id,
        issued_at=issued_at, expires_at=expires_at,
        verification_on_origin=same_channel,
        prior_requests=tuple(e for e in events if e.kind == "REQUEST"),
        nonce=_derive_nonce(sample_id, issued_at or (meta.get("timestamp") or "")),
    )
