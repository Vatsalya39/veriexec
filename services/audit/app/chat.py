"""The audit explainability chatbot. `[NOVEL-N8]` §6

Retrieval, then answer. Never the other way round, and never from the model's memory.

    plan    = classify(question)      # deterministic keyword + regex router, NOT a model call
    records = query_chain(plan)       # SQL over var/audit.db
    facts   = summarize(records)      # counts, sums, lists — computed in Python
    prose   = narrate(facts)          # optional; the template fallback always exists

**Every arithmetic answer is computed in Python.** "How many transactions were blocked today?" is a
`SELECT COUNT(*)`, and a model's only job is to put a sentence around a number it was handed. A
chatbot that counts with a language model will be wrong on stage, and one wrong count discounts
everything else in the demo.

Three guards, all implemented as code paths rather than as guidelines:

* **Citations or nothing.** An answer with an empty `record_seqs` is not returned as an answer; it
  is returned as a refusal. `test_chatbot_cites_records` asserts it.
* **Refuse to decide.** Anything asking this to approve, release, override or re-score gets
  `CANNOT_DECIDE` verbatim. It is a module constant because it gets quoted on stage.
* **Refuse to guess.** An unclassified question is answered with the eight it *can* answer, never
  with free-form prose. Refusing well is a stronger signal than answering broadly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .config import llm_enabled
from .privacy import SessionTokenMap, for_model

CANNOT_DECIDE = "I can explain decisions. I cannot make them."
CANNOT_CLASSIFY = "I can only answer from the audit chain. Try one of these."

# Verbs that mean the asker wants an action, not an explanation. Matched as whole words so
# "overridden" in "did anyone override a block" — a legitimate question — is handled by the router
# below rather than caught here. Ordering matters: this check runs before classification, because a
# question that both asks for an action and mentions a transaction id must refuse, not answer.
_DECIDE_VERBS = re.compile(
    r"\b(approve|approves?|authorise|authorize|release|releases?|unblock|override|re-?score|"
    r"rescore|re-?assess|reassess|allow|permit|push (?:it )?through|let it through|"
    r"sign off|greenlight|green-?light)\b", re.I)

# ...but only when they are aimed at *this* system doing it. "Did anyone override a block?" is a
# retrieval question about the past; "should I approve this?" is a request for a decision.
_RETROSPECTIVE = re.compile(
    r"\b(did|was|were|who|when|has|have|had|why|show|list|which|how many|what happened)\b", re.I)

TXN_RE = re.compile(r"\b(TXN-[A-Z0-9]+-\d+|TXN-\d+|ASM-S\d+|S\d{2})\b", re.I)

QUESTION_MENU: tuple[str, ...] = (
    "Why was TXN-…-0007 blocked?",
    "Show me everything that happened to TXN-…-0007.",
    "How many transactions were blocked in the last hour and why?",
    "Which payees received first-time payments today?",
    "Did anyone override a block?",
    "What changed in the policy today?",
    "Has this log been altered?",
    "What would have approved TXN-…-0007?",
)


@dataclass(frozen=True)
class Plan:
    """What the router decided. `intent` selects the retrieval and the summary, nothing else."""
    intent: str
    transaction_id: str | None = None
    event_types: tuple[str, ...] = ()
    since: str | None = None
    window: str | None = None       # human label for `since`, so the answer can name its own window
    limit: int = 200


@dataclass
class ChatAnswer:
    prose: str
    facts: dict[str, Any] = field(default_factory=dict)
    record_seqs: list[int] = field(default_factory=list)
    refused: bool = False
    refusal_kind: str | None = None
    intent: str | None = None
    computed_by: str = "python"     # never "model" — see summarize()
    narrated_by: str = "template"   # "template" | "model"


# --------------------------------------------------------------------------- the router
#
# Eight patterns, tried in order. Deterministic on purpose: the same question produces the same plan
# on every run, which is what makes the demo rehearsable and the failure mode legible. A model here
# would buy fuzzier matching at the cost of a router that can classify differently on stage than it
# did in rehearsal, and there is no version of that trade worth making.

# Checked before the decide-refusal: "what would have approved this?" contains `approve` but asks
# about a hypothetical past. It is the §6.2 counterfactual question, not a request for an action.
_COUNTERFACTUAL = re.compile(
    r"\b(would\s+have\s+(approved|passed|cleared|gone through)|what\s+would\s+it\s+have\s+taken|"
    r"counterfactual|what\s+would\s+have\s+(made|let|allowed)|how\s+could\s+it\s+have\s+"
    r"(been\s+)?approved)\b", re.I)

# A decide verb aimed at *this system, now*. "Can you", "please", "should I", or a bare imperative.
# Without this the refusal would swallow "did anyone override a block?", which is retrieval.
_DECIDE_ADDRESSED = re.compile(
    r"(\b(can|could|will|would|should|may)\s+(you|i|we|it)\b|\bplease\b|\bgo ahead\b|"
    r"\blet'?s\b|\blet us\b|^\s*(?:just\s+|please\s+)*(?:approve|release|unblock|override|allow|"
    r"permit|greenlight|green-light|re-?score|re-?assess|authorise|authorize|sign off)\b)", re.I)

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("chain_integrity", re.compile(
        r"\b(altered|tamper(ed|ing)?|modified|intact|integrity|trust(worthy)?|"
        r"has\s+(the|this)\s+log|been\s+changed|verify\s+the\s+(log|chain))\b", re.I)),
    ("policy_changes", re.compile(
        r"\b(polic(y|ies)|threshold|weight|version)\b.*\b(chang(e|ed|es)|updat(e|ed)|differ|"
        r"replay(ed)?|new|today)\b|\b(chang(e|ed|es))\b.*\bpolic(y|ies)\b", re.I)),
    ("overrides", re.compile(
        r"\b(override|overrode|overridden|officer\s+override|manual(ly)?\s+(approv|releas)|"
        r"who\s+released|bypass(ed)?)\b", re.I)),
    ("first_time_payees", re.compile(
        r"\b(first[-\s]?time|new|never\s+paid|unseen|unknown)\b.*\b(payee|beneficiar|vendor|"
        r"account|payment|paid)\w*\b|\bpayee\w*\b.*\bfirst[-\s]?time\b", re.I)),
    ("blocked_count", re.compile(
        r"\bhow\s+many\b|\b(count|number\s+of|total)\b.*\b(block|challeng|approv|decision|txn|"
        r"transaction)\w*\b|\b(block|challeng|approv)\w*\b.*\b(today|last\s+hour|so\s+far|"
        r"this\s+(hour|session))\b", re.I)),
    ("transaction_timeline", re.compile(
        r"\b(everything|timeline|full\s+(story|history|record)|all\s+(the\s+)?(events|records|"
        r"steps)|what\s+happened|walk\s+me\s+through|sequence)\b", re.I)),
    ("why_blocked", re.compile(
        r"\bwhy\b|\breason\b|\bwhat\s+(caused|drove|triggered)\b|\bexplain\b|"
        r"\bon\s+what\s+(basis|grounds)\b", re.I)),
)

# Intents whose answer is about one transaction. Asking one of these without naming a transaction is
# an under-specified question, and the honest response is to say which one it needs.
_NEEDS_TXN: frozenset[str] = frozenset({"why_blocked", "transaction_timeline", "counterfactual"})

_LAST_HOUR = re.compile(r"\blast\s+(hour|60\s+minutes)\b|\bpast\s+hour\b", re.I)
_TODAY = re.compile(r"\btoday\b|\bso\s+far\b|\bthis\s+session\b|\bthis\s+morning\b", re.I)


def _transaction_id(q: str) -> str | None:
    m = TXN_RE.search(q)
    return m.group(1).upper() if m else None


def _since(q: str) -> tuple[str | None, str | None]:
    """Resolve a relative window to an absolute ISO timestamp, in Python. §6.

    Returned as a string because `timestamp` is stored as ISO-8601 text and compared lexicographically
    — which is only correct because every record carries the same `+05:30` offset. `config.IST` is the
    single source of that offset for exactly this reason. The label comes back too: an answer that
    says "in the last hour" must be reading the same window the query used.
    """
    from datetime import datetime, timedelta

    from .config import IST
    now = datetime.now(IST)
    if _LAST_HOUR.search(q):
        return (now - timedelta(hours=1)).isoformat(timespec="milliseconds"), "in the last hour"
    if _TODAY.search(q):
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight.isoformat(timespec="milliseconds"), "today"
    return None, None


def classify(question: str) -> Plan:
    """Question -> retrieval plan. Pure, deterministic, and not a model call. §6.1"""
    q = (question or "").strip()
    if not q:
        return Plan("unclassified")

    txn = _transaction_id(q)

    # Order is load-bearing. The counterfactual question contains `approve`; the decide-refusal must
    # not swallow it. And the decide-refusal runs before the router, so a question that both names a
    # transaction and asks for an action refuses instead of helpfully answering half of it.
    if _COUNTERFACTUAL.search(q):
        return Plan("counterfactual", txn)
    if _DECIDE_VERBS.search(q) and (_DECIDE_ADDRESSED.search(q) or not _RETROSPECTIVE.search(q)):
        return Plan("refuse_decide", txn)

    for intent, pattern in _PATTERNS:
        if not pattern.search(q):
            continue
        if intent in _NEEDS_TXN and not txn:
            return Plan("needs_transaction")
        since, window = _since(q)
        return Plan(intent, txn, since=since, window=window)

    # A bare transaction id is a request for its story. Common enough on stage to be worth handling.
    if txn:
        return Plan("transaction_timeline", txn)
    return Plan("unclassified")


# ------------------------------------------------------------------------- retrieval
#
# One SQL shape per intent. Nothing here interprets: it fetches the records the plan named and hands
# them to `summarize`. Keeping retrieval this dumb is what lets the citation list be exactly "the
# records this answer was computed from" rather than "records that were probably relevant".

_DECISION_EVENTS = ("DECISION_RENDERED",)
_OVERRIDE_EVENTS = ("OFFICER_OVERRIDE",)
_POLICY_EVENTS = ("POLICY_REPLAYED",)
# The payee lives on the captured intent, not on the assessment: B scores the beneficiary dimension
# and publishes the reason, but the `beneficiary` object itself is A's, carried on INTENT_CAPTURED.
# Both are queried because either may carry it depending on how much of the bundle the writer copied.
_PAYEE_EVENTS = ("INTENT_CAPTURED", "RISK_ASSESSED")


def query_chain(store: Any, plan: Plan) -> list[dict[str, Any]]:
    """Fetch the records `plan` names. `store` is an `AuditStore`; passed in, not imported, so the
    tests can hand this a store over a temporary database."""
    if plan.intent in ("why_blocked", "transaction_timeline", "counterfactual"):
        return store.records(transaction_id=plan.transaction_id, limit=plan.limit)
    if plan.intent == "chain_integrity":
        # The integrity answer is about the whole log, so its citations are the head and the first
        # break — computed in `summarize` from the verify walk, not from a row filter.
        return store.records(limit=plan.limit, order="desc")[:1]
    if plan.intent == "blocked_count":
        return _by_events(store, _DECISION_EVENTS, plan)
    if plan.intent == "overrides":
        return _by_events(store, _OVERRIDE_EVENTS, plan)
    if plan.intent == "policy_changes":
        return _by_events(store, _POLICY_EVENTS + _DECISION_EVENTS, plan)
    if plan.intent == "first_time_payees":
        return _by_events(store, _PAYEE_EVENTS, plan)
    return []


def _by_events(store: Any, event_types: tuple[str, ...], plan: Plan) -> list[dict[str, Any]]:
    """`store.records` filters one event type per call; several is a union, re-sorted by `seq`.

    Deduplicated on `seq` because the union can overlap once an intent asks for two families.
    """
    seen: dict[int, dict[str, Any]] = {}
    for event_type in event_types:
        for record in store.records(event_type=event_type, since=plan.since, limit=plan.limit):
            seen[record["seq"]] = record
    return [seen[k] for k in sorted(seen)]


# --------------------------------------------------------------------------- payload access
#
# Records arrive from A and B, and their payload nesting is theirs to change. A `_dig` that searches
# by key name survives a reshuffle; a hard-coded `payload["assessment"]["risk_score"]` does not, and
# would fail as a `KeyError` mid-demo rather than as a missing sentence.


def _dig(obj: Any, *names: str) -> Any:
    """First value found at any depth under any of `names`. Breadth-first, so a shallow key wins."""
    frontier = [obj]
    while frontier:
        nxt: list[Any] = []
        for node in frontier:
            if isinstance(node, dict):
                for name in names:
                    if name in node and node[name] is not None:
                        return node[name]
                nxt.extend(node.values())
            elif isinstance(node, (list, tuple)):
                nxt.extend(node)
        frontier = nxt
    return None


def _inr(minor: Any) -> str | None:
    """Integer minor units -> `₹1,20,570.00`. Indian grouping: last three, then pairs. §12

    Computed here so the model is handed a finished string. `privacy.scrub` tokenizes bare integers
    over 100000, which would otherwise turn an amount into `[NUM_…]` in the prompt and leave the
    model with nothing to say about size.
    """
    if not isinstance(minor, int) or isinstance(minor, bool):
        return None
    sign = "-" if minor < 0 else ""
    whole, paise = divmod(abs(minor), 100)
    digits = str(whole)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        digits = ",".join(parts + [tail])
    return f"{sign}₹{digits}.{paise:02d}"


def _pick(records: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    """The last record of a type. Last, not first: a re-assessment supersedes the one before it."""
    hits = [r for r in records if r["event_type"] == event_type]
    return hits[-1] if hits else None


def _reason_lines(payload: Any, limit: int = 4) -> list[str]:
    """Human-readable reasons, in the order the producer published them. §Invariant 6.

    `top_reasons` is what B publishes and is checked first; the others are the shapes a reason list
    arrives in from elsewhere — bare strings, `{code, message}`, and the `contributions` rows —
    because C does not own any of them. Never invents a reason: if there is no readable text the line
    is dropped, and a missing reason shows up as a shorter list rather than as a plausible sentence C
    made up.
    """
    out: list[str] = []
    for source in ("top_reasons", "reasons", "reason_lines", "contributions"):
        rows = _dig(payload, source)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, str) and row.strip():
                out.append(row.strip())
            elif isinstance(row, dict):
                text = row.get("reason") or row.get("message") or row.get("narrative")
                if isinstance(text, str) and text.strip():
                    out.append(text.strip())
        if out:
            break
    seen, unique = set(), []
    for line in out:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return unique[:limit]


def _num(value: Any) -> float | None:
    """Read a quantity that may be an int, a float, or a fixed-decimal string.

    `db._decimalize` stores `0.15` as `"0.15"` so the payload hashes under the frozen canonical rule
    (see C-10 in docs/CHANGES.md). Every numeric read in this module goes through here so the
    chatbot's arithmetic does not care which form it got.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _weighted_top(payload: Any, limit: int = 3) -> list[dict[str, Any]]:
    """`contributions` sorted by weighted contribution, descending. Arithmetic stays in Python.

    B's rows call the weighted figure `points`; `weighted` and `weighted_points` are accepted too so
    a rename upstream degrades to a missing section rather than to a `KeyError` on stage.
    """
    rows = _dig(payload, "contributions")
    if not isinstance(rows, list):
        return []
    scored = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        weighted = next((n for n in (_num(row.get(k)) for k in
                                     ("points", "weighted", "weighted_points")) if n is not None),
                        None)
        if weighted is None:
            continue
        scored.append({"dimension": row.get("label") or row.get("dimension") or row.get("name"),
                       "weighted": weighted,
                       # `scored_as_clean: false` is B's way of saying "abstained, and not treated as
                       # favourable". Invariant 3 lives in that flag, so it is surfaced verbatim.
                       "abstained": bool(row.get("abstained")) or row.get("scored_as_clean") is False,
                       "reason": row.get("reason") or row.get("message")})
    scored.sort(key=lambda r: (-r["weighted"], str(r["dimension"])))
    return scored[:limit]


