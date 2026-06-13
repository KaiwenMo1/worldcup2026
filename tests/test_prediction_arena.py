from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.prediction_arena import (
    AgentPrediction,
    PredictionArenaGuardrailError,
    PredictionLedgerConflict,
    PredictionRecord,
    PredictionStage,
    PredictionStatus,
    PredictionTarget,
    TargetPick,
    append_prediction_record,
    compute_leaderboard,
    ensure_entertainment_disclaimer,
    load_predictions,
    lock_prediction,
    reject_betting_advice_language,
    settle_virtual_pick,
)


NOW = datetime(2026, 6, 12, 12, tzinfo=timezone.utc)


def prediction(
    prediction_id: str = "kevin-m001-v1",
    *,
    confidence: float = 0.61,
    pick: str = "Draw",
    score: str = "1-1",
) -> PredictionRecord:
    return PredictionRecord(
        prediction_id=prediction_id,
        match_id="M001",
        created_at=NOW,
        team_a="France",
        team_b="Brazil",
        stage=PredictionStage.KNOCKOUT,
        agent_name="Kevin Agent",
        regular_time_pick=pick,
        regular_time_score=score,
        qualification_pick="France advance",
        penalty_probability=0.22,
        confidence=confidence,
        core_reason="France has the clearest transition matchup.",
        fragile_assumptions=["France's left winger starts."],
    )


class PredictionArenaSchemaTests(unittest.TestCase):
    def test_prediction_target_separates_regular_time_and_knockout_targets(self) -> None:
        target = PredictionTarget(
            regular_time_90=TargetPick(pick="Draw", score="1-1", confidence=0.42),
            after_extra_time=TargetPick(pick="France", score="2-1", confidence=0.36),
            qualification=TargetPick(pick="France advance", confidence=0.58),
            penalty_shootout_probability=0.22,
        )
        arena_prediction = AgentPrediction(
            agent_name="Test Agent",
            match_id="M001",
            team_a="France",
            team_b="Brazil",
            stage=PredictionStage.KNOCKOUT,
            prediction_target=target,
            confidence=0.55,
        )

        self.assertEqual(arena_prediction.prediction_target.regular_time_90.pick, "Draw")
        self.assertEqual(arena_prediction.prediction_target.qualification.pick, "France advance")

    def test_group_stage_rejects_knockout_only_targets(self) -> None:
        with self.assertRaises(ValidationError):
            AgentPrediction(
                agent_name="Test Agent",
                match_id="M001",
                team_a="France",
                team_b="Brazil",
                stage=PredictionStage.GROUP,
                prediction_target=PredictionTarget(
                    regular_time_90=TargetPick(pick="Draw", score="1-1", confidence=0.42),
                    qualification=TargetPick(pick="France advance", confidence=0.58),
                ),
                confidence=0.55,
            )

    def test_guardrails_attach_disclaimer_and_reject_advice_language(self) -> None:
        safe = ensure_entertainment_disclaimer("France has the clearer transition path.")

        self.assertIn("not betting advice", safe.casefold())
        self.assertEqual(reject_betting_advice_language(prediction()), prediction())
        with self.assertRaises(PredictionArenaGuardrailError):
            reject_betting_advice_language("This is a sure bet with guaranteed profit.")


class PredictionLedgerTests(unittest.TestCase):
    def test_missing_ledger_is_created_append_locks_and_cannot_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "ledger.csv"
            record = append_prediction_record(prediction(), path)

            self.assertTrue(path.exists())
            self.assertEqual(load_predictions(path), [record])
            locked = lock_prediction(record.prediction_id, path)
            self.assertEqual(locked.status, PredictionStatus.LOCKED)
            self.assertEqual(lock_prediction(record.prediction_id, path), locked)
            with self.assertRaises(PredictionLedgerConflict):
                append_prediction_record(prediction(), path)


class VirtualScoreboardTests(unittest.TestCase):
    def test_settlement_is_idempotent_and_leaderboard_is_virtual_points_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            record = prediction()
            first = settle_virtual_pick(
                record,
                actual_regular_time_result="Draw",
                actual_score="1-1",
                actual_qualification_result="France advance",
                path=path,
                settled_at=NOW,
            )
            second = settle_virtual_pick(
                record,
                actual_regular_time_result="Brazil",
                actual_score="0-2",
                path=path,
                settled_at=NOW,
            )
            leaderboard = compute_leaderboard(path)

            self.assertEqual(first, second)
            self.assertEqual(first.total_points, 10)
            self.assertEqual(leaderboard[0].total_points, 10)
            self.assertEqual(leaderboard[0].winner_accuracy, 1)

    def test_wrong_high_confidence_pick_receives_penalty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = settle_virtual_pick(
                prediction("expert-m001-v1", confidence=0.72, pick="France", score="2-0"),
                actual_regular_time_result="Draw",
                actual_score="1-1",
                path=Path(directory) / "results.csv",
                settled_at=NOW,
            )

            self.assertEqual(result.confidence_penalty, -1)
            self.assertEqual(result.total_points, -1)


if __name__ == "__main__":
    unittest.main()
