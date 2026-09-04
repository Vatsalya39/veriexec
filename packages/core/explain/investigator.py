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


#: The narrator brief. The model may only rephrase the template sentence; §18.1's hard
#: rules are enforced by `summarize`, not by this prompt: numbers must be a subset of
#: the input's, and the acceptance check discards anything that fails it.
_BRIEF = (
    "Rewrite the DRAFT below as one short professional paragraph for a bank operations "
    "reviewer. Use only the facts given. Do not add numbers, names, or causes. Do not "
    "recommend an action, and do not say whether the payment should proceed. Keep every "
    "identifier exactly as written."
)

#: qwen3 is a thinking model: /api/chat returns the reasoning block inline in `content`
#: before the answer. The delimiter below separates the two halves of its output.
_THINK_END = "</think>"


def ollama_prose(request: "InvestigationRequest", draft: str) -> str | None:
    """The optional LLM paragraph, from the local Ollama model (qwen3:14b by default).

    Returns `None` on any failure — unreachable model, timeout, junk output — which the
    caller turns into "keep the template". There is no code path in which the model's
    absence produces a worse summary than a wrong one.

    Gated by the §20 kill switch *and* the env contract: `NO_LLM`/`MINIMAL` mode and
    `INTENTLOCK_MODE=offline` both force the template, which is the N25a guarantee.
    """
    import json
    import os
    import urllib.request

    from .. import degraded
    from ..config import settings

    if not degraded.llm_enabled() or settings().mode == "offline":
        return None
    host = (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("INTENTLOCK_LLM_MODEL") or "qwen3:14b"
    prompt = (
        f"{_BRIEF}\n\nDRAFT: {draft}\n\n"
        "Respond with the rewritten paragraph only, no preamble."
    )
    data = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.1},
    }).encode("utf-8")
    req = urllib.request.Request(f"{host}/api/chat", data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            out = json.loads(resp.read().decode("utf-8"))
            text = str(out.get("message", {}).get("content", "")).strip()
            if _THINK_END in text:
                text = text.split(_THINK_END, 1)[1].strip()
            return text or None
    except Exception:
        return None


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
    # `decision` key in the output is refused outright. The allowed set carries the fixed
    # scale denominators too ("40/100"): a rephrasing that keeps the template's own
    # numbers verbatim must not be rejected over a "/100" the template itself wrote.
    prose = template
    if llm_prose:
        allowed = _numbers_in(
            f"{request.risk_score} {request.intent_confidence} "
            + " ".join(str(c.get("points", "")) for c in request.contributions)
            + " ".join(str(c.get("raw_score", "")) for c in request.contributions)
            + " ".join(str(d.get("expected", "")) for d in request.fingerprint_deltas)
            + template
        )
        if re.search(r"\bdecision\b", llm_prose, re.IGNORECASE):
            pass  # refused — keep the template
        elif _numbers_in(llm_prose) <= allowed:
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