# --------------------------------------------------------------------------- summarizers
#
# `computed_by` is hard-coded to `"python"` on `ChatAnswer` and every number below is produced here.
# If a number ever needs to come from somewhere else, that field becomes a lie and the guarantee in
# the module docstring goes with it.


def _sum_why_blocked(plan: Plan, records: list[dict[str, Any]],
                     store: Any) -> tuple[dict[str, Any], list[int]]:
    decision = _pick(records, "DECISION_RENDERED")
    assessment = _pick(records, "RISK_ASSESSED")
    if decision is None and assessment is None:
        return {}, []
    source = assessment or decision
    body = (source or {}).get("payload", {})
    dbody = (decision or {}).get("payload", {})

    facts: dict[str, Any] = {
        "transaction_id": plan.transaction_id,
        "decision": _dig(dbody, "decision") or _dig(body, "decision"),
        "risk_score": _num(_dig(body, "risk_score", "score")),
        "band": _dig(body, "band_outcome", "band"),
        "coverage": _num(_dig(body, "coverage")),
        "decided_at_step": _dig(dbody, "decided_at_step") or _dig(body, "decided_at_step"),
        "override_applied": _dig(dbody, "override_applied") or _dig(body, "override_applied"),
        "control_label": _dig(dbody, "control_label") or _dig(body, "control_label"),
        "reasons": _reason_lines(body) or _reason_lines(dbody),
        "top_contributions": _weighted_top(body),
        # `amount_display` is already a rendered `₹` string upstream; `_inr` is the fallback for a
        # payload that only carries minor units. Either way the model is handed a finished string.
        "amount": (_dig(records, "amount_display")
                   or _inr(_dig(records, "amount_minor_units", "amount_minor"))),
        "event_count": len(records),
    }
    forced = _dig(dbody, "forced_by") or _dig(body, "forced_by")
    if isinstance(forced, dict):
        facts["forced_by"] = forced.get("code")
        facts["forced_reason"] = forced.get("reason") or forced.get("message")
    elif isinstance(forced, str):
        facts["forced_by"] = forced
    seqs = sorted({r["seq"] for r in (assessment, decision) if r})
    return facts, seqs


