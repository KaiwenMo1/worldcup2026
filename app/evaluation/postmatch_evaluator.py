"""Evaluate match forecasts against completed results without hiding replay limits."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.evaluation.schemas import (
    CompletedMatch,
    CompletedMatchEvaluation,
    EvaluationStatus,
    ModelPredictionSnapshot,
    PostmatchModelEvaluation,
)
from app.evaluation.storage import load_records, upsert_records
from app.ingestion.event_data_ingestion import load_match_summary_signals, load_normalized_events
from scripts.predict_worldcup import MODEL_PATH, load_model, load_teams, match_probabilities, scoreline_distribution


ROOT = Path(__file__).resolve().parents[2]
LIVE_STATE_PATH = ROOT / "data" / "live_state.json"
POSTMATCH_MODEL_EVALUATION_PATH = ROOT / "data" / "derived" / "postmatch_model_evaluation.csv"
POSTMATCH_MODEL_FIELDS = list(PostmatchModelEvaluation.model_fields)


def stable_evaluation_id(*parts: str) -> str:
    identity = "|".join(parts)
    return f"eval_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}"


def outcome(team_a: str, team_b: str, score_a: int, score_b: int) -> str:
    return team_a if score_a > score_b else team_b if score_b > score_a else "Draw"


def outcome_key(score_a: int, score_b: int) -> str:
    return "team_a_win" if score_a > score_b else "team_b_win" if score_b > score_a else "draw"


def calibration_bucket(probability: float) -> str:
    lower = min(int(probability * 10) / 10, 0.9)
    return f"{lower:.1f}-{lower + 0.1:.1f}"


def evaluate_model_prediction(
    completed: CompletedMatch,
    prediction: ModelPredictionSnapshot,
    *,
    evaluated_at: datetime | None = None,
) -> PostmatchModelEvaluation:
    if (completed.team_a, completed.team_b) != (prediction.team_a, prediction.team_b):
        raise ValueError("prediction teams and orientation must match the completed match")
    probabilities = {
        "team_a_win": prediction.team_a_win_probability,
        "draw": prediction.draw_probability,
        "team_b_win": prediction.team_b_win_probability,
    }
    actual_key = outcome_key(completed.team_a_score, completed.team_b_score)
    predicted_key = max(probabilities, key=probabilities.get)
    actual_vector = {key: float(key == actual_key) for key in probabilities}
    brier = sum((probabilities[key] - actual_vector[key]) ** 2 for key in probabilities)
    confidence = probabilities[predicted_key]
    predicted_outcome = {
        "team_a_win": completed.team_a,
        "draw": "Draw",
        "team_b_win": completed.team_b,
    }[predicted_key]
    actual_outcome = outcome(
        completed.team_a,
        completed.team_b,
        completed.team_a_score,
        completed.team_b_score,
    )
    return PostmatchModelEvaluation(
        evaluation_id=stable_evaluation_id("model", completed.match_id, prediction.model_version),
        match_id=completed.match_id,
        team_a=completed.team_a,
        team_b=completed.team_b,
        predicted_team_a_score=prediction.predicted_team_a_score,
        predicted_team_b_score=prediction.predicted_team_b_score,
        actual_team_a_score=completed.team_a_score,
        actual_team_b_score=completed.team_b_score,
        predicted_outcome=predicted_outcome,
        actual_outcome=actual_outcome,
        exact_score_hit=(
            prediction.predicted_team_a_score == completed.team_a_score
            and prediction.predicted_team_b_score == completed.team_b_score
        ),
        winner_hit=predicted_outcome == actual_outcome,
        team_a_win_probability=round(prediction.team_a_win_probability, 6),
        draw_probability=round(prediction.draw_probability, 6),
        team_b_win_probability=round(prediction.team_b_win_probability, 6),
        predicted_outcome_confidence=round(confidence, 6),
        brier_score=round(brier, 6),
        calibration_bucket=calibration_bucket(confidence),
        model_version=prediction.model_version,
        prediction_source=prediction.prediction_source,
        status=EvaluationStatus.EVALUATED,
        explanation=(
            "Multiclass Brier score is the sum of squared error across team_a_win, draw, and team_b_win. "
            "Calibration bucket uses the model's most confident result probability."
        ),
        evaluated_at=evaluated_at or datetime.now(timezone.utc),
    )


def replay_current_prediction(
    completed: CompletedMatch,
    *,
    use_model: bool = True,
) -> ModelPredictionSnapshot:
    teams = load_teams()
    if completed.team_a not in teams or completed.team_b not in teams:
        raise ValueError(f"Cannot replay prediction for unknown teams: {completed.team_a}, {completed.team_b}")
    bundle = load_model(MODEL_PATH) if use_model else None
    probabilities = match_probabilities(teams[completed.team_a], teams[completed.team_b], bundle=bundle)
    predicted_a, predicted_b, _ = scoreline_distribution(
        teams[completed.team_a],
        teams[completed.team_b],
        bundle=bundle,
    )[0]
    return ModelPredictionSnapshot(
        match_id=completed.match_id,
        team_a=completed.team_a,
        team_b=completed.team_b,
        predicted_team_a_score=predicted_a,
        predicted_team_b_score=predicted_b,
        team_a_win_probability=probabilities["team_a_win"],
        draw_probability=probabilities["draw"],
        team_b_win_probability=probabilities["team_b_win"],
        model_version=(
            f"{MODEL_PATH.name}@trained-through-{bundle.model.get('trained_through', 'unknown')}"
            if bundle is not None
            else "poisson_baseline"
        ),
        prediction_source="current_model_replay_not_historical_snapshot",
    )


def completed_match_from_row(row: dict[str, Any], *, index: int = 0) -> CompletedMatch:
    match_id = str(row.get("match_id") or row.get("provider_match_id") or "").strip()
    if not match_id:
        match_id = stable_evaluation_id(
            "completed-match",
            str(row.get("team_a", "")),
            str(row.get("team_b", "")),
            str(index),
        )
    return CompletedMatch(
        match_id=match_id,
        team_a=str(row["team_a"]),
        team_b=str(row["team_b"]),
        team_a_score=int(row["team_a_score"]),
        team_b_score=int(row["team_b_score"]),
        source=str(row.get("source") or "live_state.json"),
    )


def load_completed_matches(path: Path = LIVE_STATE_PATH) -> list[CompletedMatch]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    source = str(payload.get("source") or "live_state.json")
    return [
        completed_match_from_row({**row, "source": source}, index=index)
        for index, row in enumerate(payload.get("completed_matches", []))
    ]


def evaluate_completed_match(
    completed: CompletedMatch,
    prediction: ModelPredictionSnapshot | None = None,
    *,
    actual_formations: dict[str, str] | None = None,
    use_model: bool = True,
    evaluated_at: datetime | None = None,
) -> CompletedMatchEvaluation:
    from app.evaluation.analyst_evaluator import evaluate_analyst_logs
    from app.evaluation.manager_skill_evaluator import evaluate_manager_skills
    from app.evaluation.matchup_evaluator import evaluate_matchups

    at = evaluated_at or datetime.now(timezone.utc)
    events, _ = load_normalized_events()
    summaries, _ = load_match_summary_signals()
    match_events = [event for event in events if event.match_id == completed.match_id]
    match_summaries = [summary for summary in summaries if summary.match_id == completed.match_id]
    snapshot = prediction or replay_current_prediction(completed, use_model=use_model)
    return CompletedMatchEvaluation(
        completed_match=completed,
        model=evaluate_model_prediction(completed, snapshot, evaluated_at=at),
        managers=evaluate_manager_skills(
            completed,
            match_summaries,
            match_events,
            actual_formations=actual_formations,
            evaluated_at=at,
        ),
        matchups=evaluate_matchups(completed, match_summaries, match_events, evaluated_at=at),
        analysts=evaluate_analyst_logs(completed, evaluated_at=at),
    )


def write_model_evaluations(
    records: list[PostmatchModelEvaluation],
    path: Path = POSTMATCH_MODEL_EVALUATION_PATH,
) -> list[Any]:
    return upsert_records(path, records, PostmatchModelEvaluation, POSTMATCH_MODEL_FIELDS)


def load_model_evaluations(
    path: Path = POSTMATCH_MODEL_EVALUATION_PATH,
) -> tuple[list[PostmatchModelEvaluation], list[Any]]:
    return load_records(path, PostmatchModelEvaluation, POSTMATCH_MODEL_FIELDS)


def write_completed_evaluations(result: CompletedMatchEvaluation) -> list[Any]:
    """Upsert every evaluation surface for one completed match."""
    from app.evaluation.analyst_evaluator import write_analyst_evaluations
    from app.evaluation.manager_skill_evaluator import write_manager_skill_evaluations
    from app.evaluation.matchup_evaluator import write_matchup_evaluations

    return [
        *write_model_evaluations([result.model]),
        *write_manager_skill_evaluations(result.managers),
        *write_matchup_evaluations(result.matchups),
        *write_analyst_evaluations(result.analysts),
    ]
