"""Invariant 3: Unavailable != clean.

A detector that abstains (short utterance, low SNR, unknown codec, missing modality)
contributes ZERO authenticity evidence. Missing evidence may never be scored as favourable evidence.
"""

from __future__ import annotations

import pytest

from packages.core.scoring.fusion import fuse, DimensionScore


def test_abstained_score_increases_risk_via_uncertainty():
    """Null score reduces coverage and incurs an uncertainty penalty compared to favourable score."""
    # Favourable scores across all 7 dimensions
    all_favourable = [
        DimensionScore("beneficiary", 10.0, "Low payee risk", "EV-1"),
        DimensionScore("behavioural", 10.0, "Normal baseline", "EV-2"),
        DimensionScore("semantic_drift", 10.0, "No drift", "EV-3"),
        DimensionScore("device_channel", 10.0, "Independent channel", "EV-4"),
        DimensionScore("social_engineering", 10.0, "No pressure", "EV-5"),
        DimensionScore("communication_authenticity", 10.0, "Voice genuine", "EV-6"),
        DimensionScore("identity_confidence", 10.0, "MFA matched", "EV-7"),
    ]
    fused_clean = fuse({d.dimension: d for d in all_favourable})
    assert fused_clean.coverage == 1.0
    assert fused_clean.uncertainty_points == 0.0

    # With communication_authenticity and identity_confidence abstained (None)
    abstained = [
        DimensionScore("beneficiary", 10.0, "Low payee risk", "EV-1"),
        DimensionScore("behavioural", 10.0, "Normal baseline", "EV-2"),
        DimensionScore("semantic_drift", 10.0, "No drift", "EV-3"),
        DimensionScore("device_channel", 10.0, "Independent channel", "EV-4"),
        DimensionScore("social_engineering", 10.0, "No pressure", "EV-5"),
        DimensionScore("communication_authenticity", None, abstain_reason="No audio/video data"),
        DimensionScore("identity_confidence", None, abstain_reason="Device unknown"),
    ]
    fused_abstained = fuse({d.dimension: d for d in abstained})
    assert fused_abstained.coverage < 1.0
    assert fused_abstained.uncertainty_points > 0.0
    assert fused_abstained.score is not None and fused_clean.score is not None
    assert fused_abstained.score > fused_clean.score, "Abstaining must yield higher risk than favourable evidence"