def _sum_timeline(plan: Plan, records: list[dict[str, Any]],
                  store: Any) -> tuple[dict[str, Any], list[int]]:
    if not records:
        return {}, []
    steps = [{"seq": r["seq"], "at": r["timestamp"], "event": r["event_type"], "actor": r["actor"]}
             for r in records]
    decision = _pick(records, "DECISION_RENDERED")
    facts = {
        "transaction_id": plan.transaction_id,
        "event_count": len(records),
        "first_at": records[0]["timestamp"],
        "last_at": records[-1]["timestamp"],
        "elapsed_ms": _elapsed_ms(records[0]["timestamp"], records[-1]["timestamp"]),
        "steps": steps,
        "actors": sorted({r["actor"] for r in records}),
        "decision": _dig((decision or {}).get("payload", {}), "decision"),
    }
    return facts, [r["seq"] for r in records]


def _elapsed_ms(first: str, last: str) -> int | None:
    from datetime import datetime
    try:
        return int((datetime.fromisoformat(last) - datetime.fromisoformat(first)
                    ).total_seconds() * 1000)
    except (TypeError, ValueError):
        return None


def _sum_blocked_count(plan: Plan, records: list[dict[str, Any]],
                       store: Any) -> tuple[dict[str, Any], list[int]]:
    """`SELECT COUNT(*) ... GROUP BY decision`, done in Python over the fetched rows. §6

    The grouping is over rows this function can cite. Counting in SQL and citing nothing would be
    faster and would fail `test_chatbot_cites_records`, which is the correct outcome: a number whose
    provenance cannot be shown is not evidence.
    """
    tally: dict[str, int] = {}
    why: dict[str, dict[str, int]] = {}
    for record in records:
        body = record.get("payload", {})
        decision = _dig(body, "decision") or "UNKNOWN"
        tally[decision] = tally.get(decision, 0) + 1
        key = (_dig(body, "override_applied") or _dig(body, "forced_by")
               or _dig(body, "control_label") or _dig(body, "band_outcome") or "band")
        if isinstance(key, dict):
            key = key.get("code") or "band"
        # A duress escalation is bucketed by what it *is* to an operator — an out-of-band check —
        # rather than by the word `DURESS`. Invariant 4 makes duress silent to the requester, and
        # `/v1/audit/ask` ships without authentication (a documented scope cut), so a general-purpose
        # count is the wrong place for that word. The category is the information; the label is not.
        if str(key).upper() in _SILENT_CODES:
            key = "OUT_OF_BAND_VERIFICATION"
        # `band_outcome` equals the decision when nothing overrode the score, and "BLOCK broke down
        # as BLOCK: 1" tells a reader nothing. Say what actually decided it.
        if str(key).upper() == str(decision).upper():
            key = "band"
        bucket = why.setdefault(decision, {})
        bucket[str(key)] = bucket.get(str(key), 0) + 1

    facts = {
        "window": plan.window or "in the whole log",
        "since": plan.since,
        "total": len(records),
        "by_decision": dict(sorted(tally.items())),
        "reasons_by_decision": {k: dict(sorted(v.items())) for k, v in sorted(why.items())},
        "blocked": tally.get("BLOCK", 0),
        "challenged": tally.get("CHALLENGE", 0),
        "approved": tally.get("APPROVE", 0),
    }
    return facts, [r["seq"] for r in records]


