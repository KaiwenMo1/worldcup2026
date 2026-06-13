"""Entertainment-only virtual scoring for Prediction Arena agents."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.ingestion.normalizers import safe_read_csv, safe_write_csv
from app.prediction_arena.public_ledger import PRE_MATCH_PREDICTIONS_PATH, load_predictions
from app.prediction_arena.schemas import LeaderboardEntry, PredictionRecord, VirtualPickResult


ROOT = Path(__file__).resolve().parents[2]
VIRTUAL_RESULTS_PATH = ROOT / "data" / "prediction_arena" / "ledgers" / "virtual_pick_results.csv"
MODEL_PREDICTIONS_PATH = ROOT / "data" / "prediction_arena" / "ledgers" / "model_predictions.csv"
VIRTUAL_RESULT_FIELDS = [
    "result_id",
    "prediction_id",
    "match_id",
    "agent_name",
    "regular_time_pick",
    "actual_regular_time_result",
    "qualification_pick",
    "actual_qualification_result",
    "score_pick",
    "actual_score",
    "winner_points",
    "score_points",
    "qualification_points",
    "upset_bonus",
    "confidence_penalty",
    "total_points",
    "confidence",
    "settled_at",
]


class VirtualScoreboardError(ValueError):
    """Raised when virtual scoring data cannot be validated."""


def _validate_actual_result(actual_score: str, actual_regular_time_result: str) -> None:
    if not re.fullmatch(r"\d{1,2}-\d{1,2}", actual_score):
        raise VirtualScoreboardError("actual_score must use the form 2-1")
    goals_a, goals_b = (int(value) for value in actual_score.split("-"))
    normalized = actual_regular_time_result.casefold()
    if normalized == "draw" and goals_a != goals_b:
        raise VirtualScoreboardError("regular_time_result Draw requires a level actual_score")
    if normalized != "draw" and goals_a == goals_b:
        raise VirtualScoreboardError("a level actual_score requires regular_time_result Draw")


def _ensure_scoreboard(path: Path) -> None:
    if path.exists():
        return
    result = safe_write_csv(path, [], VIRTUAL_RESULT_FIELDS)
    if not result.ok:
        raise VirtualScoreboardError("; ".join(issue.problem for issue in result.issues))


def _row(result: VirtualPickResult) -> dict[str, Any]:
    payload = result.model_dump(mode="json")
    return {field: "" if payload.get(field) is None else payload.get(field, "") for field in VIRTUAL_RESULT_FIELDS}


def load_virtual_results(path: Path = VIRTUAL_RESULTS_PATH) -> list[VirtualPickResult]:
    """Load all validated virtual results oldest first."""
    _ensure_scoreboard(path)
    read = safe_read_csv(path, VIRTUAL_RESULT_FIELDS)
    critical = [issue.problem for issue in read.issues if issue.severity.value in {"error", "critical"}]
    if critical:
        raise VirtualScoreboardError("; ".join(critical))
    results = []
    for row in read.rows:
        try:
            results.append(
                VirtualPickResult.model_validate(
                    {
                        **row,
                        "qualification_pick": row.get("qualification_pick") or None,
                        "actual_qualification_result": row.get("actual_qualification_result") or None,
                        "winner_points": int(row["winner_points"]),
                        "score_points": int(row["score_points"]),
                        "qualification_points": int(row["qualification_points"]),
                        "upset_bonus": int(row["upset_bonus"]),
                        "confidence_penalty": int(row["confidence_penalty"]),
                        "total_points": int(row["total_points"]),
                        "confidence": float(row["confidence"]),
                    }
                )
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise VirtualScoreboardError(
                f"Invalid virtual result row {row.get('result_id', '<unknown>')}: {exc}"
            ) from exc
    return results


def _load_results(path: Path = VIRTUAL_RESULTS_PATH) -> list[VirtualPickResult]:
    return load_virtual_results(path)


def settle_virtual_pick(
    prediction: PredictionRecord,
    *,
    actual_regular_time_result: str,
    actual_score: str,
    actual_qualification_result: str | None = None,
    is_upset_pick: bool = False,
    actual_upset: bool = False,
    settled_at: datetime | None = None,
    path: Path = VIRTUAL_RESULTS_PATH,
) -> VirtualPickResult:
    """Settle one prediction using virtual points only; repeated settlement is idempotent."""
    _validate_actual_result(actual_score, actual_regular_time_result)
    existing = next((row for row in _load_results(path) if row.prediction_id == prediction.prediction_id), None)
    if existing is not None:
        return existing

    result_correct = prediction.regular_time_pick.casefold() == actual_regular_time_result.casefold()
    score_correct = prediction.regular_time_score == actual_score
    qualification_correct = (
        prediction.qualification_pick is not None
        and actual_qualification_result is not None
        and prediction.qualification_pick.casefold() == actual_qualification_result.casefold()
    )
    winner_points = 3 if result_correct else 0
    score_points = 5 if score_correct else 0
    qualification_points = 2 if qualification_correct else 0
    upset_bonus = 2 if is_upset_pick and actual_upset and result_correct else 0
    confidence_penalty = -1 if not result_correct and prediction.confidence > 0.65 else 0
    result = VirtualPickResult(
        result_id=uuid4().hex,
        prediction_id=prediction.prediction_id,
        match_id=prediction.match_id,
        agent_name=prediction.agent_name,
        regular_time_pick=prediction.regular_time_pick,
        actual_regular_time_result=actual_regular_time_result,
        qualification_pick=prediction.qualification_pick,
        actual_qualification_result=actual_qualification_result,
        score_pick=prediction.regular_time_score,
        actual_score=actual_score,
        winner_points=winner_points,
        score_points=score_points,
        qualification_points=qualification_points,
        upset_bonus=upset_bonus,
        confidence_penalty=confidence_penalty,
        total_points=winner_points + score_points + qualification_points + upset_bonus + confidence_penalty,
        confidence=prediction.confidence,
        settled_at=settled_at or datetime.now(timezone.utc),
    )
    written = safe_write_csv(path, [_row(result)], VIRTUAL_RESULT_FIELDS, append=True)
    if not written.ok:
        raise VirtualScoreboardError("; ".join(issue.problem for issue in written.issues))
    return result


def _record_priority(record: PredictionRecord) -> tuple[int, int, datetime]:
    published_status = record.status.value in {"locked", "published", "settled", "evaluated"}
    return int(published_status), record.version, record.created_at


def select_match_predictions(
    match_id: str,
    *,
    prediction_paths: list[Path] | None = None,
) -> list[PredictionRecord]:
    """Select one latest public-ready record per agent for a match."""
    paths = prediction_paths or [PRE_MATCH_PREDICTIONS_PATH, MODEL_PREDICTIONS_PATH]
    records = [
        record
        for path in paths
        for record in load_predictions(path)
        if record.match_id == match_id
    ]
    selected: dict[str, PredictionRecord] = {}
    for record in records:
        existing = selected.get(record.agent_name)
        if existing is None or _record_priority(record) > _record_priority(existing):
            selected[record.agent_name] = record
    return sorted(selected.values(), key=lambda record: record.agent_name)


def _base_model_pick(records: list[PredictionRecord]) -> str | None:
    base = next((record for record in records if record.agent_name == "Base Model"), None)
    return base.regular_time_pick if base else None


def _is_upset_call(record: PredictionRecord, base_pick: str | None) -> bool:
    if base_pick:
        return (
            record.regular_time_pick.casefold() != base_pick.casefold()
            and record.regular_time_pick.casefold() != "draw"
        )
    return record.agent_name == "Upset Agent"


def settle_match_predictions(
    match_id: str,
    *,
    actual_score: str,
    actual_regular_time_result: str,
    actual_qualification_result: str | None = None,
    prediction_paths: list[Path] | None = None,
    results_path: Path = VIRTUAL_RESULTS_PATH,
    settled_at: datetime | None = None,
) -> list[VirtualPickResult]:
    """Settle one latest record per agent without counting the same match twice."""
    _validate_actual_result(actual_score, actual_regular_time_result)
    records = select_match_predictions(match_id, prediction_paths=prediction_paths)
    if not records:
        raise VirtualScoreboardError(f"No saved predictions exist for match {match_id!r}.")

    existing_by_agent = {
        result.agent_name: result
        for result in load_virtual_results(results_path)
        if result.match_id == match_id
    }
    base_pick = _base_model_pick(records)
    actual_upset = bool(base_pick and actual_regular_time_result.casefold() != base_pick.casefold())
    results = []
    for record in records:
        existing = existing_by_agent.get(record.agent_name)
        if existing is not None:
            results.append(existing)
            continue
        is_upset_call = _is_upset_call(record, base_pick)
        results.append(
            settle_virtual_pick(
                record,
                actual_regular_time_result=actual_regular_time_result,
                actual_score=actual_score,
                actual_qualification_result=actual_qualification_result,
                is_upset_pick=is_upset_call,
                actual_upset=actual_upset or (base_pick is None and is_upset_call),
                settled_at=settled_at,
                path=results_path,
            )
        )
    return results


def compute_leaderboard(path: Path = VIRTUAL_RESULTS_PATH) -> list[LeaderboardEntry]:
    """Aggregate virtual points and basic calibration warnings by agent."""
    latest_by_agent_match: dict[tuple[str, str], VirtualPickResult] = {}
    for result in _load_results(path):
        key = result.agent_name, result.match_id
        existing = latest_by_agent_match.get(key)
        if existing is None or result.settled_at > existing.settled_at:
            latest_by_agent_match[key] = result
    grouped: defaultdict[str, list[VirtualPickResult]] = defaultdict(list)
    for result in latest_by_agent_match.values():
        grouped[result.agent_name].append(result)

    leaderboard = []
    for agent_name, results in grouped.items():
        winner_hits = sum(result.winner_points > 0 for result in results)
        qualification_rows = [
            result
            for result in results
            if result.qualification_pick is not None and result.actual_qualification_result is not None
        ]
        qualification_hits = sum(result.qualification_points > 0 for result in qualification_rows)
        average_confidence = sum(result.confidence for result in results) / len(results)
        winner_accuracy = winner_hits / len(results)
        warning = None
        if len(results) >= 3 and average_confidence - winner_accuracy > 0.2:
            warning = "overconfident"
        leaderboard.append(
            LeaderboardEntry(
                agent_name=agent_name,
                matches_predicted=len(results),
                total_points=sum(result.total_points for result in results),
                winner_accuracy=round(winner_accuracy, 3),
                exact_score_hits=sum(result.score_points > 0 for result in results),
                qualification_accuracy=(
                    round(qualification_hits / len(qualification_rows), 3) if qualification_rows else None
                ),
                average_confidence=round(average_confidence, 3),
                calibration_warning=warning,
            )
        )
    return sorted(leaderboard, key=lambda row: (-row.total_points, row.agent_name))


def evaluate_arena_predictions(path: Path = VIRTUAL_RESULTS_PATH) -> dict[str, Any]:
    """Return a compact entertainment-only scoring summary."""
    results = load_virtual_results(path)
    leaderboard = compute_leaderboard(path)
    return {
        "matches_settled": len({result.match_id for result in results}),
        "predictions_scored": len(results),
        "leaderboard": [row.model_dump(mode="json") for row in leaderboard],
        "scoring_rules": {
            "correct_regular_time_result": 3,
            "correct_exact_score": 5,
            "correct_qualification": 2,
            "correct_upset_call_bonus": 2,
            "wrong_high_confidence_pick": -1,
        },
        "disclaimer": "Entertainment-only virtual points for comparing prediction methods.",
    }


__all__ = [
    "VIRTUAL_RESULTS_PATH",
    "VirtualScoreboardError",
    "compute_leaderboard",
    "evaluate_arena_predictions",
    "load_virtual_results",
    "select_match_predictions",
    "settle_match_predictions",
    "settle_virtual_pick",
]
