"""Evaluate immutable analyst predictions against completed matches."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.evaluation.postmatch_evaluator import outcome, stable_evaluation_id
from app.evaluation.schemas import AnalystEvaluation, CompletedMatch, EvaluationStatus
from app.evaluation.storage import load_records, upsert_records
from app.tactics.analyst_journal import load_postgame_reviews, load_prediction_logs


ROOT = Path(__file__).resolve().parents[2]
ANALYST_EVALUATION_PATH = ROOT / "data" / "derived" / "analyst_evaluation_results.csv"
ANALYST_EVALUATION_FIELDS = list(AnalystEvaluation.model_fields)


def evaluate_analyst_logs(
    completed: CompletedMatch,
    *,
    evaluated_at: datetime | None = None,
) -> list[AnalystEvaluation]:
    reviews = {review.log_id: review for review in load_postgame_reviews()}
    output = []
    for log in load_prediction_logs():
        same_match_id = log.match_id is not None and log.match_id == completed.match_id
        same_orientation = (log.team_a.casefold(), log.team_b.casefold()) == (
            completed.team_a.casefold(),
            completed.team_b.casefold(),
        )
        reverse_orientation = (log.team_a.casefold(), log.team_b.casefold()) == (
            completed.team_b.casefold(),
            completed.team_a.casefold(),
        )
        if not same_orientation and not reverse_orientation:
            continue
        if log.match_id is not None and not same_match_id:
            continue
        actual_a, actual_b = (
            (completed.team_b_score, completed.team_a_score)
            if reverse_orientation
            else (completed.team_a_score, completed.team_b_score)
        )
        actual_winner = outcome(log.team_a, log.team_b, actual_a, actual_b)
        review = reviews.get(log.log_id)
        output.append(
            AnalystEvaluation(
                evaluation_id=stable_evaluation_id("analyst", completed.match_id, log.log_id),
                match_id=completed.match_id,
                log_id=log.log_id,
                analyst=log.analyst,
                team_a=log.team_a,
                team_b=log.team_b,
                predicted_team_a_score=log.predicted_team_a_score,
                predicted_team_b_score=log.predicted_team_b_score,
                actual_team_a_score=actual_a,
                actual_team_b_score=actual_b,
                confidence=log.confidence,
                winner_hit=log.predicted_winner == actual_winner,
                exact_score_hit=(
                    log.predicted_team_a_score == actual_a and log.predicted_team_b_score == actual_b
                ),
                key_matchup_correct=review.key_matchup_correct if review else None,
                tactical_correct=review.tactical_correct if review else None,
                status=EvaluationStatus.EVALUATED if review else EvaluationStatus.PARTIAL,
                explanation=(
                    "Winner and exact score use the immutable pre-match log. "
                    "Key-matchup and tactical accuracy require a linked post-game review."
                ),
                evaluated_at=evaluated_at or datetime.now(timezone.utc),
            )
        )
    return output


def write_analyst_evaluations(records: list[AnalystEvaluation], path: Path = ANALYST_EVALUATION_PATH) -> list:
    return upsert_records(path, records, AnalystEvaluation, ANALYST_EVALUATION_FIELDS)


def load_analyst_evaluations(path: Path = ANALYST_EVALUATION_PATH) -> tuple[list[AnalystEvaluation], list]:
    return load_records(path, AnalystEvaluation, ANALYST_EVALUATION_FIELDS)