# How "this payee has not been paid before" is actually expressed upstream. There is no boolean: A's
# bundle and B's intent both say it structurally, with `status: "NEW_TO_ORG"` and an
# `org_payment_count` of zero. The boolean spellings are kept as a fallback in case one appears later,
# but the two structural checks are what the fixtures exercise.
_FIRST_TIME_KEYS = ("first_time_payee", "is_first_time_payee", "first_time", "never_paid_before")
_FIRST_TIME_STATUS = frozenset({"NEW_TO_ORG", "NEW", "FIRST_TIME", "UNKNOWN_PAYEE"})


def _is_first_time(body: Any) -> bool:
    if any(_dig(body, key) is True for key in _FIRST_TIME_KEYS):
        return True
    status = _dig(body, "status")
    if isinstance(status, str) and status.upper() in _FIRST_TIME_STATUS:
        return True
    count = _dig(body, "org_payment_count", "prior_payment_count", "payment_count")
    return isinstance(count, int) and not isinstance(count, bool) and count == 0


def _sum_first_time_payees(plan: Plan, records: list[dict[str, Any]],
                           store: Any) -> tuple[dict[str, Any], list[int]]:
    payees: list[dict[str, Any]] = []
    seqs: list[int] = []
    seen: set[tuple[Any, Any]] = set()
    for record in records:
        body = record.get("payload", {})
        beneficiary = _dig(body, "beneficiary") or body
        if not _is_first_time(beneficiary):
            continue
        # Business name if the payee has one, masked tail otherwise. Never the full number: §12
        # applies to the chatbot's output as much as to the console's DOM.
        name = (_dig(beneficiary, "name", "vendor_name", "payee_name", "beneficiary_name")
                or _mask(_dig(beneficiary, "account_last4", "destination_account", "account"))
                or "an unnamed payee")
        key = (record.get("transaction_id"), name)
        if key in seen:
            # The intent and the assessment can both carry the payee. One transaction, one payee row.
            continue
        seen.add(key)
        seqs.append(record["seq"])
        payees.append({
            "seq": record["seq"],
            "transaction_id": record.get("transaction_id"),
            "payee": name,
            "account": _mask(_dig(beneficiary, "account_last4", "destination_account", "account")),
            "amount": (_dig(body, "amount_display")
                       or _inr(_dig(body, "amount_minor_units", "amount_minor"))),
            "status": _dig(beneficiary, "status"),
            "prior_payments": _dig(beneficiary, "org_payment_count"),
            "at": record["timestamp"],
        })
    facts = {"window": plan.window or "in the whole log", "since": plan.since,
             "count": len(payees), "payees": payees,
             "records_scanned": len(records)}
    return facts, seqs


def _mask(value: Any) -> str | None:
    """Last four, everything else an ellipsis. §12 — including tooltips, copy payloads and the DOM.

    Idempotent on values that arrive pre-masked: B publishes `account_last4` as `••••9281`, and
    masking it again must not produce `…••••9281` or strip the digits that make it identifiable.
    """
    if not isinstance(value, str) or not value:
        return None
    tail = "".join(ch for ch in value if ch.isalnum())[-4:]
    return f"••••{tail}" if tail else None


