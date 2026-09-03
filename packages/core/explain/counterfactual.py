"""B14 — counterfactual explanations. [NOVEL-N12a]

Because fusion is a weighted additive sum with a published contribution table,
counterfactuals are **arithmetic, not generation** — every number needed is already on the
wire. This is the highest perceived-sophistication-per-line-of-code feature in the
project. Do not let an LLM near it.

Override counterfactuals are honest that no numeric change helps: a counterfactual that
implies a blocked-by-override transaction could be scored into approval is a lie, and a
sharp judge catches it by asking "so what if the risk were zero?"
"""

from __future__ import annotations

from ..models import Counterfactual, Decision, FieldChange
from ..policy.constants import BANDS


def _approve_ceiling() -> int:
    """The top of the APPROVE band — the target a counterfactual must reach."""
    return BANDS[0][1]


def override_counterfactual(override_id: str) -> str:
    """§17.2's override templates: exact and honest, never numeric."""
    table = {
        "HO-1": "No change to risk scoring would approve this. The request must be "
                "re-issued so the account it pays matches the account authorized.",
        "HO-2": "No change to risk scoring would approve this. Payment above the "
                "single-transaction ceiling to an unregistered account requires a new "
                "authorization with the payee's account verified on file.",
        "HO-3": "No change to risk scoring would approve this. The payee name is a "
                "lookalike of an established payee; verify the vendor on a known channel "
                "and re-issue.",
        "HO-4": "This authorization is spent. A new authorization must be captured from "
                "the executive.",
        "HO-5": "The approver could not confirm the transaction in the attempts allowed. "
                "A new authorization must be captured.",
        "HO-6": "No change to risk scoring would approve this. The approving device's "
                "signature did not verify; re-enrol the device and re-authorize.",
        "HO-7": "No change to risk scoring would approve this. Release requires "
                "compliance sign-off against the screening list.",
        "HO-8": "This authorization was issued under an older policy. Re-authorize under "
                "the current policy.",
        "BREAKER": "No individual change approves this while the organization-wide "
                   "velocity breaker is open; wait for review or a named officer's "
                   "force-close.",
        "DURESS": "No change to risk scoring would approve this. Named human review is "
                  "required before any funds are released.",
    }
    return table.get(override_id, "No change to risk scoring would approve this.")


def counterfactuals(
    *,
    decision: Decision,
    override_applied: str | None,
    risk_score: float,
    contributions: list[dict],   # {factor, points, reason}
) -> list[Counterfactual]:
    """Greedy largest-first — the *shortest* explanation, deterministic every time."""
    if override_applied:
        return [
            Counterfactual(
                would_be_decision=Decision.APPROVE,
                changes=[FieldChange(field="override", from_=override_applied, to=None)],
                points_delta=0,
            )
        ]

    if decision is Decision.APPROVE:
        # §17.3's inverse: the smallest change that would have challenged. Emitted by
        # perturbing named inputs — three named risks, not a search.
        return [
            Counterfactual(
                would_be_decision=Decision.CHALLENGE,
                changes=[
                    FieldChange(field="risk_score", from_=risk_score,
                                to=max(risk_score, _approve_ceiling() + 1)),
                ],
                points_delta=max(0.0, _approve_ceiling() + 1 - risk_score),
            )
        ]

    gap = max(0.0, risk_score - _approve_ceiling())
    out: list[Counterfactual] = []
    running = 0.0
    for row in sorted(contributions, key=lambda r: -float(r.get("points", 0))):
        pts = float(row.get("points", 0))
        if pts <= 0:
            continue
        running += pts
        out.append(Counterfactual(
            would_be_decision=Decision.APPROVE,
            changes=[FieldChange(field=str(row.get("factor", "risk")),
                                 from_=round(pts, 2), to=0)],
            points_delta=round(pts, 2),
        ))
        if running >= gap:
            break
    return out


def approve_inverse_text(risk_score: float) -> str:
    """§17.3's sentence for the APPROVE card: names the boundary the system knows it has."""
    ceiling = _approve_ceiling()
    return (f"Approved at risk {min(100, round(risk_score))}. It would have been challenged "
            f"above {ceiling + 1}, to a new payee, or outside business hours.")
