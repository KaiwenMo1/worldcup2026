"""Append-only CSV journal for human pre-match predictions and post-game reviews."""

from __future__ import annotations

import csv
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.tactics.schemas import (
    AnalystProfile,
    PostgameReview,
    PostgameReviewCreate,
    PredictionLog,
    PredictionLogCreate,
)


ROOT = Path(__file__).resolve().parents[2]
PREDICTION_LOGS_PATH = ROOT / "data" / "analyst_prediction_logs.csv"
POSTGAME_REVIEWS_PATH = ROOT / "data" / "postgame_reviews.csv"

PREDICTION_FIELDS = [
    "log_id",
    "analyst",
    "match_id",
    "team_a",
    "team_b",
    "predicted_winner",
    "predicted_team_a_score",
    "predicted_team_b_score",
    "confidence",
    "key_matchup_prediction",
    "tactical_prediction",
    "created_at",
    "kickoff_at",
    "model_version",
    "data_snapshot_id",
]
REVIEW_FIELDS = [
    "review_id",
    "log_id",
    "actual_team_a_score",
    "actual_team_b_score",
    "actual_winner",
    "key_matchup_correct",
    "tactical_correct",
    "notes",
    "created_at",
]

_WRITE_LOCK = threading.Lock()


class AnalystJournalError(ValueError):
    """Base error for journal validation and storage failures."""


class JournalNotFoundError(AnalystJournalError):
    """Raised when a review references a missing prediction log."""


class JournalConflictError(AnalystJournalError):
    """Raised when an append-only journal constraint would be violated."""