def _sum_overrides(plan: Plan, records: list[dict[str, Any]],
                   store: Any) -> tuple[dict[str, Any], list[int]]:
    """Officer overrides. The answer to "did anyone override a block?" is a list or the word no.

    `OFFICER_OVERRIDE` is a mandatory log event, so an empty list here is a real finding rather than
    a gap — and it still cites the records it scanned, because "nothing happened" needs provenance
    too. The store query already restricted to the event type; every fetched row is an override.
    """
    overrides = [{
        "seq": r["seq"],
        "transaction_id": r.get("transaction_id"),
        "actor": r["actor"],
        "at": r["timestamp"],
        "justification": _dig(r.get("payload", {}), "justification", "reason", "note"),
        "from_decision": _dig(r.get("payload", {}), "from_decision", "original_decision"),
        "to_decision": _dig(r.get("payload", {}), "to_decision", "new_decision", "decision"),
    } for r in records]
    facts = {"count": len(overrides), "overrides": overrides,
             "window": plan.window or "in the whole log", "since": plan.since,
             "actors": sorted({o["actor"] for o in overrides})}
    return facts, [r["seq"] for r in records]


def _sum_policy_changes(plan: Plan, records: list[dict[str, Any]],
                        store: Any) -> tuple[dict[str, Any], list[int]]:
    """Which policy versions appear, and where the log crosses from one to the next.

    Every record carries `policy_version` and `policy_hash`, so "what changed today" is answerable
    from the chain itself rather than from a changelog somebody might have forgotten to write. A
    version whose hash differs from another record's under the *same* version string is a louder
    finding than a version bump, and it is reported separately.
    """
    versions: dict[str, set[str]] = {}
    transitions: list[dict[str, Any]] = []
    previous: tuple[str, str] | None = None
    seqs: list[int] = []

    for record in records:
        version, digest = record["policy_version"], record["policy_hash"]
        versions.setdefault(version, set()).add(digest)
        current = (version, digest)
        if previous is not None and current != previous:
            transitions.append({"seq": record["seq"], "at": record["timestamp"],
                                "from_version": previous[0], "to_version": version,
                                "hash_changed": previous[1] != digest})
            seqs.append(record["seq"])
        previous = current

    replays = [{"seq": r["seq"], "at": r["timestamp"], "actor": r["actor"],
                "transaction_id": r.get("transaction_id"),
                "from_version": _dig(r.get("payload", {}), "from_version", "original_version"),
                "to_version": _dig(r.get("payload", {}), "to_version", "replayed_version"),
                "decision_changed": _dig(r.get("payload", {}), "decision_changed", "changed")}
               for r in records if r["event_type"] == "POLICY_REPLAYED"]
    seqs.extend(r["seq"] for r in records if r["event_type"] == "POLICY_REPLAYED")

    # Always cite the endpoints of the scanned range, not just the rows that changed. "One version
    # across 6 records" is a claim about a *range*, and a citation list holding only the replay row
    # would invite a reader to check one record and think they had checked the claim.
    if records:
        seqs.extend((records[0]["seq"], records[-1]["seq"]))
    seqs = sorted(set(seqs))

    facts = {
        "window": plan.window or "in the whole log", "since": plan.since,
        "versions": {v: sorted(h) for v, h in sorted(versions.items())},
        "version_count": len(versions),
        "same_version_different_hash": sorted(v for v, h in versions.items() if len(h) > 1),
        "transitions": transitions,
        "replays": replays,
        "records_scanned": len(records),
    }
    return facts, sorted(set(seqs))


def _sum_chain_integrity(plan: Plan, records: list[dict[str, Any]],
                         store: Any) -> tuple[dict[str, Any], list[int]]:
    """"Has this log been altered?" — answered by re-running the verification walk, now.

    Not from a cached result and not from the `ok` flag some earlier response returned. The whole
    point of the question is that the answer must be recomputed over the current contents, and the
    walk is cheap enough at demo scale to make caching a false economy.
    """
    verdict = store.verify()
    head = store.head()
    facts = {
        "ok": verdict["ok"],
        "record_count": verdict["record_count"],
        "head_hash": head["record_hash"],
        "head_seq": head["seq"],
        "verified_at": head["verified_at"],
        "first_broken_seq": verdict["first_broken_seq"],
        "untrusted_from": verdict["untrusted_from"],
        "detail": verdict["detail"],
        # Kept distinct from the cryptographic finding on purpose: `broken_field` is only ever the
        # demo route's own breadcrumb, never something recovered from the digest. See `chain.py`.
        "broken_field": verdict["broken_field"],
        "broken_field_source": verdict["broken_field_source"],
    }
    seqs = [verdict["first_broken_seq"]] if verdict["first_broken_seq"] else \
           [r["seq"] for r in records]
    return facts, [s for s in seqs if s]


def _sum_counterfactual(plan: Plan, records: list[dict[str, Any]],
                        store: Any) -> tuple[dict[str, Any], list[int]]:
    """Quote Team B's stored counterfactual. Never recompute it. §6.2

    B publishes `counterfactual.narrative` on the assessment. If the chatbot derived its own from
    `contributions`, two parts of the same system could describe the same transaction differently —
    and on stage the discrepancy is the thing the audience remembers. So this reads the field and
    passes it through, and when the field is a `withheld` kind (duress) it says so rather than
    reaching into `contributions` to reconstruct what B deliberately did not publish.
    """
    assessment = _pick(records, "RISK_ASSESSED")
    if assessment is None:
        return {}, []
    body = assessment.get("payload", {})
    cf = _dig(body, "counterfactual")
    if not isinstance(cf, dict):
        cf = {"kind": "unavailable", "narrative": None}
    facts = {
        "transaction_id": plan.transaction_id,
        "kind": cf.get("kind"),
        "narrative": cf.get("narrative"),
        "derivable_from": cf.get("derivable_from"),
        "decision": _dig(body, "decision") or _dig(
            (_pick(records, "DECISION_RENDERED") or {}).get("payload", {}), "decision"),
        "risk_score": _num(_dig(body, "risk_score", "score")),
        "quoted_from_seq": assessment["seq"],
        "recomputed": False,
    }
    return facts, [assessment["seq"]]


