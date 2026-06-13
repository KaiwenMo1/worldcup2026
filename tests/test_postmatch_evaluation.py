from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.evaluation.analyst_evaluator import evaluate_analyst_logs
from app.evaluation.manager_skill_evaluator import evaluate_manager_skill
from app.evaluation.matchup_evaluator import evaluate_matchup_edge
from app.evaluation.postmatch_evaluator import (
    evaluate_completed_match,
    evaluate_model_prediction,
    load_model_evaluations,
    write_model_evaluations,
)
from app.evaluation.schemas import CompletedMatch, EvaluationStatus, ModelPredictionSnapshot
from app.ingestion.event_data_ingestion import MatchEvent, MatchEventType, MatchSummarySignal
from app.tactics.manager_skills import generate_manager_plan
from app.tactics.schemas import MatchupEdge, PostgameReview, PredictionLog


AT = datetime(2026, 6, 12, 12, tzinfo=timezone.utc)


def completed(team_a: str = "France", team_b: str = "Brazil") -> CompletedMatch:
    return CompletedMatch(
        match_id="test-match",
        team_a=team_a,
        team_b=team_b,
        team_a_score=2,
        team_b_score=1,
        source="test",
    )


def prediction(team_a: str = "France", team_b: str = "Brazil") -> ModelPredictionSnapshot:
    return ModelPredictionSnapshot(
        match_id="test-match",
        team_a=team_a,
        team_b=team_b,
        predicted_team_a_score=2,
        predicted_team_b_score=1,
        team_a_win_probability=0.6,
        draw_probability=0.2,
        team_b_win_probability=0.2,
        model_version="test-v1",
        prediction_source="test_snapshot",
    )


def summary(
    team: str,
    opponent: str,
    *,
    field_tilt: float,
    set_piece_xg: float,
    counterattack_xg: float,
    pressing_proxy: float,
) -> MatchSummarySignal:
    return MatchSummarySignal(
        match_id="test-match",
        team=team,
        opponent=opponent,
        goals=2 if team == "France" else 1,
        xg=1.2,
        shots=5,
        shots_on_target=3,
        field_tilt=field_tilt,
        attacking_third_actions=8,
        box_entries=4,
        set_piece_xg=set_piece_xg,
        counterattack_xg=counterattack_xg,
        pressing_actions=5,
        high_pressing_actions=2,
        pressing_proxy=pressing_proxy,
        goalkeeper_saves=2,
        xg_faced=0.8,
        goals_conceded=1,
        goalkeeper_impact=-0.2,
        event_count=20,
        source="test",
        data_quality="observed_events_with_xg",
        updated_at=AT,
    )


def substitution(team: str, opponent: str, minute: int = 65) -> MatchEvent:
    return MatchEvent(
        event_id=f"{team}-sub",
        match_id="test-match",
        team=team,
        opponent=opponent,
        player="Starter",
        event_type=MatchEventType.SUBSTITUTION,
        minute=minute,
        substitution_replacement="Replacement",
        source="test",
        source_event_type="substitution",
        source_confidence=1.0,
        updated_at=AT,
    )


class ModelEvaluationTests(unittest.TestCase):
    def test_model_evaluation_scores_exact_result_brier_and_bucket(self) -> None:
        result = evaluate_model_prediction(completed(), prediction(), evaluated_at=AT)

        self.assertTrue(result.winner_hit)
        self.assertTrue(result.exact_score_hit)
        self.assertAlmostEqual(result.brier_score, 0.24)
        self.assertEqual(result.calibration_bucket, "0.6-0.7")
        self.assertEqual(result.predicted_outcome, "France")

    def test_model_evaluation_requires_matching_orientation(self) -> None:
        with self.assertRaisesRegex(ValueError, "orientation"):
            evaluate_model_prediction(completed(), prediction("Brazil", "France"), evaluated_at=AT)

    def test_model_evaluation_upsert_is_idempotent_and_typed(self) -> None:
        result = evaluate_model_prediction(completed(), prediction(), evaluated_at=AT)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.csv"

            self.assertFalse(write_model_evaluations([result], path))
            self.assertFalse(write_model_evaluations([result], path))
            loaded, issues = load_model_evaluations(path)

            self.assertFalse(issues)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].brier_score, 0.24)


