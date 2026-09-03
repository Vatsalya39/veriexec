"""Generate golden fixtures: run all 22 samples through the offline pipeline and
write {intent, signals, expected_decision} per scenario to contracts/golden/.

Teams B and C hand-wrote expected DECISIONS; these fixtures carry A's actual offline
OUTPUTS so B can develop against real signal values and C against real payloads
without running A's service. Regenerate with:
    PYTHONPATH=packages .venv/bin/python packages/signal_intel/scripts/gen_golden.py
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "packages"))

from signal_intel.pipeline import process_communication  # noqa: E402

SAMPLES = REPO / "packages" / "signal_intel" / "samples"
GOLDEN = REPO / "contracts" / "golden"


def main():
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for i in range(1, 23):
        sid = f"S{i:02d}"
        s = json.loads((SAMPLES / f"{sid}.json").read_text(encoding="utf-8"))
        out = process_communication({
            "channel": s["channel"],
            "raw_text_or_transcript": s["raw_text_or_transcript"],
            "metadata": s["metadata"],
            "sample_id": sid,
            "detector_script": s["detector_script"],
        })
        fixture = {
            "sample_id": sid,
            "label": s["label"],
            "class": s["class"],
            "hero": s["hero"],
            "channel": s["channel"],
            "narration": s["narration"],
            "expected_decision": s["expected_decision"],
            "expected_override": s.get("expected_override"),
            "intent": out["intent"],
            "signals": out["signals"],
        }
        (GOLDEN / f"{sid}.json").write_text(
            json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{sid}: {s['expected_decision']:8} "
              f"ident={out['signals']['identity_confidence']:3} "
              f"auth={out['signals']['communication_authenticity']:3} "
              f"se={out['signals']['social_engineering_score']:3}")


if __name__ == "__main__":
    main()
