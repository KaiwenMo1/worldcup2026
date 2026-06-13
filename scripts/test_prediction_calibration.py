#!/usr/bin/env python3
"""Smoke-test Prediction Arena calibration report generation."""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.calibration import run_prediction_calibration  # noqa: E402
from app.prediction_arena.public_ledger import append_prediction_record  # noqa: E402
from app.prediction_arena.schemas import PredictionRecord  # noqa: E402
from app.prediction_arena.virtual_scoreboard import settle_virtual_pick  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger = root / "predictions.csv"
        results = root / "results.csv"
        now = datetime.now(timezone.utc)
        for index in range(3):
            prediction = PredictionRecord(
                prediction_id=f"smoke-expert-m{index}",
                match_id=f"M{index}",
                created_at=now + timedelta(minutes=index),
                team_a="France",
                team_b="Brazil",
                stage="group",
                agent_name="Expert Agent",
                regular_time_pick="France",
                regular_time_score="1-0",
                confidence=0.9,
                core_reason="France can control the central matchup if its projected midfield starts.",
                fragile_assumptions=["The projected midfield starts."],
            )
            append_prediction_record(prediction, ledger)
            settle_virtual_pick(
                prediction,
                actual_regular_time_result="Brazil",
                actual_score="1-3",
                path=results,
            )
        report = run_prediction_calibration(
            prediction_paths=[ledger],
            results_path=results,
            scoreline_path=root / "scoreline.csv",
            upset_path=root / "upset.csv",
            performance_path=root / "performance.csv",
        )
        performance = report["agent_performance"][0]
        assert "too_conservative" in performance.warnings
        assert "overconfident" in performance.warnings
        print(
            "Prediction calibration smoke test passed: "
            f"agents={len(report['agent_performance'])}, warnings={','.join(performance.warnings)}"
        )


if __name__ == "__main__":
    main()
