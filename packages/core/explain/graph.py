"""B19 — the evidence subgraph for Team C.

C renders a reactflow graph; B emits the data and never the layout. Coordinates are a
frontend concern. Node count is capped at 14 so the graph stays readable on a projector
at the back of a room; `status` is in `{clean, neutral, warn, critical}`; every scoring
node carries its `points` so the graph and the contribution table can never disagree;
the edge that caused the decision is the only one with `emphasis: true`.
"""

from __future__ import annotations

from ..models import BeneficiaryGraph, GraphEdge, GraphNode

#: The cap. More than 14 nodes on a projector is a hairball, and a hairball is worse
#: than a list. If truncated, C must show a visible chip — never silently drop nodes.
MAX_NODES = 14


def build(
    *,
    executive_id: str | None,
    executive_name: str,
    beneficiary_id: str | None,
    beneficiary_name: str,
    account_on_record: bool,
    beneficiary_tier: str,
    contributions: list[dict],
    override_applied: str | None,
    decision: str,
    risk_score: float,
) -> BeneficiaryGraph:
    """The subgraph, deterministic in construction order (replay asserts byte-identity)."""
    nodes: list[GraphNode] = [
        GraphNode(
            id="requester", label=executive_name or "Claimed requester",
            kind="executive", trust="unknown",
        ),
        GraphNode(
            id="beneficiary", label=beneficiary_name or "Unmatched payee",
            kind="beneficiary",
            trust=("trusted" if beneficiary_tier == "established"
                   else "established" if beneficiary_tier == "emerging"
                   else "emerging" if beneficiary_tier == "provisional" else "unknown"),
        ),
        GraphNode(
            id="account", label=("Account on record" if account_on_record
                                 else "Account NOT on record"),
            kind="bank",
            trust="trusted" if account_on_record else "unknown",
        ),
    ]
    edges = [
        GraphEdge(source="requester", target="beneficiary", label="pays", kind="flow"),
        GraphEdge(source="beneficiary", target="account",
                  label=("registered" if account_on_record else "unregistered"),
                  kind="account"),
    ]

    for row in contributions:
        pts = float(row.get("points", 0))
        if pts <= 0:
            continue
        nodes.append(GraphNode(
            id=f"score-{row.get('factor', 'x')}",
            label=f"{str(row.get('factor', '')).replace('_', ' ')}: {pts:.1f}",
            kind="score", trust="warn" if pts < 10 else "critical",
        ))
        edges.append(GraphEdge(
            source=f"score-{row.get('factor', 'x')}", target="decision",
            label=f"{pts:.1f} pts", kind="contribution",
        ))

    nodes.append(GraphNode(
        id="decision",
        label=f"{decision}" + (f" ({override_applied})" if override_applied else ""),
        kind="decision", trust="critical" if decision == "BLOCK"
        else "warn" if decision == "CHALLENGE" else "clean",
        emphasis=True,
    ))
    if override_applied:
        edges.append(GraphEdge(
            source="override", target="decision", label=override_applied,
            kind="override", weight=1,
        ))
        nodes.append(GraphNode(id="override", label=f"Hard override {override_applied}",
                               kind="check", trust="critical"))

    # Enforce the cap: collapse the smallest scoring nodes, keep the structural ones.
    if len(nodes) > MAX_NODES:
        structural = {"requester", "beneficiary", "account", "decision", "override"}
        score_nodes = sorted(
            (n for n in nodes if n.id.startswith("score-")),
            key=lambda n: float(n.label.rsplit(":", 1)[-1]),
        )
        dropped = {n.id for n in score_nodes[: len(nodes) - MAX_NODES]}
        nodes = [n for n in nodes if n.id not in dropped or n.id in structural]
        edges = [e for e in edges if e.source not in dropped]
        kept = {n.id for n in nodes}
        edges = [e for e in edges if e.target in kept and e.source in kept]

    return BeneficiaryGraph(nodes=nodes, edges=edges)
