"""Invariant 7: Every number carries reasons.

Any score above a materiality threshold must emit at least one human-readable reason.
A populated score with an empty reasons array fails schema validation.
"""

from __future__ import annotations

import pytest

from packages.core.scoring.fusion import fuse, DimensionScore


def test_material_scores_must_carry_reasons_and_evidence():
    """Every score contribution that is populated carries a human-readable reason and evidence_ref."""
    scores = [
        DimensionScore("beneficiary", 85.0, "Unrecognized payee in foreign jurisdiction", "EV-BEN-1"),
        DimensionScore("behavioural", 70.0, "Transaction amount 4x median baseline", "EV-BEH-1"),
        DimensionScore("semantic_drift", 60.0, "Destination account changed after authorization", "EV-DRIFT-1"),
        DimensionScore("device_channel", 50.0, "Same channel", "EV-DC-1"),
        DimensionScore("social_engineering", 50.0, "Urgency pressure", "EV-SE-1"),
        DimensionScore("communication_authenticity", 50.0, "Voice check", "EV-VA-1"),
        DimensionScore("identity_confidence", 50.0, "Identity check", "EV-ID-1"),
    ]
    fused = fuse({d.dimension: d for d in scores})
    for c in fused.contributions:
        if c.raw_score > 0:
            assert c.reason is not None and len(c.reason) > 5, f"Missing reason for dimension {c.dimension}"
            assert c.evidence_ref is not None, f"Missing evidence_ref for dimension {c.dimension}"