_SUMMARIZERS = {
    "why_blocked": _sum_why_blocked,
    "transaction_timeline": _sum_timeline,
    "blocked_count": _sum_blocked_count,
    "first_time_payees": _sum_first_time_payees,
    "overrides": _sum_overrides,
    "policy_changes": _sum_policy_changes,
    "chain_integrity": _sum_chain_integrity,
    "counterfactual": _sum_counterfactual,
}


def summarize(plan: Plan, records: list[dict[str, Any]],
              store: Any) -> tuple[dict[str, Any], list[int]]:
    """Records -> facts and citations. **The only place arithmetic happens.** §6

    Returns `(facts, record_seqs)`. `record_seqs` is not decoration: `answer()` refuses to return a
    response whose citation list is empty, so a summarizer that computes a number without being able
    to name the rows it came from produces a refusal instead of an answer.
    """
    fn = _SUMMARIZERS.get(plan.intent)
    if fn is None:
        return {}, []
    return fn(plan, records, store)


# --------------------------------------------------------------------------- templates
#
# The template is the product, not the degraded mode. `INTENTLOCK_MODE=offline` is the default and
# the demo runs on conference wifi, so the sentence that ships is the one written here. A model, when
# enabled, gets to rephrase these — it never gets to supply a fact one of them does not already have.

# Reason codes that must not be echoed as prose. Invariant 4: duress is silent — the requester sees
# a normal processing state, and `/v1/audit/ask` has no authentication to distinguish who is asking.
# The *decision* is still reported in full; only the word is withheld, and `SILENT_ESCALATION` in the
# decision field already tells an operator what happened.
#
# Duress is step 3 of B's §16.2 decision function, not a hard override, so no `HO-` code belongs in
# this set. HO-4 in particular is nonce replay — "this authorization is spent" is precisely the kind
# of specific, explainable reason Invariant 6 exists to make sure a reader gets.
_SILENT_CODES = frozenset({"DURESS", "DURESS_SUSPECTED", "COERCION"})

_STEP_LABEL = {
    "breaker": "the velocity breaker, before scoring",
    "hard_override": "a hard override, before scoring",
    # Step 3 of B's decision function. Named for what it does, not for what triggered it: this string
    # is rendered into prose that any caller of `/v1/audit/ask` can read, and the step name is the one
    # place the word would otherwise survive every other guard in this module.
    "duress": "the out-of-band verification path, before scoring",
    "abstention_floor": "an evidence floor, after scoring",
    "approve_precondition": "an approve precondition, after scoring",
    "band": "the numeric band",
}


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"  · {line}" for line in lines)


def _sentence(text: Any) -> str:
    """One trailing period, not two. Upstream reason strings sometimes end with one and sometimes not."""
    body = str(text).rstrip()
    return body if body.endswith((".", "?", "!", ":")) else body + "."


# Decisions are contract values and stay upper-case in lists and counts, where a reviewer is scanning
# for a code. In a sentence they read as English, because "TXN-…-0008 was BLOCK" is not a sentence.
_DECISION_VERB = {
    "APPROVE": "approved", "CHALLENGE": "challenged", "BLOCK": "blocked",
    "SILENT_ESCALATION": "sent for out-of-band verification",
}


def _t_why_blocked(f: dict[str, Any]) -> str:
    txn = f.get("transaction_id")
    decision = f.get("decision")
    verb = _DECISION_VERB.get(str(decision), f"decided {decision}") if decision else "not decided"
    score, band = f.get("risk_score"), f.get("band")
    out = [f"{txn} was {verb}."]
    if score is not None:
        out[0] = f"{txn} was {verb} at a risk score of {score:g} out of 100."
        if band and band != decision:
            out.append(f"The score alone put it in the {band} band; the outcome is {decision} "
                       f"because something else took precedence.")
    override = f.get("override_applied")
    label = f.get("control_label")
    if isinstance(override, str) and override.upper().startswith("HO-"):
        out.append(f"Hard override {override} applied, which replaces the score rather than "
                   f"adjusting it.")
    elif isinstance(override, str) and override.upper() not in _SILENT_CODES and override != label:
        # Not an HO- code, so not one of the eight frozen hard overrides. Naming it as one would
        # misrepresent the policy; naming it as a control is accurate for a breaker or a floor.
        out.append(f"Control applied: {override}. It sets the outcome regardless of the score.")
    if label:
        out.append(f"Control in effect: {label}.")
    forced = f.get("forced_by")
    if isinstance(forced, str) and forced.upper() in _SILENT_CODES:
        # Invariant 4. The record's own decision code already says out-of-band verification; the
        # reason category adds nothing an operator needs and adds a word the requester must not see.
        out.append("Sent for out-of-band verification before any release.")
    elif forced:
        detail = f.get("forced_reason") or "the condition it names was not met"
        out.append(f"Forced by {forced}: {_sentence(detail)}")
    if f.get("decided_at_step") in _STEP_LABEL:
        out.append(f"Decided at {_STEP_LABEL[f['decided_at_step']]}.")
    if f.get("coverage") is not None:
        out.append(f"Evidence coverage was {f['coverage']:.2f} of 1.00.")
    top = f.get("top_contributions") or []
    if top:
        out.append("Largest contributions to the score:")
        out.append(_bullets([
            f"{c['dimension']}: {c['weighted']:g} points"
            + (" (abstained — scored as unavailable, not as clean)" if c["abstained"] else "")
            + (f" — {c['reason']}" if c.get("reason") else "")
            for c in top]))
    if f.get("reasons"):
        out.append("Reasons on the record:")
        out.append(_bullets(f["reasons"]))
    return "\n".join(out)


def _t_timeline(f: dict[str, Any]) -> str:
    out = [f"{f['event_count']} records for {f.get('transaction_id')}, "
           f"from {f['first_at']} to {f['last_at']}."]
    if isinstance(f.get("elapsed_ms"), int):
        out[0] = out[0][:-1] + f" — {f['elapsed_ms']} ms end to end."
    out.append(_bullets([f"{s['seq']:>4}  {s['at']}  {s['event']}  ({s['actor']})"
                         for s in f["steps"]]))
    if f.get("decision"):
        out.append(f"Final decision on the record: {f['decision']}.")
    return "\n".join(out)


