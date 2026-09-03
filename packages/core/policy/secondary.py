"""B20 — collusion-aware secondary approver selection. [NOVEL-N22]

P1, cut this before cutting anything in §16–§19 — but cheap and high-judge-value.

The novel part is *who*: not "any manager", but the approver least likely to be
compromised by the same attack. Two exclusions carry the idea: **no self-approval** and
**no direct reporting line** — an attacker who has socially engineered the finance
manager has, in practice, also engineered that manager's direct report, who will not
overrule their boss under time pressure.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Selection:
    approver_id: str | None
    name: str
    department: str
    score: float
    rationale: str
    excluded: tuple[str, ...]     # who was refused, and why — C renders this


def select_secondary(
    requester_id: str,
    pool: list[dict],               # {id, name, department, reports_to, device_family,
                                    #  channel_family, available, recent_contact_ids}
    *,
    origin_device_family: str = "",
    origin_channel_family: str = "",
) -> Selection:
    """Score every candidate for *independence*, exclude the compromisable, pick the max.

    An empty eligible pool ESCALATES rather than approves — `None` means named human
    review, never "skip the second approver".
    """
    scored: list[tuple[float, dict, list[str]]] = []
    excluded: list[str] = []

    for p in sorted(pool, key=lambda x: str(x.get("id"))):
        pid = str(p.get("id"))
        if pid == requester_id:
            excluded.append(f"{pid}: no self-approval")
            continue
        if str(p.get("reports_to", "")) == requester_id:
            excluded.append(f"{pid}: reports to the requester — not independent")
            continue
        if str(p.get("has_reports_containing", "") or "") == requester_id:
            excluded.append(f"{pid}: the requester reports to them — not independent")
            continue

        s = 0.0
        why: list[str] = []
        if p.get("department") and p.get("department") != "requester_department":
            s += 30
            why.append("different department")
        if p.get("device_family") and p.get("device_family") != origin_device_family:
            s += 25
            why.append("different device family")
        if p.get("channel_family") and p.get("channel_family") != origin_channel_family:
            s += 20
            why.append("different channel family")
        if requester_id not in (p.get("recent_contact_ids") or []):
            s += 15
            why.append("not party to the originating thread")
        if p.get("available"):
            s += 10
            why.append("available now")
        scored.append((s, p, why))

    if not scored:
        return Selection(
            approver_id=None, name="(no eligible secondary approver)",
            department="", score=0.0,
            rationale="No eligible independent approver: escalate to named human review "
                      "rather than approving with a compromised pool.",
            excluded=tuple(excluded),
        )

    # max() over (score, id) is deterministic — no dict-order dependence (replay).
    best = max(scored, key=lambda t: (t[0], str(t[1].get("id"))))
    s, p, why = best
    rationale = (
        f"Routed to {p.get('name', p.get('id'))} ({p.get('department', 'unknown dept')}) — "
        + ", ".join(why)
        if why else f"Routed to {p.get('name', p.get('id'))}"
    )
    return Selection(
        approver_id=str(p.get("id")), name=str(p.get("name", "")),
        department=str(p.get("department", "")), score=s,
        rationale=rationale, excluded=tuple(excluded),
    )
