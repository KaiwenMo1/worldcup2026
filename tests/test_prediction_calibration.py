from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.calibration import (
    analyze_prediction_target_calibration,
    analyze_scoreline_calibration,
    analyze_upset_calibration,
    prediction_target_issues,
    run_prediction_calibration,
    score_underdog_path_quality,
)
from app.prediction_arena.public_ledger import append_prediction_record
from app.prediction_arena.schemas import PredictionRecord, VirtualPickResult
from app.prediction_arena.virtual_scoreboard import settle_virtual_pick


NOW = datetime(2026, 6, 12, 12, tzinfo=timezone.utc)


def prediction(
    prediction_id: str,
    match_id: str,
    agent: str,
    pick: str,
    score: str,
    confidence: float,
    *,
    stage: str = "group",
    qualification: str | None = None,
    penalty_probability: float | None = None,
    reason: str = "A short reason.",
) -> PredictionRecord:
    return PredictionRecord(
        prediction_id=prediction_id,
        match_id=match_id,
        created_at=NOW,
        team_a="France",
        team_b="Brazil",
        stage=stage,
        agent_name=agent,
        regular_time_pick=pick,
        regular_time_score=score,
        qualification_pick=qualification,
        penalty_probability=penalty_probability,
        confidence=confidence,
        core_reason=reason,
        fragile_assumptions=["Projected lineup uncertainty."],
    )


def result(
    prediction_id: str,
    match_id: str,
    agent: str,
    pick: str,
    actual: str,
    score_pick: str,
    actual_score: str,
    confidence: float,
    *,
    upset_bonus: int = 0,
) -> VirtualPickResult:
    winner_points = 3 if pick == actual else 0
    score_points = 5 if score_pick == actual_score else 0
    return VirtualPickResult(
        result_id=(prediction_id.encode().hex() + ("0" * 32))[:32],
        prediction_id=prediction_id,
        match_id=match_id,
        agent_name=agent,
        regular_time_pick=pick,
        actual_regular_time_result=actual,
        score_pick=score_pick,
        actual_score=actual_score,
        winner_points=winner_points,
        score_points=score_points,
        qualification_points=0,
        upset_bonus=upset_bonus,
        confidence_penalty=-1 if not winner_points and confidence > 0.65 else 0,
        total_points=winner_points + score_points + upset_bonus,
        confidence=confidence,
        settled_at=NOW,
    )


class ScorelineCalibrationTests(unittest.TestCase):
    def test_detects_common_score_overprediction_three_plus_gap_and_confidence(self) -> None:
        rows = [
            result(f"expert-{index}", f"M{index}", "Expert Agent", "France", "Brazil", "1-0", "1-3", 0.9)
            for index in range(3)
        ]

        report = analyze_scoreline_calibration(rows)[0]

        self.assertEqual(report.overpredicted_scorelines, ["1-0"])
        self.assertTrue(report.underpredicts_three_plus)
        self.assertTrue(report.exact_score_confidence_too_high)
        self.assertIn("underpredicts_three_plus_goal_games", report.warnings)


class UpsetCalibrationTests(unittest.TestCase):
    def test_detects_never_and_overpicks_while_scoring_path_quality_separately(self) -> None:
        predictions = []
        results = []
        for index in range(3):
            match_id = f"M{index}"
            base = prediction(f"base-{index}", match_id, "Base Model", "France", "1-0", 0.6)
            favorite = prediction(f"favorite-{index}", match_id, "Favorite Agent", "France", "1-0", 0.6)
            upset = prediction(
                f"upset-{index}",
                match_id,
                "Upset Agent",
                "Brazil",
                "0-1",
                0.4,
                reason=(
                    "Brazil can keep the match compact and use transition space if France's "
                    "fullbacks advance together."
                ),
            )
            predictions.extend([base, favorite, upset])
            results.extend(
                [
                    result(base.prediction_id, match_id, "Base Model", "France", "Brazil", "1-0", "0-1", 0.6),
                    result(favorite.prediction_id, match_id, "Favorite Agent", "France", "Brazil", "1-0", "0-1", 0.6),
                    result(upset.prediction_id, match_id, "Upset Agent", "Brazil", "Brazil", "0-1", "0-1", 0.4, upset_bonus=2),
                ]
            )

        reports = {row.agent_name: row for row in analyze_upset_calibration(predictions, results)}

        self.assertTrue(reports["Favorite Agent"].never_picks_underdogs)
        self.assertTrue(reports["Upset Agent"].overpicks_underdogs)
        self.assertEqual(reports["Upset Agent"].correct_upset_calls, 3)
        self.assertGreater(reports["Upset Agent"].average_underdog_path_quality, 0.7)
        self.assertGreater(score_underdog_path_quality(predictions[-1]), 0.7)


class TargetCalibrationTests(unittest.TestCase):
    def test_flags_target_confusion_and_missing_knockout_penalty_probability(self) -> None:
        confused = prediction(
            "confused",
            "M1",
            "Confused Agent",
            "France advance",
            "1-0",
            0.6,
            stage="knockout",
            qualification="France advance",
            penalty_probability=None,
        )

        issues = prediction_target_issues(confused)
        report = analyze_prediction_target_calibration([confused])[0]

        self.assertIn("regular_time_pick_uses_qualification_language", issues)
        self.assertIn("knockout_missing_penalty_probability", issues)
        self.assertEqual(report.target_confusion_count, 1)
        self.assertEqual(report.missing_penalty_probability_count, 1)
        self.assertIn("target_confusion", report.warnings)


class PerformanceTrackerTests(unittest.TestCase):
    def test_writes_three_reports_and_combines_required_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "predictions.csv"
            results_path = root / "results.csv"
            for index in range(3):
                base = prediction(
                    f"base-{index}",
                    f"M{index}",
                    "Base Model",
                    "France",
                    "1-0",
                    0.7,
                    stage="knockout",
                    qualification="France advance",
                    penalty_probability=0.2,
                )
                row = prediction(
                    f"expert-{index}",
                    f"M{index}",
                    "Expert Agent",
                    "France",
                    "1-0",
                    0.9,
                    stage="knockout",
                    qualification="France advance",
                    penalty_probability=None,
                    reason="France can control the central matchup if the projected midfield starts.",
                )
                append_prediction_record(
                    base.model_copy(update={"created_at": NOW + timedelta(minutes=index)}),
                    ledger,
                )
                append_prediction_record(row.model_copy(update={"created_at": NOW + timedelta(minutes=index)}), ledger)
                settle_virtual_pick(
                    row,
                    actual_regular_time_result="Brazil",
                    actual_score="1-3",
                    actual_qualification_result="Brazil advance",
                    path=results_path,
                    settled_at=NOW + timedelta(minutes=index),
                )

            report = run_prediction_calibration(
                prediction_paths=[ledger],
                results_path=results_path,
                scoreline_path=root / "scoreline.csv",
                upset_path=root / "upset.csv",
                performance_path=root / "performance.csv",
            )
            performance = report["agent_performance"][0]

            self.assertEqual(performance.agent_name, "Expert Agent")
            self.assertIn("too_conservative", performance.warnings)
            self.assertIn("too_favorite_biased", performance.warnings)
            self.assertIn("overconfident", performance.warnings)
            self.assertIn("target_confusion", performance.warnings)
            self.assertTrue((root / "scoreline.csv").exists())
            self.assertTrue((root / "upset.csv").exists())
            self.assertTrue((root / "performance.csv").exists())


if __name__ == "__main__":
    unittest.main()