def _t_blocked_count(f: dict[str, Any]) -> str:
    if not f["total"]:
        return f"No decisions were recorded {f['window']}."
    parts = [f"{n} {d}" for d, n in f["by_decision"].items()]
    out = [f"{f['total']} decisions {f['window']}: " + ", ".join(parts) + "."]
    for decision, reasons in f["reasons_by_decision"].items():
        out.append(f"{decision} broke down as:")
        out.append(_bullets([f"{code}: {n}" for code, n in reasons.items()]))
    return "\n".join(out)


def _t_first_time_payees(f: dict[str, Any]) -> str:
    if not f["count"]:
        return (f"No first-time payees {f['window']}. "
                f"{f['records_scanned']} records carrying a payee were checked.")
    out = [f"{f['count']} first-time payee"
           f"{'' if f['count'] == 1 else 's'} {f['window']}:"]
    out.append(_bullets([
        f"{p['payee']}"
        + (f" {p['account']}" if p["account"] else "")
        + (f" — {p['amount']}" if p["amount"] else "")
        + (f" on {p['transaction_id']}" if p["transaction_id"] else "")
        + (f" — {p['status']}" if p["status"] else "")
        for p in f["payees"]]))
    out.append("Account numbers are shown as the last four digits only.")
    return "\n".join(out)


def _t_overrides(f: dict[str, Any]) -> str:
    if not f["count"]:
        return (f"No officer overrides {f['window']}. Every override is a mandatory log event, "
                f"so an empty result here means none were recorded — not that none were logged.")
    out = [f"{f['count']} override{'' if f['count'] == 1 else 's'} {f['window']}, "
           f"by {', '.join(f['actors'])}:"]
    out.append(_bullets([
        f"{o['at']}  {o['transaction_id'] or '—'}  {o['actor']}"
        + (f"  {o['from_decision']} → {o['to_decision']}" if o["to_decision"] else "")
        + (f"  “{o['justification']}”" if o["justification"] else "  (no justification recorded)")
        for o in f["overrides"]]))
    return "\n".join(out)


def _t_policy_changes(f: dict[str, Any]) -> str:
    out: list[str] = []
    if f["version_count"] <= 1 and not f["transitions"]:
        only = next(iter(f["versions"]), "unknown")
        out.append(f"One policy version across {f['records_scanned']} decision records "
                   f"{f['window']}: {only}. Nothing changed.")
    else:
        out.append(f"{f['version_count']} policy versions appear {f['window']}: "
                   f"{', '.join(f['versions'])}.")
        if f["transitions"]:
            out.append("Crossings:")
            out.append(_bullets([f"record {t['seq']} at {t['at']}: "
                                 f"{t['from_version']} → {t['to_version']}"
                                 for t in f["transitions"]]))
    if f["same_version_different_hash"]:
        # Louder than a version bump: the label stayed the same while the content moved.
        out.append(f"Same version string, different policy hash: "
                   f"{', '.join(f['same_version_different_hash'])}. "
                   f"A version was edited in place rather than bumped.")
    if f["replays"]:
        out.append(f"{len(f['replays'])} policy replay"
                   f"{'' if len(f['replays']) == 1 else 's'} recorded:")
        out.append(_bullets([
            f"{r['at']}  {r['transaction_id'] or '—'}  "
            f"{r['from_version']} → {r['to_version']}"
            + ("  decision changed" if r["decision_changed"] else "  decision unchanged")
            for r in f["replays"]]))
    return "\n".join(out)


def _t_chain_integrity(f: dict[str, Any]) -> str:
    if f["ok"]:
        return (f"No. All {f['record_count']} records verify.\n"
                f"Head hash {f['head_hash']} at record {f['head_seq']}, checked {f['verified_at']}.\n"
                f"Each record's hash covers the previous record's hash, so any edit to any record "
                f"would break every record after it.")
    out = [f"Yes. The chain breaks at record {f['first_broken_seq']}.",
           f["detail"] or "",
           f"Records {f['untrusted_from']} onward cannot be trusted: a break is inherited, "
           f"not local."]
    if f["broken_field"] and f["broken_field_source"] == "demo_affordance":
        out.append(f"The field name `{f['broken_field']}` comes from the demo tamper endpoint's own "
                   f"breadcrumb, not from cryptography. A hash mismatch cannot identify which field "
                   f"changed; on a real tampered log this line would be absent.")
    out.append(f"{f['record_count']} records were walked before the walk stopped.")
    return "\n".join(line for line in out if line)


def _t_counterfactual(f: dict[str, Any]) -> str:
    txn = f.get("transaction_id")
    if f["kind"] == "withheld":
        return (f"{f['narrative']}\n"
                f"Quoted from record {f['quoted_from_seq']} exactly as the risk engine published it. "
                f"The full contributions are on the record for anyone with access to it.")
    if not f.get("narrative"):
        return (f"Record {f['quoted_from_seq']} carries no counterfactual for {txn}, so there is "
                f"nothing to quote. This answer does not compute one: if it did, two parts of the "
                f"system could describe the same transaction differently.")
    out = [f["narrative"]]
    if f["kind"] == "categorical":
        out.append("Categorical, not numeric: the outcome was set by a control that replaces the "
                   "score, so there is no lower score that would have changed it.")
    if isinstance(f.get("risk_score"), (int, float)):
        out.append(f"{txn} scored {f['risk_score']:g} and was {f.get('decision') or 'not decided'}.")
    out.append(f"Quoted verbatim from record {f['quoted_from_seq']}, not recomputed.")
    return "\n".join(out)


_TEMPLATES = {
    "why_blocked": _t_why_blocked,
    "transaction_timeline": _t_timeline,
    "blocked_count": _t_blocked_count,
    "first_time_payees": _t_first_time_payees,
    "overrides": _t_overrides,
    "policy_changes": _t_policy_changes,
    "chain_integrity": _t_chain_integrity,
    "counterfactual": _t_counterfactual,
}


def narrate(plan: Plan, facts: dict[str, Any]) -> str:
    """Facts -> prose, from a template. No model, no network, no failure mode."""
    fn = _TEMPLATES.get(plan.intent)
    return fn(facts) if fn else ""


# --------------------------------------------------------------------------- the model boundary
#
# Optional, off by default, and constrained to rephrasing. Three things make that structural rather
# than aspirational: the payload is built only by `privacy.for_model`, the model is handed the
# finished template sentence as the thing to rephrase, and its output is rejected if it contains a
# number the Python facts do not already contain.

