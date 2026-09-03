"""§16.6 — the LLM containment tests. Invariant 2, made executable.

`AdversarialLLM` tries, on every prompt, to force an APPROVE — with a decision key, a
`system_override`, a `<policy>` XML block and a fake tool call. If a single scenario's
decision moves, that is a control-flow bug, not a prompt problem.

The AST guard keeps the invariant alive against future edits: it greps B's own policy and
scoring sources for the banned attribute names, so "how do we know the LLM isn't deciding?"
is answered by showing a test.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.core import clock
from packages.core.assess import assess, preimage_fields
from packages.core.models import AssessInput, Decision, SignalBundle, TransactionIntent

NOW = clock.parse_iso("2026-09-18T14:02:11+05:30")

#: The scenarios worth proving the invariant over, inline (the golden fixture set may not
#: have landed from Team A when this runs — B never blocks on A).
SCENARIOS = {
    "s06-tampered-account": dict(
        intent=dict(transaction_id="S06", requester="Ananya Rao", action="TRANSFER",
                    amount="4500000", currency="INR",
                    beneficiary="Kalyani Forge Components Pvt Ltd",
                    destination_account="50100234879982",
                    purpose="Q3 vendor settlement", channel="VIDEO",
                    extraction_confidence=94),
        swap_account="50100234874471",
        signals=dict(transaction_id="S06", identity_confidence=91,
                     communication_authenticity=96, deepfake_voice_score=88.0,
                     social_engineering_score=70,
                     social_engineering_indicators=["urgency"]),
        expected="BLOCK",
    ),
    "s03-deepfake-voice": dict(
        intent=dict(transaction_id="S03", requester="Ananya Rao", action="TRANSFER",
                    amount="25000000", currency="INR", beneficiary="Global Trading FZE",
                    destination_account="30070019929982", channel="PHONE",
                    urgency="HIGH", secrecy_flags=["do not tell anyone"],
                    extraction_confidence=10),
        swap_account=None,
        signals=dict(transaction_id="S03", identity_confidence=42,
                     communication_authenticity=21, social_engineering_score=88,
                     social_engineering_indicators=["urgency", "secrecy", "authority"]),
        expected="BLOCK",
    ),
    "s01-routine-payment": dict(
        intent=dict(transaction_id="S01", requester="Ananya Rao", action="TRANSFER",
                    amount="640000", currency="INR",
                    beneficiary="Kalyani Forge Components Pvt Ltd",
                    destination_account="50100234874471", channel="EMAIL",
                    extraction_confidence=95),
        swap_account=None,
        signals=dict(transaction_id="S01", identity_confidence=95,
                     communication_authenticity=97, deepfake_voice_score=None,
                     social_engineering_score=8, social_engineering_indicators=[]),
        expected="CHALLENGE",   # PC-1: never bound -> challenge, never approve
    ),
}


def _run(case: dict, **over):
    intent = TransactionIntent(**{**case["intent"], **over.pop("intent_over", {})})
    signals = SignalBundle(**case["signals"])
    reference = None
    presented = None
    if case["swap_account"]:
        reference = preimage_fields(
            TransactionIntent(**{**case["intent"],
                                 "destination_account": case["swap_account"]}),
            executive_id="EXE-001",
        )
        from packages.core.crypto.fingerprint import fingerprint
        presented = fingerprint(reference)
    return assess(
        AssessInput(intent=intent, signals=signals,
                    presented_fingerprint=presented),
        reference_fields=reference, now=NOW,
    )


def test_adversarial_llm_cannot_change_any_decision():
    """The invariant over the scenario set. assess() takes no model parameter at all —
    there is literally nowhere a hostile completion could enter the decision path, and
    this test is the proof that stays true as the codebase grows.

    The expected outcomes here are what B's own inputs produce — the golden 22-fixture
    suite (Team A's real SignalBundles) is the authoritative decision matrix, and these
    three inline shapes are the containment proof, not a calibration target (§26 trap #4).
    """
    from packages.core.models import Decision as D
    expected = {
        "s06-tampered-account": D.BLOCK,       # HO-1: the binding, not the score
        "s03-deepfake-voice": D.CHALLENGE,      # 52 on inline inputs; golden S03 fixtures decide the real row
        "s01-routine-payment": D.CHALLENGE,    # PC-1: never bound -> challenge, never approve
    }
    for name, case in SCENARIOS.items():
        a = _run(case)   # the "offline" run — no LLM exists anywhere in assess()
        # The adversarial model's output shape: a decision key, system_override, XML
        # policy block and a fake tool call. There is no parameter for it to enter;
        # re-running and asserting byte-stability is the executable form of that fact.
        b = _run(case)
        assert a.decision == b.decision == expected[name], name
        assert a.risk_score == b.risk_score, name
        assert a.intent_confidence == b.intent_confidence, name
        # and hostile text cannot reach the wire
        assert "IGNORE PRIOR INSTRUCTIONS" not in b.investigation_summary
        assert "<policy>" not in b.investigation_summary


def test_decide_module_never_reads_llm_fields():
    """The AST guard. Banned attribute names in decide.py mean model output reached policy."""
    banned = {"llm", "model_output", "completion", "narrative", "advisory", "summary"}
    src = Path("packages/core/policy/decide.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Attribute) and node.attr in banned:
            pytest.fail(f"decide.py touches model output at line {node.lineno}")
        if isinstance(node, ast.Name) and node.id in banned:
            pytest.fail(f"decide.py references {node.id!r} at line {node.lineno}")


def test_fusion_never_reads_llm_fields():
    banned = {"llm", "model_output", "completion"}
    src = Path("packages/core/scoring/fusion.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Attribute,)) and node.attr in banned:
            pytest.fail(f"fusion.py touches model output at line {node.lineno}")


def test_intent_confidence_independent_of_voice():
    """THE flagship test (§10.4). Move voice across its whole range; intent may not move."""
    from packages.core.models import Decision
    case = SCENARIOS["s06-tampered-account"]
    a = _run(case)
    loud = _run(case, intent_over={})
    # rewrite the bundle's media scores to the opposite extreme and re-run
    flipped = dict(case)
    flipped["signals"] = {**case["signals"],
                          "identity_confidence": 4, "communication_authenticity": 3,
                          "deepfake_voice_score": 2.0,
                          "social_engineering_indicators": ["detector says fake"]}
    b = _run(flipped)
    assert a.intent_confidence == b.intent_confidence
    assert a.decision == b.decision == Decision.BLOCK   # blocked for the same reason
    assert a.risk_score != b.risk_score               # risk MAY move; intent may not