class TacticalEvaluationTests(unittest.TestCase):
    def test_manager_skill_uses_only_available_components(self) -> None:
        france = summary(
            "France",
            "Brazil",
            field_tilt=0.6,
            set_piece_xg=0.3,
            counterattack_xg=0.4,
            pressing_proxy=30,
        )
        result = evaluate_manager_skill(
            completed(),
            "France",
            "Brazil",
            france,
            [substitution("France", "Brazil")],
            actual_formation=generate_manager_plan("France", "Brazil").expected_formation,
            evaluated_at=AT,
        )

        self.assertEqual(result.status, EvaluationStatus.EVALUATED)
        self.assertEqual(result.evaluated_components, 4)
        self.assertEqual(result.component_score, 1.0)
        self.assertTrue(result.formation_hit)
        self.assertTrue(result.pressing_hit)
        self.assertTrue(result.transition_hit)
        self.assertTrue(result.substitution_hit)

    def test_missing_manager_skill_is_not_evaluable(self) -> None:
        result = evaluate_manager_skill(
            completed("Brazil", "France"),
            "Brazil",
            "France",
            None,
            [],
            evaluated_at=AT,
        )

        self.assertEqual(result.status, EvaluationStatus.NOT_EVALUABLE)
        self.assertEqual(result.evaluated_components, 0)
        self.assertIsNone(result.component_score)

    def test_matchup_edge_uses_type_specific_event_summary_evidence(self) -> None:
        edge = MatchupEdge(
            matchup_type="set_piece_edge",
            team_a="France",
            team_b="Brazil",
            favored_team="France",
            edge_score=0.4,
            edge_label="moderate",
            reason="test",
            data_quality="test",
        )
        summaries = {
            "france": summary(
                "France",
                "Brazil",
                field_tilt=0.6,
                set_piece_xg=0.7,
                counterattack_xg=0.1,
                pressing_proxy=50,
            ),
            "brazil": summary(
                "Brazil",
                "France",
                field_tilt=0.4,
                set_piece_xg=0.1,
                counterattack_xg=0.2,
                pressing_proxy=40,
            ),
        }

        result = evaluate_matchup_edge(completed(), edge, summaries, [], evaluated_at=AT)

        self.assertEqual(result.status, EvaluationStatus.EVALUATED)
        self.assertEqual(result.evidence_metric, "set_piece_xg")
        self.assertEqual(result.observed_favored_team, "France")
        self.assertTrue(result.edge_confirmed)


class AnalystAndIntegrationTests(unittest.TestCase):
    def test_analyst_evaluation_joins_review_without_rewriting_log(self) -> None:
        log = PredictionLog(
            analyst="Kai",
            match_id="test-match",
            team_a="France",
            team_b="Brazil",
            predicted_team_a_score=2,
            predicted_team_b_score=1,
            confidence=0.8,
            kickoff_at=datetime(2026, 6, 12, 14, tzinfo=timezone.utc),
            log_id="a" * 32,
            predicted_winner="France",
            created_at=datetime(2026, 6, 12, 10, tzinfo=timezone.utc),
        )
        review = PostgameReview(
            review_id="b" * 32,
            log_id=log.log_id,
            actual_team_a_score=2,
            actual_team_b_score=1,
            actual_winner="France",
            key_matchup_correct=True,
            tactical_correct=False,
            created_at=datetime(2026, 6, 12, 17, tzinfo=timezone.utc),
        )
        with (
            patch("app.evaluation.analyst_evaluator.load_prediction_logs", return_value=[log]),
            patch("app.evaluation.analyst_evaluator.load_postgame_reviews", return_value=[review]),
        ):
            results = evaluate_analyst_logs(completed(), evaluated_at=AT)

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].winner_hit)
        self.assertTrue(results[0].exact_score_hit)
        self.assertTrue(results[0].key_matchup_correct)
        self.assertFalse(results[0].tactical_correct)

    def test_analyst_match_id_cannot_override_mismatched_teams(self) -> None:
        log = PredictionLog(
            analyst="Kai",
            match_id="test-match",
            team_a="England",
            team_b="Spain",
            predicted_team_a_score=1,
            predicted_team_b_score=0,
            confidence=0.6,
            kickoff_at=datetime(2026, 6, 12, 14, tzinfo=timezone.utc),
            log_id="c" * 32,
            predicted_winner="England",
            created_at=datetime(2026, 6, 12, 10, tzinfo=timezone.utc),
        )
        with (
            patch("app.evaluation.analyst_evaluator.load_prediction_logs", return_value=[log]),
            patch("app.evaluation.analyst_evaluator.load_postgame_reviews", return_value=[]),
        ):
            results = evaluate_analyst_logs(completed(), evaluated_at=AT)

        self.assertEqual(results, [])

    def test_sample_feedback_loop_evaluates_all_available_layers(self) -> None:
        sample = CompletedMatch(
            match_id="FRA-BRA-TEST",
            team_a="France",
            team_b="Brazil",
            team_a_score=2,
            team_b_score=1,
            source="sample",
        )
        snapshot = prediction().model_copy(
            update={
                "match_id": "FRA-BRA-TEST",
                "team_a_win_probability": 0.55,
                "draw_probability": 0.25,
            }
        )

        result = evaluate_completed_match(
            sample,
            snapshot,
            actual_formations={"France": "4-2-3-1"},
            evaluated_at=AT,
        )

        self.assertTrue(result.model.winner_hit)
        self.assertEqual(len(result.managers), 2)
        self.assertGreaterEqual(len(result.matchups), 9)


if __name__ == "__main__":
    unittest.main()
