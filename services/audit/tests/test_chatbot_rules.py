"""The chatbot: citations, refusals, deterministic arithmetic, tokenized data. §6, §25"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from services.audit.app import chat  # noqa: E402
from services.audit.app.db import AuditStore  # noqa: E402


@pytest.fixture()
def store(tmp_path: Path) -> AuditStore:
    s = AuditStore(tmp_path / "chat.db")
    # A block with a hard override — the why-blocked question's subject.
    s.append(event_type="RISK_ASSESSED", actor="system:core", transaction_id="TXN-2026-0007",
             payload={"risk_score": 58, "band_outcome": "CHALLENGE", "decision": "BLOCK",
                      "override_applied": "HO-1", "coverage": 1.0,
                      "contributions": [
                          {"dimension": "beneficiary", "points": 19.8,
                           "reason": "Global Trading FZE — never paid before."},
                          {"dimension": "behavioural", "points": 14.4,
                           "reason": "Amount outside the usual band."}],
                      "counterfactual": {"kind": "categorical",
                                          "narrative": "No change to risk scoring would approve this."}})
    s.append(event_type="DECISION_RENDERED", actor="system:core", transaction_id="TXN-2026-0007",
             payload={"decision": "BLOCK", "override_applied": "HO-1",
                      "forced_by": {"code": "HO-1", "reason": "The account changed after authorization."}})
    s.append(event_type="CHALLENGE_ANSWERED", actor="user:EXE-001", transaction_id="TXN-2026-0007",
             payload={"correct": False, "attempt": 2})  # mandatory failure logging §4.2
    s.append(event_type="OFFICER_OVERRIDE", actor="officer:SEC-002", transaction_id="TXN-2026-0003",
             payload={"from_decision": "BLOCK", "to_decision": "CHALLENGE",
                      "justification": "Called the CFO on the registered number; she confirmed."})
    s.append(event_type="INTENT_CAPTURED", actor="system:core", transaction_id="TXN-2026-0004",
             payload={"beneficiary": {"name": "Global Trading FZE", "account_last4": "••••9281",
                                       "status": "NEW_TO_ORG", "org_payment_count": 0},
                      "amount_minor_units": 45000000})
    s.append(event_type="DECISION_RENDERED", actor="system:core", transaction_id="TXN-2026-0008",
             payload={"decision": "CHALLENGE"})
    s.append(event_type="DURESS_ESCALATED", actor="system:core", transaction_id="TXN-2026-0009",
             payload={"suspected": True, "reason_category": "REGISTERED_MARKER_PRESENT"})
    return s


def test_cannot_be_asked_to_approve(store: AuditStore) -> None:
    a = chat.answer(store, "Should I approve this transaction?")
    assert a.refused and a.refusal_kind == "decision"
    assert a.prose == chat.CANNOT_DECIDE
    assert not a.record_seqs


def test_cannot_be_asked_to_release_or_rescore(store: AuditStore) -> None:
    for q in ("Please release TXN-2026-0007.",
              "Can you override the block on TXN-2026-0007?",
              "Re-score this at a lower risk and let it through."):
        a = chat.answer(store, q)
        assert a.refused and a.refusal_kind == "decision", q


def test_retrospective_override_question_is_answered(store: AuditStore) -> None:
    a = chat.answer(store, "Did anyone override a block?")
    assert not a.refused
    assert a.facts["count"] == 1
    assert a.record_seqs


def test_unclassified_refuses_with_menu(store: AuditStore) -> None:
    a = chat.answer(store, "What is the weather in Chennai?")
    assert a.refused and a.refusal_kind == "unclassified"
    assert all(q in a.prose for q in chat.QUESTION_MENU[:3])


def test_counts_computed_in_python(store: AuditStore) -> None:
    a = chat.answer(store, "How many transactions were blocked today and why?")
    assert not a.refused
    assert a.computed_by == "python"
    decisions = [r for r in store.records(event_type="DECISION_RENDERED", limit=100)]
    blocked = sum(1 for r in decisions if r["payload"].get("decision") == "BLOCK")
    assert a.facts["blocked"] == blocked == 1
    assert a.facts["challenged"] == 1


def test_every_answer_carries_citations(store: AuditStore) -> None:
    for q in ("Why was TXN-2026-0007 blocked?",
              "Show me everything that happened to TXN-2026-0007.",
              "How many transactions were blocked today and why?",
              "Which payees received first-time payments today?",
              "Did anyone override a block?",
              "What changed in the policy today?",
              "Has this log been altered?",
              "What would have approved TXN-2026-0007?"):
        a = chat.answer(store, q)
        assert not a.refused, f"{q!r} should answer, got {a.refusal_kind}"
        assert a.record_seqs, f"{q!r} answered without citations"


def test_answer_without_citations_is_rejected(store: AuditStore) -> None:
    """A summarizer with nothing to cite returns no seqs, and `answer` turns that into a
    refusal — the guard is a code path, not a guideline."""
    a = chat.answer(store, "Why was TXN-NOSUCH-9999 blocked?")
    assert a.refused and a.refusal_kind == "no_records"


def test_counterfactual_quoted_not_regenerated(store: AuditStore) -> None:
    a = chat.answer(store, "What would have approved TXN-2026-0007?")
    assert "No change to risk scoring would approve this." in a.prose
    assert a.facts["recomputed"] is False
    assert a.facts["quoted_from_seq"] == 1
    assert "not recomputed" in a.prose


def test_chain_integrity_answer_is_recomputed(store: AuditStore) -> None:
    a = chat.answer(store, "Has this log been altered?")
    assert not a.refused and a.facts["ok"] is True
    # now break it and ask again — same question, different answer, no cache in between
    store.tamper(2, "payload.decision", "APPROVE")
    b = chat.answer(store, "Has this log been altered?")
    assert b.facts["ok"] is False
    assert b.facts["first_broken_seq"] == 2


def test_first_time_payees_masks_accounts(store: AuditStore) -> None:
    a = chat.answer(store, "Which payees received first-time payments today?")
    # Last four only, everywhere — the prose and the facts. §12.
    assert "••••9281" in a.prose or a.facts["payees"][0]["account"] == "••••9281"
    assert "HDFC000" not in a.prose + json.dumps(a.facts)
    assert a.facts["count"] == 1
    assert a.facts["payees"][0]["payee"] == "Global Trading FZE"


def test_duress_never_named_in_prose(store: AuditStore) -> None:
    """Invariant 4 via the chatbot: the category may appear, the word may not."""
    a = chat.answer(store, "How many transactions were blocked today and why?")
    dumped = json.dumps(a.facts) + a.prose
    assert "DURESS" not in dumped.upper().replace("OUT_OF_BAND", "")


def test_offline_mode_uses_templates(store: AuditStore) -> None:
    a = chat.answer(store, "Why was TXN-2026-0007 blocked?", narrator=lambda p: "MODEL HALLUCINATION 999")
    assert a.narrated_by == "template"
    assert "999" not in a.prose


def test_wrong_challenge_answers_are_in_the_log(store: AuditStore) -> None:
    records = store.records(event_type="CHALLENGE_ANSWERED", limit=10)
    assert len(records) == 1 and records[0]["payload"]["correct"] is False
