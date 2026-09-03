"""B15 — the investigation summary: the only place an LLM speaks.

The model receives a decision that has ALREADY been made, with all its numbers, and
writes the paragraph a human reads. It cannot change anything because the `Decision`
object is frozen by the time it is called. Offline mode serves the cached/template
narrative — which is the scored feature (N25a): the decision is identical without it.

Hard rules (§18.1): called after decide(), never before; prose only; numbers in the
output must already appear in the input; accounts arrive pre-redacted; a disclaimer is
appended by code, not by the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Fixed vocabulary (§18.2) so C can render icons and the audit log can aggregate.
NEXT_STEPS: tuple[str, ...] = (
    "contact_executive_out_of_band", "verify_account_with_vendor_on_file",
    "notify_security_officer", "request_secondary_approver", "hold_for_cooldown",
    "file_sar_draft", "no_action_required", "complete_approval_in_console",
    "named_human_review", "answer_comprehension_challenge",
)

#: Appended by code, not by the model (§18.1 rule 5).
DISCLAIMER = "Narrative generated from the decision above; it did not influence the decision."


@dataclass(frozen=True)
class InvestigationRequest:
    decision: str
    risk_score: int
    intent_confidence: int
    contributions: tuple[dict, ...]
    fingerprint_deltas: tuple[dict, ...]
    counterfactuals: tuple[str, ...]
    scenario_id: str = ""
    # NOT included: raw transcript, full account numbers, executive PII, audio, video.


def _numbers_in(text: str) -> set[str]:
    return set(re.findall(r"\d[\d,\.]*", text))


def summarize(request: InvestigationRequest, *, llm_prose: str | None = None) -> tuple[str, list[str]]:
    """(`investigation_summary`, `recommended_next_steps`). Template-first, LLM-optional.

    The LLM's paragraph is *accepted* only when it invents no number that was not already
    in the decision — a model that invents "₹4.1 crore" in a report about ₹2.5 crore
    destroys credibility faster than having no summary at all.
    """
    if request.decision not in ("APPROVE", "CHALLENGE", "BLOCK"):
        raise AssertionError(
            "investigator called before decide(); the pipeline was reordered."
        )

    top = sorted(request.contributions, key=lambda c: -float(c.get("points", 0)))[:3]
    reasons = "; ".join(
        f"{str(c.get('factor')).replace('_', ' ')} contributed {float(c.get('points', 0)):.1f} points"
        for c in top
    ) or "no single dimension dominates"

    if request.decision == "BLOCK":
        head = (f"Refused at risk {request.risk_score}/100 with intent confidence "
                f"{request.intent_confidence}/100.")
    elif request.decision == "CHALLENGE":
        head = (f"Held for verification at risk {request.risk_score}/100; intent confidence "
                f"{request.intent_confidence}/100.")
    else:
        head = (f"Approved at risk {request.risk_score}/100; intent confidence "
                f"{request.intent_confidence}/100.")
    template = f"{head} {reasons.capitalize()}."

    # The LLM may only rephrase. Numbers must be a subset of the input's numbers; a
    # `decision` key in the output is refused outright.
    prose = template
    if llm_prose:
        if re.search(r"\bdecision\b", llm_prose, re.IGNORECASE):
            pass  # refused — keep the template
        elif _numbers_in(llm_prose) <= _numbers_in(
            f"{request.risk_score} {request.intent_confidence} "
            + " ".join(str(c.get("points", "")) for c in request.contributions)
            + " ".join(str(c.get("raw_score", "")) for c in request.contributions)
            + " ".join(str(d.get("expected", "")) for d in request.fingerprint_deltas)
        ):
            prose = llm_prose.strip()

    summary = f"{prose} {DISCLAIMER}"[:1800]

    steps: list[str] = []
    if request.decision == "BLOCK":
        steps = ["notify_security_officer", "contact_executive_out_of_band"]
    elif request.decision == "CHALLENGE":
        steps = ["answer_comprehension_challenge", "complete_approval_in_console"]
    else:
        steps = ["no_action_required"]
    return summary, [s for s in steps if s in NEXT_STEPS]