_TOKEN_RE = re.compile(r"\[[A-Z]+_[a-z]{4,}\]")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

_MODEL_BRIEF = (
    "Rewrite the DRAFT below as one short paragraph for a bank operations reviewer. "
    "Use only the facts given. Do not add numbers, names, or causes. Do not recommend an action, "
    "and do not say whether the payment should proceed. Keep every identifier exactly as written, "
    "including bracketed tokens."
)


def model_payload(plan: Plan, facts: dict[str, Any],
                  draft: str) -> tuple[dict[str, Any], SessionTokenMap]:
    """Build the only thing that is ever sent to a model. §5

    Goes through `privacy.for_model`, which is the single tested path: `test_no_digits_reach_llm`
    scans that function's output, so a payload assembled any other way would be untested by
    construction. The draft goes in as `draft` and comes back rephrased — the model is never asked
    what happened, only how to say it.
    """
    payload, tokens = for_model({"brief": _MODEL_BRIEF, "intent": plan.intent,
                                 "facts": facts, "draft": draft})
    return payload, tokens


def _render_tokens(text: str, tokens: SessionTokenMap) -> str:
    """Turn surviving tokens into masked tails for display. §12

    Deliberately *not* a full detokenization. The session map can reverse a token completely, and the
    rendering layer for a record view uses that; a chatbot sentence does not need to, and "last four
    only, everywhere, including tooltips and copy payloads" is easier to keep true if the chatbot
    never holds the full value in a string at all.
    """
    def sub(match: re.Match[str]) -> str:
        original = tokens.original(match.group(0))
        if original is None:
            return match.group(0)
        return _mask(original) or match.group(0)
    return _TOKEN_RE.sub(sub, text)


def _numbers_agree(candidate: str, source: str) -> bool:
    """Every number in the model's prose must already appear in the Python prose. §Invariant 2

    Cheap, blunt, and it catches the failure that actually matters — a model that rounds 78 to 80, or
    that helpfully totals two counts and gets it wrong. A rephrasing that drops a number is fine; one
    that invents a number is discarded and the template is used instead.
    """
    allowed = set(_NUMBER_RE.findall(source))
    return all(number in allowed for number in _NUMBER_RE.findall(candidate))


# --------------------------------------------------------------------------- refusals
#
# Three of them, each a distinct `refusal_kind` so the console can style them differently and so a
# test can assert on the kind rather than on the wording. Wording changes; kinds do not.


def _menu(lead: str) -> str:
    return lead + "\n" + _bullets(list(QUESTION_MENU))


def _refuse(kind: str, prose: str, intent: str | None = None) -> ChatAnswer:
    """A refusal carries no citations, and that is the one case where an empty list is correct."""
    return ChatAnswer(prose=prose, refused=True, refusal_kind=kind, intent=intent)


# ---------------------------------------------------------------------------- entry point


def ollama_narrate(payload: dict) -> str | None:
    """Optional prose narrator using local Ollama model (qwen3:14b).

    Strictly constrained by _numbers_agree: any number, amount or count that does not
    match the deterministic Python-computed SQL facts causes the candidate to be discarded.
    """
    import os
    import json
    import urllib.request

    host = (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("INTENTLOCK_LLM_MODEL") or "qwen3:14b"
    prompt = (
        "You are an explainability narrator for INTENTLOCK audit records.\n"
        "Here are the exact facts and template prose:\n"
        f"FACTS: {json.dumps(payload, ensure_ascii=False)}\n"
        "Narrate this in a single professional, concise sentence. Do NOT invent numbers or change any counts."
    )
    req_data = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.1},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=req_data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("message", {}).get("content", "").strip()
    except Exception:
        return None


def answer(store: Any, question: str, narrator: Any = None) -> ChatAnswer:
    """Question -> `ChatAnswer`. The whole pipeline, in the order §6 specifies.

    `narrator` is an optional callable taking the tokenized payload and returning prose. It is only
    consulted when `config.llm_enabled()` is true — which is false in offline mode regardless of the
    flag — and its output is discarded unless it survives `_numbers_agree`. There is no code path in
    which the model's absence produces a worse answer than a wrong one.
    """
    plan = classify(question)

    if plan.intent == "refuse_decide":
        # Verbatim, and before any retrieval: the answer to "should I approve this?" does not depend
        # on what the log says, so looking is both pointless and misleading.
        return _refuse("decision", CANNOT_DECIDE, plan.intent)

    if plan.intent == "needs_transaction":
        return _refuse("needs_transaction",
                       "That question is about one transaction and I could not find an id in it. "
                       "Name the transaction — for example `TXN-2026-0007` — and ask again.",
                       plan.intent)

    if plan.intent == "unclassified":
        return _refuse("unclassified", _menu(CANNOT_CLASSIFY), plan.intent)

    records = query_chain(store, plan)
    facts, seqs = summarize(plan, records, store)

    if not seqs:
        # The citation guard. Implemented here, once, as the only exit from the happy path — a
        # guideline saying "always cite" would be one refactor away from being untrue.
        subject = plan.transaction_id or "that window"
        return _refuse("no_records",
                       f"I have no records for {subject}, so there is nothing I can cite. "
                       f"I do not answer from anything except the audit chain.",
                       plan.intent)

    prose = narrate(plan, facts)
    narrated_by = "template"

    active_narrator = narrator
    if active_narrator is None and llm_enabled():
        active_narrator = ollama_narrate

    if active_narrator is not None and llm_enabled():
        payload, tokens = model_payload(plan, facts, prose)
        try:
            candidate = active_narrator(payload)
        except Exception:
            # A narrator that raises, times out or returns junk costs the demo nothing. The template
            # is already a complete answer, so this is a fallback with no visible failure mode.
            candidate = None
        if isinstance(candidate, str) and candidate.strip():
            rendered = _render_tokens(candidate.strip(), tokens)
            if _numbers_agree(rendered, prose) and not _DECIDE_ADDRESSED.search(rendered):
                prose, narrated_by = rendered, "model"

    return ChatAnswer(prose=prose, facts=facts, record_seqs=seqs, intent=plan.intent,
                      narrated_by=narrated_by)
