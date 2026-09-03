"""The benchmark harness computes the frozen §12 metrics with visible denominators. §17, §25"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from services.audit.app import bench  # noqa: E402


def test_22_rows_and_frozen_denominators() -> None:
    report = bench.run(live=False)
    assert len(report["rows"]) == 22
    m = report["metrics"]
    # Denominators follow contracts/scenarios.json — the frozen contract file. Its classes
    # give 15 ATTACK / 7 LEGIT; the shared context's "14/8" count line contradicts its own
    # table by one scenario. Recorded as C-11 in docs/CHANGES.md.
    assert m["attack_block_rate"]["denominator"] == 15
    assert m["legitimate_approval_success"]["denominator"] == 7
    assert m["false_challenge_rate"]["denominator"] == 3


def test_target_scorecard() -> None:
    """Every attack blocked or contained, every legit approved or on the approval path,
    zero false challenges — with the denominators visible beside the claim."""
    report = bench.run(live=False)
    m = report["metrics"]
    assert m["attack_block_rate"]["numerator"] == 15
    assert m["legitimate_approval_success"]["numerator"] == 7
    assert m["false_challenge_rate"]["numerator"] == 0


def test_silent_escalation_counts_as_blocked() -> None:
    report = bench.run(live=False)
    s09 = next(r for r in report["rows"] if r["id"] == "S09")
    assert s09["actual"] == "SILENT_ESCALATION" and s09["visible_to_requester"] == "PROCESSING"
    assert s09["class"] == "ATTACK"
    assert bench._blocked_outcome(s09) is True


def test_confusion_matrix_is_diagonal() -> None:
    report = bench.run(live=False)
    matrix = report["confusion"]["matrix"]
    for expected, row in matrix.items():
        for actual, n in row.items():
            if expected != actual:
                assert n == 0, f"off-diagonal: {expected}→{actual} = {n}"
    assert not report["confusion"]["off_diagonal"]


def test_sweep_covers_50_to_90() -> None:
    report = bench.run(live=False)
    thresholds = [s["threshold"] for s in report["sweep"]]
    assert thresholds == list(range(50, 91, 5))
    # The chosen point (70) is in the sweep, annotated by the console.
    assert any(s["threshold"] == 70 for s in report["sweep"])


def test_metrics_carry_raw_fractions() -> None:
    report = bench.run(live=False)
    rate = report["metrics"]["attack_block_rate"]
    assert "/15" in rate["display"] and rate["pct"] == "100.0%"
    assert report["metrics"]["false_challenge_rate"]["display"] == "0/3"


def test_prevented_value_is_synthetically_labelled() -> None:
    report = bench.run(live=False)
    assert "synthetic" in report["metrics"]["prevented_fraudulent_value_display"]
    # §10: prevented = sum of attack amounts not executed; all blocked ⇒ all counted.
    assert report["metrics"]["prevented_fraudulent_value_minor_units"] > 0


def test_honesty_note_present() -> None:
    report = bench.run(live=False)
    assert "authored by the same team" in report["honesty"]
    assert "smoke test, not an evaluation" in report["honesty"]


def test_report_written_to_var() -> None:
    bench.run(live=False)
    out = REPO_ROOT / "var" / "bench_latest.json"
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["mode"] == "fixtures"


def test_explanation_completeness_is_100() -> None:
    report = bench.run(live=False)
    assert report["metrics"]["explanation_completeness"]["display"] == "22/22"
    assert report["metrics"]["abstention_correctness"]["display"] == "22/22"
