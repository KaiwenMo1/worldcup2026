from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.prediction_arena.public_ledger import append_prediction_record, lock_prediction
from app.prediction_arena.schemas import PredictionRecord, PredictionStage
from app.prediction_arena.virtual_scoreboard import (
    VirtualScoreboardError,
    compute_leaderboard,
    evaluate_arena_predictions,
    load_virtual_results,
    select_match_predictions,
    settle_match_predictions,
    settle_virtual_pick,
)


NOW = datetime(2026, 6, 12, 12, tzinfo=timezone.utc)


def record(
    prediction_id: str,
    match_id: str,
    agent: str,
    pick: str,
    score: str,
    confidence: float,
    *,
    version: int = 1,
    qualification: str | None = None,
) -> PredictionRecord:
    stage = PredictionStage.KNOCKOUT if qualification else PredictionStage.GROUP
    return PredictionRecord(
        prediction_id=prediction_id,
        version=version,
        match_id=match_id,
        created_at=NOW + timedelta(minutes=version),
        team_a="France",
        team_b="Brazil",
        stage=stage,
        agent_name=agent,
        regular_time_pick=pick,
        regular_time_score=score,
        qualification_pick=qualification,
        penalty_probability=0.2 if qualification else None,
        confidence=confidence,
        core_reason="Transparent test call.",
        fragile_assumptions=["Test fixture uncertainty."],
        entertainment_disclaimer="Entertainment-only technical forecast.",
    )


class MatchSettlementTests(unittest.TestCase):
    def test_fixture_scores_all_agents_and_correct_upset_calls(self) -> None:
        fixture = Path("data/prediction_arena/test_data/sample_predictions.csv")
        with tempfile.TemporaryDirectory() as directory:
            results_path = Path(directory) / "results.csv"
            results = settle_match_predictions(
                "M900",
                actual_score="1-2",
                actual_regular_time_result="Brazil",
                actual_qualification_result="Brazil advance",
                prediction_paths=[fixture],
                results_path=results_path,
                settled_at=NOW,
            )
            by_agent = {result.agent_name: result for result in results}

            self.assertEqual(len(results), 5)
            self.assertEqual(by_agent["Upset Agent"].winner_points, 3)
            self.assertEqual(by_agent["Upset Agent"].score_points, 5)
            self.assertEqual(by_agent["Upset Agent"].qualification_points, 2)
            self.assertEqual(by_agent["Upset Agent"].upset_bonus, 2)
            self.assertEqual(by_agent["Upset Agent"].total_points, 12)
            self.assertEqual(by_agent["Kevin Agent"].upset_bonus, 2)
            self.assertEqual(by_agent["Base Model"].confidence_penalty, -1)
            self.assertEqual(by_agent["Final Forecast Agent"].confidence_penalty, -1)

    def test_settling_same_match_twice_does_not_duplicate_agent_results(self) -> None:
        fixture = Path("data/prediction_arena/test_data/sample_predictions.csv")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            first = settle_match_predictions(
                "M900",
                actual_score="1-2",
                actual_regular_time_result="Brazil",
                actual_qualification_result="Brazil advance",
                prediction_paths=[fixture],
                results_path=path,
                settled_at=NOW,
            )
            second = settle_match_predictions(
                "M900",
                actual_score="2-0",
                actual_regular_time_result="France",
                actual_qualification_result="France advance",
                prediction_paths=[fixture],
                results_path=path,
                settled_at=NOW + timedelta(hours=1),
            )

            self.assertEqual(first, second)
            self.assertEqual(len(load_virtual_results(path)), 5)

    def test_selection_prefers_locked_record_over_newer_draft(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "predictions.csv"
            locked = append_prediction_record(
                record("expert-m1-v1", "M1", "Expert Agent", "France", "1-0", 0.6),
                ledger,
            )
            lock_prediction(locked.prediction_id, ledger)
            append_prediction_record(
                record("expert-m1-v2", "M1", "Expert Agent", "Brazil", "0-1", 0.6, version=2),
                ledger,
            )

            selected = select_match_predictions("M1", prediction_paths=[ledger])

            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0].prediction_id, "expert-m1-v1")

    def test_actual_result_must_match_actual_score(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(VirtualScoreboardError):
                settle_match_predictions(
                    "M900",
                    actual_score="1-1",
                    actual_regular_time_result="France",
                    prediction_paths=[Path("data/prediction_arena/test_data/sample_predictions.csv")],
                    results_path=Path(directory) / "results.csv",
                )


class LeaderboardEvaluationTests(unittest.TestCase):
    def test_leaderboard_returns_required_metrics_and_calibration_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            for index in range(3):
                prediction = record(
                    f"expert-m{index}-v1",
                    f"M{index}",
                    "Expert Agent",
                    "France",
                    "2-0",
                    0.9,
                )
                settle_virtual_pick(
                    prediction,
                    actual_regular_time_result="Brazil",
                    actual_score="0-1",
                    path=path,
                    settled_at=NOW + timedelta(minutes=index),
                )
            summary = evaluate_arena_predictions(path)
            leader = compute_leaderboard(path)[0]

            self.assertEqual(leader.matches_predicted, 3)
            self.assertEqual(leader.total_points, -3)
            self.assertEqual(leader.winner_accuracy, 0)
            self.assertEqual(leader.exact_score_hits, 0)
            self.assertIsNone(leader.qualification_accuracy)
            self.assertEqual(leader.average_confidence, 0.9)
            self.assertEqual(leader.calibration_warning, "overconfident")
            self.assertEqual(summary["matches_settled"], 3)
            self.assertEqual(summary["predictions_scored"], 3)


if __name__ == "__main__":
    unittest.main()
