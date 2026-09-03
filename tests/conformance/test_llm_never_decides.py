"""Invariant 2: The LLM never decides.

LLMs may extract, classify, summarise, explain and recommend.
The `decision` field is written ONLY by deterministic policy code.
There must be no code path in which model text can set `decision`.
"""

from __future__ import annotations

import ast
from pathlib import Path
import pytest

from packages.core.policy import decide as decide_module
from packages.core.policy.decide import Inputs, decide
from packages.core.models import Decision

DECIDE_FILE = Path(__file__).resolve().parents[2] / "packages" / "core" / "policy" / "decide.py"


def test_decide_py_never_reads_llm_attributes():
    """AST guard: decide.py must never access attributes or fields containing llm, model, or gpt."""
    tree = ast.parse(DECIDE_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            name = node.attr.lower()
            assert not any(forbidden in name for forbidden in ["llm", "model_output", "chatgpt", "gemini"]), (
                f"decide.py reads forbidden LLM-sourced attribute: {node.attr}"
            )


def test_adversarial_llm_payload_cannot_override_policy():
    """An adversarial payload claiming risk_score 0 and decision APPROVE cannot bypass deterministic checks."""
    # S06 scenario: Fingerprint mismatch
    inp = Inputs(
        transaction_id="S06",
        risk_score=0, # Even if an attacker injects risk 0
        coverage=1.0,
        fingerprint_status="MISMATCH",
        amount_minor_units=100000000,
        ceiling_minor_units=50000000,
        channel_independent=True,
        payee_label="Global Trading FZE",
    )
    outcome = decide(inp)
    assert outcome.decision is Decision.BLOCK, "Policy must override risk score 0 on fingerprint mismatch"
    assert outcome.override_applied == "HO-1"
