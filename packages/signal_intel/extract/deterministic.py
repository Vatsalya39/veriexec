"""Deterministic extractor [NOVEL-N15a] — the floor of the whole system. Pure Python,
no network, no model. This is the path that runs on stage and in offline mode.

It also produces `deterministic_intent` — the object Team B independently recomputes
and diffs against the LLM path (extraction_divergence).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from functools import lru_cache

from ..config import now
from ..textnorm import ascii_fold, normalize_text
from .money import parse_amount

# ---------------------------------------------------------------- action lexicons
ACTION_LEXICON: list[tuple[str, list[str]]] = [
    ("CREDENTIAL_RESET", [
        "reset", "unlock", "mfa", "password", "credential", "lost my phone", "temporary unlock",
        "full reset", "locked out"]),
    ("PAYMENT_LIMIT_CHANGE", [
        "raise the limit", "raise my", "increase the limit", "payment approval limit",
        "approval limit", "temporary limit", "raise.*limit", "update the limit", "threshold"]),
    ("BENEFICIARY_CHANGE", [
        "change account", "update bank details", "new account", "revised neft details",
        "account has changed", "revised account", "moved their collections account",
        "updated master", "add .* as an approved vendor", "beneficiary"]),
    ("TRANSFER", [
        "transfer", "remit", "wire", "pay ", "release", "releasing", "process by neft",
        "process the", "settlement", "send it", "move some money", "move it", "deposit",
        "advance", "penalty", "payroll run", "execute", "queue", "levied", "pls",
        "pandrah lakh", "lakh to", "crore to", "rs \\d", "₹"]),
]
# PAYMENT_LIMIT_CHANGE must win over TRANSFER when both patterns are present
# ("raising my payment approval limit from Rs 50,00,000 to Rs 5 crore").

URGENCY_HIGH = re.compile(
    r"\b(immediately|right now|within the hour|asap|urgent|urgency|cannot wait|before market close|"
    r"before the market closes|before eod|today itself|tonight itself|now itself|before six|"
    r"before four|before the board call|move it now|need it moving|do not wait|no need to re-)\b",
    re.IGNORECASE)
URGENCY_MEDIUM = re.compile(
    r"\b(by eod|end of day|before friday|this week|today|tonight|tomorrow morning|cut-off|"
    r"deadline|keep it ready)\b", re.IGNORECASE)

SECRECY_PATTERNS = [
    r"do not tell anyone", r"keep this between us", r"confidential", r"off the books",
    r"no need to loop in", r"keep it off the (shared )?tracker", r"keep it quiet",
    r"don'?t log a ticket", r"highly confidential", r"do not copy anyone",
    r"no need to route it", r"off the tracker",
]

DEADLINE_PATTERNS = [
    (r"before (market close|the market closes)", "before market close"),
    (r"before eod\b", "before EOD"),
    (r"by eod\b", "by EOD"),
    (r"end of day", "end of day"),
    (r"within the hour", "within the hour"),
    (r"before (\d{1,2}\s*(am|pm))", "before time"),
    (r"by (\d{1,2}\s*(am|pm))", "by time"),
    (r"today itself", "today itself"),
    (r"tonight itself", "tonight itself"),
    (r"tomorrow morning", "tomorrow morning"),
    (r"before the two o'?clock cut-?off", "before 14:00 cut-off"),
    (r"before the board call", "before the board call"),
    (r"this week", "this week"),
    (r"before four", "before 16:00"),
    (r"before six", "before 18:00"),
]

# Spoken account endings: "ending nine two eight one", "ending 9281", "account ending 776655"
DIGIT_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
               "six": "6", "seven": "7", "eight": "8", "nine": "9"}
SPOKEN_ENDING = re.compile(
    r"(?:account|a/c|ending)\s+((?:(?:zero|one|two|three|four|five|six|seven|eight|nine)\s+){2,8}"
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine)|\d{4,8})\b", re.IGNORECASE)
BANK_TOKEN = re.compile(r"\b[A-Z]{4}\d{6,}\b|\b\d{9,}\b")

#: A bank code sitting just before the digits, as people actually write it: "HDFC account
#: 0001234567890" is the same string the vendor master stores fused as "HDFC0001234567890".
#: Without this, A published the bare digits, B looked them up, found no such account on
#: record for the payee, and a routine invoice payment scored as money leaving for an
#: account nobody had ever seen.
BANK_CODES = ("HDFC", "ICIC", "SBIN", "AXIS", "ADCB", "EBIL", "KKBK", "UTIB", "PUNB")
SPLIT_BANK_ACCOUNT = re.compile(
    r"\b(" + "|".join(BANK_CODES) + r")\b[^\n\d]{0,24}?(\d{9,})\b", re.IGNORECASE)

PURPOSE_HINTS = re.compile(
    r"against (invoice|inv-[#\w]+|po \d+|consignment[^\n.]{0,30}|the offtake[^\n.]{0,30}|"
    r"the acquisition[^\n.]{0,30}|the escrow[^\n.]{0,30}|the freight[^\n.]{0,30})|"
    r"(customs penalty|payroll run|acquisition deposit|offtake (advance|deposit)|escrow|"
    r"credit note|advance against|quarter-end|freight settlement|die order|tooling line|"
    r"input credit mismatch|rtgs confirmations)", re.IGNORECASE)

#: Where the *speaker* of a message identifies themselves, in decreasing order of strength.
#: Self-identification beats the line prefix because a transcript's first prefixed line is
#: often the anonymous side of the call ("Caller: Priya, this is Ananya Rao" — the requester
#: is Ananya; `Priya:` is the reply two lines down).
SPEAKER_POSITIONS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:it'?s|this is)\s+([A-Za-z][\w' .-]{1,40}?)\b[.,!—-]?"),
    re.compile(r"\b([A-Z][\w']+(?: [A-Z][\w']+)?)\s+here\b"),
    re.compile(r"^[ \t]*([A-Za-z][\w' .()-]{0,40}?)\s*:", re.MULTILINE),
    re.compile(r"[—-]\s*'?([A-Z][\w' .-]{1,40}?)'?\s+(?:to|in|with)\b"),
    re.compile(r"^From:\s*'?([^<\n@]{2,60}?)'?\s*(?:<|$)", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^From:\s*([a-z]+\.[a-z]+)@", re.MULTILINE | re.IGNORECASE),
)


@lru_cache(maxsize=1)
def _persona_index() -> tuple[tuple[str, str, str], ...]:
    """`(match_key, actor_id, "Name (Role)")` for every persona, longest key first.

    Read from `contracts/personas.json` rather than hard-coded, for two reasons. A two-entry
    executive-only table cannot name the requester of S19 — a payroll run instructed by the
    treasury manager, with no `claimed_executive_id` — so A published `requester: null`, B
    matched nobody, and the behavioural dimension abstained on the corpus's most ordinary
    payment. And hard-coded display strings drift: this table said `"Vikram Shah (CEO)"` while
    the registry says `"role": "Chief Executive Officer"`.

    A first name shared by two personas is dropped rather than guessed — naming the wrong
    requester is worse than naming none, because B scores the requester's baseline.
    """
    from ..registry import personas

    p = personas()
    seen: dict[str, list[tuple[str, str]]] = {}
    for group, id_key in (("executives", "executive_id"), ("employees", "employee_id")):
        for rec in p.get(group, ()):
            name = str(rec.get("name", "")).strip()
            if not name:
                continue
            role = str(rec.get("role", "")).strip()
            label = f"{name} ({role})" if role else name
            value = (rec[id_key], label)
            for key in {name, name.split()[0]}:
                seen.setdefault(key.casefold(), []).append(value)
    out = [(key, holders[0][0], holders[0][1])
           for key, holders in seen.items()
           if len({h[0] for h in holders}) == 1]
    return tuple(sorted(out, key=lambda t: -len(t[0])))


def _label_for(actor_id: str) -> str:
    for _key, aid, label in _persona_index():
        if aid == actor_id:
            return label
    return actor_id


@dataclass
class ExtractionResult:
    action: str = "OTHER"
    amount: float | None = None
    currency: str | None = None
    beneficiary: str | None = None
    beneficiary_raw_span: str | None = None
    beneficiary_matched_id: str | None = None
    destination_account: str | None = None
    purpose: str | None = None
    deadline: str | None = None
    urgency: str = "LOW"
    secrecy_flags: list[str] = field(default_factory=list)
    requester: str | None = None
    requester_id: str | None = None
    amount_normalization: dict | None = None
    notes: list[str] = field(default_factory=list)


def _match_action(text: str) -> str:
    scores = {}
    for action, phrases in ACTION_LEXICON:
        score = 0
        for p in phrases:
            if p.startswith("raise.*") or ".*" in p:
                if re.search(p, text, re.IGNORECASE):
                    score += 2
            elif re.search(rf"\b{re.escape(p.strip())}\b", text, re.IGNORECASE):
                score += 1
        if score:
            scores[action] = score
    if not scores:
        return "OTHER"
    # PAYMENT_LIMIT_CHANGE beats TRANSFER on limit-raise phrasing
    if "PAYMENT_LIMIT_CHANGE" in scores and "raise" in text.lower():
        return "PAYMENT_LIMIT_CHANGE"
    return max(scores, key=scores.get)


def _match_beneficiary(text: str, accounts: set[str] | None = None):
    """Fuzzy-match beneficiary names from the frozen master, after confusable normalization.

    When `accounts` (known destination-account numbers from the same text) is given, a
    vendor whose registered account matches one of them is preferred — this binds
    "Sundaram ... ICIC account ending 776655" to Sundaram Freight Services.
    """
    from difflib import SequenceMatcher
    from ..registry import beneficiaries

    if accounts is None:
        accounts = set()

    # Candidate spans: capitalized runs of 2+ words, 8+ chars
    spans = re.findall(r"\b([A-Z][A-Za-z&.]*+(?:\s+[A-Z][A-Za-z&.]*+){1,5})\b", text)
    best = None
    for span in spans:
        if len(span) < 8:
            continue
        folded = ascii_fold(span)
        for b in beneficiaries():
            target = ascii_fold(b["name"])
            ratio = SequenceMatcher(None, folded, target).ratio()
            # Substring containment either way ("Sundaram Freight" vs full name) counts strongly
            if folded in target or target in folded:
                ratio = max(ratio, 0.85)
            if b["account"] in accounts:
                ratio = 1.0  # account match is decisive
            if ratio >= 0.80 and (best is None or ratio > best[0]):
                best = (ratio, span, b)
    if best:
        ratio, span, b = best
        return b["name"], span, b["beneficiary_id"], ratio
    return None, None, None, 0.0


def _match_destination_account(text: str) -> str | None:
    # A fused "HDFC0001234567890" wins outright. Otherwise, a bank code separated from its
    # digits by a word or two is reassembled into the canonical fused form the vendor master
    # stores, so that the account the executive named is the account B looks up.
    fused = re.search(r"\b[A-Z]{4}\d{6,}\b", text)
    split = SPLIT_BANK_ACCOUNT.search(text)
    if fused and (not split or fused.start() <= split.start()):
        return fused.group(0)
    if split:
        return f"{split.group(1).upper()}{split.group(2)}"
    m = BANK_TOKEN.search(text)
    if m:
        return m.group(0)
    m = SPOKEN_ENDING.search(text)
    if m:
        tok = m.group(1).strip()
        words = tok.lower().split()
        if all(w in DIGIT_WORDS for w in words):
            return "".join(DIGIT_WORDS[w] for w in words)
        return re.sub(r"\D", "", tok) or None
    return None


def _match_deadline(text: str) -> str | None:
    # Explicit ISO datetime first
    m = re.search(r"\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?)\b", text)
    if m:
        return m.group(1)
    for pattern, label in DEADLINE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return None


def _match_urgency(text: str, deadline: str | None) -> str:
    if URGENCY_HIGH.search(text):
        return "HIGH"
    if deadline and any(p in deadline.lower() for p in ("eod", "today", "tonight", "hour")):
        return "MEDIUM"
    if URGENCY_MEDIUM.search(text):
        return "MEDIUM"
    return "LOW"


def _match_secrecy(text: str) -> list[str]:
    flags = []
    for pattern in SECRECY_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            flags.append(m.group(0))
    return flags


def _match_purpose(text: str) -> str | None:
    m = PURPOSE_HINTS.search(text)
    if m:
        return m.group(0)[:80]
    return None


def _match_requester(text: str, claimed_executive_id: str | None) -> tuple[str | None, str | None]:
    """`(display label, actor id)` for whoever is asking — not whoever is mentioned.

    The channel's own claim wins when it has one. Otherwise the persona index is searched
    against speaker positions in priority order, so a name that merely appears in the body
    ("Rohit, it's Ananya" — Rohit is the recipient) cannot become the requester.
    """
    if claimed_executive_id:
        return _label_for(claimed_executive_id), claimed_executive_id
    index = _persona_index()
    for pattern in SPEAKER_POSITIONS:
        for m in pattern.finditer(text):
            candidate = " ".join(g for g in m.groups() if g).replace(".", " ").casefold()
            for key, aid, label in index:
                if key in candidate:
                    return label, aid
    # Last resort: a persona named anywhere at all. Weak, but "Ananya Rao wants this" is
    # still a claim about who is asking, and B treats an unresolvable requester as no
    # baseline rather than as trust.
    lowered = text.casefold()
    for key, aid, label in index:
        if re.search(rf"\b{re.escape(key)}\b", lowered):
            return label, aid
    m = re.search(r"\bthis is ([A-Z][a-z]+(?: [A-Z][a-z]+)?)\b", text)
    if m:
        return m.group(1), None
    return None, None


def extract_deterministic(text: str, *, claimed_executive_id: str | None = None,
                          channel: str = "EMAIL") -> ExtractionResult:
    """Pure regex/rule extraction of every critical field. Never raises on sane input."""
    result = ExtractionResult()
    if not text or not text.strip():
        return result
    t = normalize_text(text)

    result.action = _match_action(t)
    amt = parse_amount(t)
    if amt:
        result.amount = amt.value
        result.currency = amt.currency
        result.amount_normalization = {
            "raw_span": amt.raw_span, "parsed_value": amt.value,
            "multiplier": amt.multiplier, "rule": amt.rule_id}

    # Re-match beneficiary with account binding: "ICIC account ending 776655" pins the vendor.
    known_accounts = set()
    for m in BANK_TOKEN.finditer(t):
        known_accounts.add(m.group(0))
    for m in SPOKEN_ENDING.finditer(t):
        tok = re.sub(r"\D", "", m.group(1))
        if len(tok) >= 4:
            known_accounts.add(tok)

    name, span, matched_id, ratio = _match_beneficiary(t, accounts=known_accounts)
    result.beneficiary = name
    result.beneficiary_raw_span = span
    result.beneficiary_matched_id = matched_id
    if span and not matched_id:
        result.notes.append("BENEFICIARY_UNKNOWN")
        result.beneficiary = span
    else:
        result.destination_account = result.destination_account or _match_destination_account(t)
    result.deadline = _match_deadline(t)
    result.urgency = _match_urgency(t, result.deadline)
    result.secrecy_flags = _match_secrecy(t)
    result.purpose = _match_purpose(t)
    result.requester, result.requester_id = _match_requester(t, claimed_executive_id)
    return result


def build_deterministic_intent_object(res: ExtractionResult, transaction_id: str,
                                       timestamp: str) -> dict:
    """The `deterministic_intent` extension object for B's divergence check."""
    return {
        "action": res.action,
        "amount": res.amount,
        "currency": res.currency,
        "beneficiary": res.beneficiary,
        "beneficiary_matched_id": res.beneficiary_matched_id,
        "destination_account": res.destination_account,
        "urgency": res.urgency,
        "deadline": res.deadline,
        "secrecy_flags": res.secrecy_flags,
        "transaction_id": transaction_id,
        "timestamp": timestamp,
    }
