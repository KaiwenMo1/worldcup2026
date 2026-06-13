#!/usr/bin/env python3
"""Smoke-test entertainment-only Prediction Arena virtual scoring."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.prediction_arena.virtual_scoreboard import (  # noqa: E402
    evaluate_arena_predictions,
    settle_match_predictions,
)


def main() -> None:
    fixture = ROOT / "data" / "prediction_arena" / "test_data" / "sample_predictions.csv"
    with tempfile.TemporaryDirectory() as directory:
        results_path = Path(directory) / "virtual_results.csv"
        results = settle_match_predictions(
            "M900",
            actual_score="1-2",
            actual_regular_time_result="Brazil",
            actual_qualification_result="Brazil advance",
            prediction_paths=[fixture],
            results_path=results_path,
        )
        summary = evaluate_arena_predictions(results_path)
        leaders = summary["leaderboard"]
        assert len(results) == 5
        assert leaders[0]["agent_name"] in {"Kevin Agent", "Upset Agent"}
        assert leaders[0]["total_points"] == 12
        assert summary["matches_settled"] == 1
        print(
            "Virtual scoreboard smoke test passed: "
            f"results={len(results)}, leader={leaders[0]['agent_name']}, points={leaders[0]['total_points']}"
        )


if __name__ == "__main__":
    main()