class JournalDataError(AnalystJournalError):
    """Raised when an existing journal CSV does not match its contract."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AnalystJournalError("timestamps must include a timezone")
    return value.astimezone(timezone.utc)


def _now_utc(now: datetime | None = None) -> datetime:
    return _utc(now) if now is not None else datetime.now(timezone.utc)


def _winner(team_a: str, team_b: str, score_a: int, score_b: int) -> str:
    if score_a > score_b:
        return team_a
    if score_b > score_a:
        return team_b
    return "Draw"


def _optional(value: str | None) -> str:
    return value or ""


def _optional_bool(value: str | None) -> bool | None:
    if value in (None, ""):
        return None
    normalized = value.casefold()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise JournalDataError(f"Invalid boolean value in journal CSV: {value!r}")


def _read_rows(path: Path, fields: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != fields:
                raise JournalDataError(
                    f"Invalid journal schema in {path}: expected {fields}, found {reader.fieldnames}"
                )
            return list(reader)
    except OSError as exc:
        raise JournalDataError(f"Could not read journal file {path}: {exc}") from exc


def _append_row_unlocked(path: Path, fields: list[str], row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    if exists:
        _read_rows(path, fields)
    try:
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            if not exists:
                writer.writeheader()
            writer.writerow({field: row.get(field, "") for field in fields})
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise JournalDataError(f"Could not append journal file {path}: {exc}") from exc


def _prediction_from_row(row: dict[str, str]) -> PredictionLog:
    try:
        return PredictionLog.model_validate(
            {
                **row,
                "match_id": row.get("match_id") or None,
                "predicted_team_a_score": int(row["predicted_team_a_score"]),
                "predicted_team_b_score": int(row["predicted_team_b_score"]),
                "confidence": float(row["confidence"]),
                "key_matchup_prediction": row.get("key_matchup_prediction") or None,
                "tactical_prediction": row.get("tactical_prediction") or None,
                "model_version": row.get("model_version") or None,
                "data_snapshot_id": row.get("data_snapshot_id") or None,
            }
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise JournalDataError(f"Invalid prediction log row {row.get('log_id', '<unknown>')}: {exc}") from exc


def _review_from_row(row: dict[str, str]) -> PostgameReview:
    try:
        return PostgameReview.model_validate(
            {
                **row,
                "actual_team_a_score": int(row["actual_team_a_score"]),
                "actual_team_b_score": int(row["actual_team_b_score"]),
                "key_matchup_correct": _optional_bool(row.get("key_matchup_correct")),
                "tactical_correct": _optional_bool(row.get("tactical_correct")),
                "notes": row.get("notes") or None,
            }
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise JournalDataError(f"Invalid post-game review row {row.get('review_id', '<unknown>')}: {exc}") from exc


def load_prediction_logs(
    analyst: str | None = None,
    *,
    limit: int | None = None,
) -> list[PredictionLog]:
    """Load prediction logs newest first without mutating the append-only journal."""
    logs = [_prediction_from_row(row) for row in _read_rows(PREDICTION_LOGS_PATH, PREDICTION_FIELDS)]
    if analyst is not None:
        logs = [log for log in logs if log.analyst.casefold() == analyst.casefold()]
    logs.sort(key=lambda log: log.created_at, reverse=True)
    return logs[:limit] if limit is not None else logs


def load_postgame_reviews() -> list[PostgameReview]:
    """Load post-game reviews newest first."""
    reviews = [_review_from_row(row) for row in _read_rows(POSTGAME_REVIEWS_PATH, REVIEW_FIELDS)]
    reviews.sort(key=lambda review: review.created_at, reverse=True)
    return reviews


def create_prediction_log(request: PredictionLogCreate, *, now: datetime | None = None) -> PredictionLog:
    """Append a prediction only when it is created before kickoff."""
    created_at = _now_utc(now)
    kickoff_at = _utc(request.kickoff_at)
    if created_at >= kickoff_at:
        raise JournalConflictError("Prediction logs must be created before kickoff.")

    payload = request.model_dump()
    payload["kickoff_at"] = kickoff_at
    log = PredictionLog(
        **payload,
        log_id=uuid4().hex,
        predicted_winner=_winner(
            request.team_a,
            request.team_b,
            request.predicted_team_a_score,
            request.predicted_team_b_score,
        ),
        created_at=created_at,
    )
    row = {
        **log.model_dump(mode="json"),
        "match_id": _optional(log.match_id),
        "key_matchup_prediction": _optional(log.key_matchup_prediction),
        "tactical_prediction": _optional(log.tactical_prediction),
        "model_version": _optional(log.model_version),
        "data_snapshot_id": _optional(log.data_snapshot_id),
    }
    with _WRITE_LOCK:
        _append_row_unlocked(PREDICTION_LOGS_PATH, PREDICTION_FIELDS, row)
    return log


def create_postgame_review(request: PostgameReviewCreate, *, now: datetime | None = None) -> PostgameReview:
    """Append one review linked to an existing immutable pre-match prediction."""
    created_at = _now_utc(now)
    with _WRITE_LOCK:
        logs = [_prediction_from_row(row) for row in _read_rows(PREDICTION_LOGS_PATH, PREDICTION_FIELDS)]
        original = next((log for log in logs if log.log_id == request.log_id), None)
        if original is None:
            raise JournalNotFoundError(f"Prediction log {request.log_id!r} does not exist.")
        if created_at < _utc(original.kickoff_at):
            raise JournalConflictError("Post-game reviews cannot be created before kickoff.")

        existing_reviews = [_review_from_row(row) for row in _read_rows(POSTGAME_REVIEWS_PATH, REVIEW_FIELDS)]
        if any(review.log_id == request.log_id for review in existing_reviews):
            raise JournalConflictError(f"Prediction log {request.log_id!r} already has a post-game review.")

        review = PostgameReview(
            **request.model_dump(),
            review_id=uuid4().hex,
            actual_winner=_winner(
                original.team_a,
                original.team_b,
                request.actual_team_a_score,
                request.actual_team_b_score,
            ),
            created_at=created_at,
        )
        row = {
            **review.model_dump(mode="json"),
            "key_matchup_correct": "" if review.key_matchup_correct is None else str(review.key_matchup_correct).lower(),
            "tactical_correct": "" if review.tactical_correct is None else str(review.tactical_correct).lower(),
            "notes": _optional(review.notes),
        }
        _append_row_unlocked(POSTGAME_REVIEWS_PATH, REVIEW_FIELDS, row)
    return review


def _accuracy(correct: int, reviewed: int) -> float | None:
    return round((100 * correct / reviewed), 1) if reviewed else None


def summarize_analyst_profile(analyst: str) -> AnalystProfile:
    """Summarize one analyst using immutable predictions joined to their reviews."""
    logs = load_prediction_logs(analyst)
    reviews_by_log = {review.log_id: review for review in load_postgame_reviews()}
    reviewed_pairs = [(log, reviews_by_log[log.log_id]) for log in logs if log.log_id in reviews_by_log]

    winner_correct = sum(
        log.predicted_winner
        == _winner(log.team_a, log.team_b, review.actual_team_a_score, review.actual_team_b_score)
        for log, review in reviewed_pairs
    )
    score_correct = sum(
        log.predicted_team_a_score == review.actual_team_a_score
        and log.predicted_team_b_score == review.actual_team_b_score
        for log, review in reviewed_pairs
    )
    matchup_reviews = [review.key_matchup_correct for _, review in reviewed_pairs if review.key_matchup_correct is not None]
    tactical_reviews = [review.tactical_correct for _, review in reviewed_pairs if review.tactical_correct is not None]

    return AnalystProfile(
        analyst=analyst,
        number_of_predictions=len(logs),
        reviewed_predictions=len(reviewed_pairs),
        winner_accuracy=_accuracy(winner_correct, len(reviewed_pairs)),
        score_exact_accuracy=_accuracy(score_correct, len(reviewed_pairs)),
        average_confidence=round(sum(log.confidence for log in logs) / len(logs), 3) if logs else None,
        key_matchup_accuracy=_accuracy(sum(matchup_reviews), len(matchup_reviews)),
        tactical_accuracy=_accuracy(sum(tactical_reviews), len(tactical_reviews)),
    )
