"""Social-engineering language detector — eight named pressure families.

social_engineering_score: 0-100 RISK — HIGHER = WORSE (opposite direction of the
authenticity scores; comment kept on every function per Team A trap #1).

Rule pass is authoritative in offline mode. The LLM pass may only raise the merged
score above the rule score by at most 25 points and may never lower it below
rule_score − 10 — an injected transcript cannot talk this number down (§11).
"""
from __future__ import annotations

import re

# family -> (points, trigger regexes)
PRESSURE_FAMILIES: list[tuple[str, int, list[str]]] = [
    ("URGENCY", 12, [
        r"urgent", r"immediately", r"right now", r"within the hour", r"before market close",
        r"before the market closes", r"cannot wait", r"asap", r"need it moving", r"move it now",
        r"do not wait", r"before the board call", r"tonight itself", r"today itself"]),
    ("SECRECY", 18, [
        r"do not tell anyone", r"keep this between us", r"confidential", r"off the books",
        r"no need to loop in", r"keep it off the (shared )?tracker", r"keep it quiet",
        r"don'?t log a ticket", r"do not copy anyone", r"has not cleared it yet"]),
    ("AUTHORITY", 12, [
        r"as your cfo", r"this comes from the top", r"board-level", r"i am instructing you",
        r"i'?m instructing", r"i will take responsibility", r"the board has cleared"]),
    ("PROCESS_BYPASS", 20, [
        r"skip the usual process", r"no need for the second approval", r"do not follow the normal workflow",
        r"i'?ll sign later", r"no need to route it", r"treat this as my verification",
        r"no shortcuts? on this one[.,!]? *$",  # negation — excluded below
        r"don'?t call back", r"no need to re-?issue"]),
    ("ISOLATION", 10, [
        r"i'?m in a meeting", r"cannot take calls", r"do not call me back", r"only reply here",
        r"i'?m boarding a flight", r"my assistant will verify on my behalf", r"only email me",
        r"do not disconnect"]),
    ("CONSEQUENCE", 10, [
        r"we will lose the deal", r"penalty", r"legal notice", r"we lose the deal",
        r"the deal team is waiting", r"penalty clause"]),
    ("CHANNEL_STEER", 8, [
        r"move this to whatsapp", r"reply to my personal", r"use this number instead",
        r"only reply on this number", r"reply on chat", r"on this same line"]),
    ("NOVEL_ACCOUNT", 10, [
        r"new bank account", r"updated neft details", r"revised beneficiary", r"account has changed",
        r"revised account", r"moved their collections account", r"route it to their revised account",
        r"the old account is closed"]),
]

# Negations that neutralize a PROCESS_BYPASS trigger (genuine executives insist on process)
_BYPASS_NEGATIONS = [re.compile(r"no shortcuts? on this one", re.IGNORECASE)]


def _family_matches(family: str, pattern: str, text: str) -> list[str]:
    if family == "PROCESS_BYPASS":
        for neg in _BYPASS_NEGATIONS:
            if neg.search(text):
                return []
    return [m.group(0) for m in re.finditer(pattern, text, re.IGNORECASE)]


def rule_pass(text: str) -> tuple[int, list[str]]:
    """Pure rule score. Returns (score 0-100 RISK — higher = worse, indicators)."""
    score = 0
    indicators: list[str] = []
    if not text:
        return 0, []
    for family, points, patterns in PRESSURE_FAMILIES:
        for pattern in patterns:
            for phrase in _family_matches(family, pattern, text):
                score += points
                indicators.append(f"{family}: '{phrase}'")
                break  # one hit per family
    return min(100, score), indicators


def merge_with_llm(rule_score: int, rule_indicators: list[str],
                   llm_result: tuple[int, list[str]] | None) -> tuple[int, list[str], bool]:
    """Merge rule and LLM passes with the anti-injection clamp.

    Clamp: llm may raise above rule_score by at most 25 and may never lower below
    rule_score - 10. Returns (score, indicators, diverged).
    """
    if llm_result is None:
        return rule_score, rule_indicators, False
    llm_score, llm_indicators = llm_result
    merged = 0.5 * rule_score + 0.5 * llm_score
    merged = max(rule_score - 10.0, min(rule_score + 25.0, merged))
    indicators = list(dict.fromkeys(rule_indicators + llm_indicators))  # rule first, dedup
    diverged = abs(rule_score - llm_score) > 30
    if diverged:
        indicators.append("Rule and model assessments diverge — escalating")
    return round(merged), indicators, diverged
