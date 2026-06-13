from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.main import api_analyst_log, api_analyst_logs, api_analyst_profile
from app.tactics import analyst_journal
from app.tactics.analyst_journal import (
    JournalConflictError,
    JournalDataError,
    JournalNotFoundError,
    create_postgame_review,
    create_prediction_log,
    load_prediction_logs,
    summarize_analyst_profile,
)
from app.tactics.schemas import PostgameReviewCreate, PredictionLogCreate


class JournalStorageMixin:
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.logs_path = root / "analyst_prediction_logs.csv"
        self.reviews_path = root / "postgame_reviews.csv"
        self.patches = [
            patch.object(analyst_journal, "PREDICTION_LOGS_PATH", self.logs_path),
            patch.object(analyst_journal, "POSTGAME_REVIEWS_PATH", self.reviews_path),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def prediction(
        self,
        *,
        analyst: str = "Kai",
        score_a: int = 2,
        score_b: int = 1,
        confidence: float = 0.8,
        kickoff_at: datetime | None = None,
        now: datetime | None = None,
    ):
        kickoff = kickoff_at or datetime(2026, 6, 12, 20, tzinfo=timezone.utc)
        created = now or datetime(2026, 6, 11, 12, tzinfo=timezone.utc)
        return create_prediction_log(
            PredictionLogCreate(
                analyst=analyst,
                match_id="FRAvBRA",
                team_a="France",
                team_b="Brazil",
                predicted_team_a_score=score_a,
                predicted_team_b_score=score_b,
                confidence=confidence,
                key_matchup_prediction="France left wing creates the strongest edge",
                tactical_prediction="France attacks transitions behind Brazil's fullbacks",
                kickoff_at=kickoff,
                model_version="ensemble-2026.06",
                data_snapshot_id="snapshot-001",
            ),
            now=created,
        )


class AnalystJournalTests(JournalStorageMixin, unittest.TestCase):
    def test_prediction_is_append_only_and_must_precede_kickoff(self) -> None:
        log = self.prediction()
        rows = load_prediction_logs()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], log)
        self.assertEqual(log.predicted_winner, "France")
        self.assertEqual(log.model_version, "ensemble-2026.06")
        self.assertEqual(log.data_snapshot_id, "snapshot-001")

        with self.assertRaisesRegex(JournalConflictError, "before kickoff"):
            self.prediction(
                kickoff_at=datetime(2026, 6, 12, 20, tzinfo=timezone.utc),
                now=datetime(2026, 6, 12, 20, tzinfo=timezone.utc),
            )

    def test_review_links_to_log_without_rewriting_prediction(self) -> None:
        log = self.prediction()
        original_csv = self.logs_path.read_text(encoding="utf-8")

        review = create_postgame_review(
            PostgameReviewCreate(
                log_id=log.log_id,
                actual_team_a_score=2,
                actual_team_b_score=1,
                key_matchup_correct=True,
                tactical_correct=False,
                notes="Transition prediction was directionally useful.",
            ),
            now=datetime(2026, 6, 13, 12, tzinfo=timezone.utc),
        )

        self.assertEqual(review.log_id, log.log_id)
        self.assertEqual(review.actual_winner, "France")
        self.assertEqual(self.logs_path.read_text(encoding="utf-8"), original_csv)

        with self.assertRaisesRegex(JournalConflictError, "already has"):
            create_postgame_review(
                PostgameReviewCreate(log_id=log.log_id, actual_team_a_score=1, actual_team_b_score=1),
                now=datetime(2026, 6, 13, 13, tzinfo=timezone.utc),
            )

    def test_review_rejects_missing_log_and_pre_kickoff_review(self) -> None:
        missing_id = "a" * 32
        with self.assertRaises(JournalNotFoundError):
            create_postgame_review(
                PostgameReviewCreate(log_id=missing_id, actual_team_a_score=1, actual_team_b_score=0),
                now=datetime(2026, 6, 13, tzinfo=timezone.utc),
            )

        log = self.prediction()
        with self.assertRaisesRegex(JournalConflictError, "before kickoff"):
            create_postgame_review(
                PostgameReviewCreate(log_id=log.log_id, actual_team_a_score=1, actual_team_b_score=0),
                now=datetime(2026, 6, 12, 19, tzinfo=timezone.utc),
            )

    def test_profile_calculates_reviewed_accuracy_and_all_prediction_confidence(self) -> None:
        first = self.prediction(score_a=2, score_b=1, confidence=0.8)
        second = self.prediction(score_a=1, score_b=1, confidence=0.6)
        create_postgame_review(
            PostgameReviewCreate(
                log_id=first.log_id,
                actual_team_a_score=2,
                actual_team_b_score=1,
                key_matchup_correct=True,
                tactical_correct=False,
            ),
            now=datetime(2026, 6, 13, 12, tzinfo=timezone.utc),
        )
        create_postgame_review(
            PostgameReviewCreate(
                log_id=second.log_id,
                actual_team_a_score=0,
                actual_team_b_score=1,
                key_matchup_correct=False,
                tactical_correct=True,
            ),
            now=datetime(2026, 6, 13, 13, tzinfo=timezone.utc),
        )

        profile = summarize_analyst_profile("kai")

        self.assertEqual(profile.number_of_predictions, 2)
        self.assertEqual(profile.reviewed_predictions, 2)
        self.assertEqual(profile.winner_accuracy, 50.0)
        self.assertEqual(profile.score_exact_accuracy, 50.0)
        self.assertEqual(profile.average_confidence, 0.7)
        self.assertEqual(profile.key_matchup_accuracy, 50.0)
        self.assertEqual(profile.tactical_accuracy, 50.0)

    def test_malformed_existing_csv_fails_clearly(self) -> None:
        self.logs_path.write_text("wrong,header\nvalue,row\n", encoding="utf-8")

        with self.assertRaisesRegex(JournalDataError, "Invalid journal schema"):
            load_prediction_logs()


class AnalystApiTests(JournalStorageMixin, unittest.TestCase):
    def test_log_list_and_profile_endpoints(self) -> None:
        now = datetime.now(timezone.utc)
        response = api_analyst_log(
            PredictionLogCreate(
                analyst="API Analyst",
                team_a="France",
                team_b="Brazil",
                predicted_team_a_score=1,
                predicted_team_b_score=0,
                confidence=0.65,
                kickoff_at=now + timedelta(days=1),
            )
        )
        logs = api_analyst_logs("API Analyst", 10)
        profile = api_analyst_profile("API Analyst")

        self.assertTrue(response["append_only"])
        self.assertEqual(logs["count"], 1)
        self.assertEqual(profile["number_of_predictions"], 1)
        self.assertIsNone(profile["winner_accuracy"])

    def test_logs_endpoint_rejects_invalid_limit(self) -> None:
        with self.assertRaises(HTTPException) as context:
            api_analyst_logs(limit=0)

        self.assertEqual(context.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
