"""Fixture validity conformance test.

Asserts that all 22 golden fixtures (S01..S22) are present, parse cleanly,
and declare an expected_decision (APPROVE, CHALLENGE, or BLOCK).
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

SCENARIOS_JSON = Path(__file__).resolve().parents[2] / "contracts" / "scenarios.json"
GOLDEN_DIR = Path(__file__).resolve().parents[2] / "contracts" / "golden"
ALL_IDS = [f"S{i:02d}" for i in range(1, 23)]


def test_all_22_scenarios_and_golden_fixtures_valid():
    """All 22 scenarios S01-S22 exist in scenarios.json and have valid golden fixtures."""
    assert SCENARIOS_JSON.exists(), f"Missing scenarios.json: {SCENARIOS_JSON}"
    scenarios_data = json.loads(SCENARIOS_JSON.read_text(encoding="utf-8"))
    scenarios_map = {s["id"]: s for s in scenarios_data["scenarios"]}

    for sid in ALL_IDS:
        assert sid in scenarios_map, f"Scenario {sid} missing from scenarios.json"
        assert scenarios_map[sid]["expected_decision"] in ("APPROVE", "CHALLENGE", "BLOCK", "SILENT_ESCALATION")

        fixture_path = GOLDEN_DIR / f"{sid}.json"
        assert fixture_path.exists(), f"Missing fixture: {fixture_path}"
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert "assessment" in data, f"{sid} missing assessment"
        assert "intent" in data, f"{sid} missing intent"
        assert "signals" in data, f"{sid} missing signals"
        assert "scenario" in data, f"{sid} missing scenario"
