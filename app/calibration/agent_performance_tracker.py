"""Aggregate Prediction Arena calibration and write reviewable CSV reports."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from app.calibration.prediction_target_calibration import (
    PredictionTargetCalibrationReport,
    analyze_prediction_target_calibration,
)
from app.calibration.scoreline_calibration import (
    ScorelineBiasReport,
    analyze_scoreline_calibration,
)
from app.calibration.upset_calibration import UpsetBiasReport, analyze_upset_calibration
from app.ingestion.normalizers import safe_write_csv
from app.prediction_arena.public_ledger import PRE_MATCH_PREDICTIONS_PATH, load_predictions
from app.prediction_arena.schemas import PredictionRecord, StrictModel, VirtualPickResult
from app.prediction_arena.virtual_scoreboard import (
    MODEL_PREDICTIONS_PATH,
    VIRTUAL_RESULTS_PATH,
    compute_leaderboard,
    load_virtual_results,
)


ROOT = Path(__file__).resolve().parents[2]
CALIBRATION_DIR = ROOT / "data" / "prediction_arena" / "calibration"
SCORELINE_REPORT_PATH = CALIBRATION_DIR / "scoreline_bias_report.csv"
UPSET_REPORT_PATH = CALIBRATION_DIR / "upset_bias_report.csv"
AGENT_PERFORMANCE_PATH = CALIBRATION_DIR / "agent_performance.csv"


class AgentPerformanceReport(StrictModel):
    agent_name: str = Field(min_length=1)
    matches_predicted: int = Field(ge=0)
    total_points: int
    winner_accuracy: float = Field(ge=0, le=1)
    exact_score_hits: int = Field(ge=0)
    qualification_accuracy: float | None = Field(default=None, ge=0, le=1)
    average_confidence: float = Field(ge=0, le=1)
    underdog_pick_rate: float | None = Field(default=None, ge=0, le=1)
    average_underdog_path_quality: float | None = Field(default=None, ge=0, le=1)
    target_confusion_count: int = Field(ge=0)
    missing_penalty_probability_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)


SCORELINE_FIELDS = list(ScorelineBiasReport.model_fields)
UPSET_FIELDS = list(UpsetBiasReport.model_fields)
PERFORMANCE_FIELDS = list(AgentPerformanceReport.model_fields)


def _unique_latest_predictions(paths: list[Path]) -> list[PredictionRecord]:
    selected: dict[tuple[str, str], PredictionRecord] = {}
    for path in paths:
        for prediction in load_predictions(path):
            key = prediction.agent_name, prediction.match_id
            existing = selected.get(key)
            current_priority = (
                prediction.status.value in {"locked", "published", "settled", "evaluated"},
                prediction.version,
                prediction.created_at,
            )
            existing_priority = (
                existing.status.value in {"locked", "published", "settled", "evaluated"},
                existing.version,
                existing.created_at,
            ) if existing else None
            if existing is None or current_priority > existing_priority:
                selected[key] = prediction
    return sorted(selected.values(), key=lambda row: (row.agent_name, row.match_id))


def _json_row(model: StrictModel, fields: list[str]) -> dict[str, object]:
    payload = model.model_dump(mode="json")
    for field in fields:
        if isinstance(payload.get(field), list):
            payload[field] = json.dumps(payload[field], ensure_ascii=True)
    return {field: "" if payload.get(field) is None else payload.get(field, "") for field in fields}


def build_agent_performance_reports(
    results: list[VirtualPickResult],
    scoreline_reports: list[ScorelineBiasReport],
    upset_reports: list[UpsetBiasReport],
    target_reports: list[PredictionTargetCalibrationReport],
    *,
    results_path: Path | None = None,
) -> list[AgentPerformanceReport]:
    leaderboard = compute_leaderboard(results_path) if results_path else []
    if not leaderboard and results:
        raise ValueError("results_path is required when in-memory results are supplied")
    scoreline_by_agent = {report.agent_name: report for report in scoreline_reports}
    upset_by_agent = {report.agent_name: report for report in upset_reports}
    target_by_agent = {report.agent_name: report for report in target_reports}
    reports = []
    for row in leaderboard:
        scoreline = scoreline_by_agent.get(row.agent_name)
        upset = upset_by_agent.get(row.agent_name)
        target = target_by_agent.get(row.agent_name)
        warnings = []
        if scoreline and scoreline.underpredicts_three_plus and scoreline.overpredicted_scorelines:
            warnings.append("too_conservative")
        if upset and upset.never_picks_underdogs:
            warnings.append("too_favorite_biased")
        if upset and upset.overpicks_underdogs:
            warnings.append("too_upset_happy")
        if row.calibration_warning == "overconfident" or (
            scoreline and scoreline.exact_score_confidence_too_high
        ):
            warnings.append("overconfident")
        if target and (target.target_confusion_count or target.missing_penalty_probability_count):
            warnings.append("target_confusion")
        reports.append(
            AgentPerformanceReport(
                agent_name=row.agent_name,
                matches_predicted=row.matches_predicted,
                total_points=row.total_points,
                winner_accuracy=row.winner_accuracy,
                exact_score_hits=row.exact_score_hits,
                qualification_accuracy=row.qualification_accuracy,
                average_confidence=row.average_confidence,
                underdog_pick_rate=upset.underdog_pick_rate if upset else None,
                average_underdog_path_quality=upset.average_underdog_path_quality if upset else None,
                target_confusion_count=target.target_confusion_count if target else 0,
                missing_penalty_probability_count=(
                    target.missing_penalty_probability_count if target else 0
                ),
                warnings=list(dict.fromkeys(warnings)),
            )
        )
    return reports


def run_prediction_calibration(
    *,
    prediction_paths: list[Path] | None = None,
    results_path: Path = VIRTUAL_RESULTS_PATH,
    scoreline_path: Path = SCORELINE_REPORT_PATH,
    upset_path: Path = UPSET_REPORT_PATH,
    performance_path: Path = AGENT_PERFORMANCE_PATH,
) -> dict[str, list]:
    """Build and atomically replace all three calibration reports."""
    predictions = _unique_latest_predictions(
        prediction_paths or [PRE_MATCH_PREDICTIONS_PATH, MODEL_PREDICTIONS_PATH]
    )
    results = load_virtual_results(results_path)
    scoreline = analyze_scoreline_calibration(results)
    upset = analyze_upset_calibration(predictions, results)
    target = analyze_prediction_target_calibration(predictions)
    performance = build_agent_performance_reports(
        results,
        scoreline,
        upset,
        target,
        results_path=results_path,
    )
    writes = [
        safe_write_csv(scoreline_path, [_json_row(row, SCORELINE_FIELDS) for row in scoreline], SCORELINE_FIELDS),
        safe_write_csv(upset_path, [_json_row(row, UPSET_FIELDS) for row in upset], UPSET_FIELDS),
        safe_write_csv(
            performance_path,
            [_json_row(row, PERFORMANCE_FIELDS) for row in performance],
            PERFORMANCE_FIELDS,
        ),
    ]
    problems = [issue.problem for write in writes for issue in write.issues if not write.ok]
    if problems:
        raise ValueError("; ".join(problems))
    return {
        "scoreline_bias": scoreline,
        "upset_bias": upset,
        "target_calibration": target,
        "agent_performance": performance,
    }


__all__ = [
    "AGENT_PERFORMANCE_PATH",
    "SCORELINE_REPORT_PATH",
    "UPSET_REPORT_PATH",
    "AgentPerformanceReport",
    "build_agent_performance_reports",
    "run_prediction_calibration",
]
