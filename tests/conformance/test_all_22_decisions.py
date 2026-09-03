"""All 22 Decisions Conformance Test.

Runs the benchmark evaluation across all 22 scenarios and verifies
that actual decisions match the expected decisions in the frozen fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from services.audit.app import bench


def test_all_22_decisions_match_expected():
    """All 22 scenario decisions match the expected decision."""
    report = bench.run(live=False)
    assert len(report["rows"]) == 22

    failures = []
    for r in report["rows"]:
        if r["actual"] != r["expected"]:
            failures.append(f"{r['id']}: expected {r['expected']}, got {r['actual']}")

    assert not failures, f"Mismatched decisions:\n" + "\n".join(failures)
