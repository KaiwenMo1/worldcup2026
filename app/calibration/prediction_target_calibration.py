"""Audit separation of regular-time and knockout prediction targets."""

from __future__ import annotations

import re
from collections import defaultdict

from pydantic import Field

from app.prediction_arena.schemas import PredictionRecord, PredictionStage, StrictModel


ADVANCEMENT_TERMS = ("advance", "qualif", "progress", "reach the next")


class PredictionTargetCalibrationReport(StrictModel):
    agent_name: str = Field(min_length=1)
    predictions_checked: int = Field(ge=0)
    target_confusion_count: int = Field(ge=0)
    missing_penalty_probability_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)


def prediction_target_issues(prediction: PredictionRecord) -> list[str]:
    """Return target-contract issues without changing the prediction."""
    issues = []
    regular = prediction.regular_time_pick.casefold()
    qualification = (prediction.qualification_pick or "").casefold()
    if any(term in regular for term in ADVANCEMENT_TERMS):
        issues.append("regular_time_pick_uses_qualification_language")
    if prediction.stage == PredictionStage.KNOCKOUT:
        if not prediction.qualification_pick:
            issues.append("knockout_missing_qualification_result")
        elif qualification == "draw" or re.fullmatch(r"\d{1,2}-\d{1,2}", qualification):
            issues.append("qualification_result_uses_regular_time_target")
        if prediction.penalty_probability is None:
            issues.append("knockout_missing_penalty_probability")
    elif prediction.qualification_pick is not None or prediction.penalty_probability is not None:
        issues.append("group_prediction_contains_knockout_target")
    return issues


def analyze_prediction_target_calibration(
    predictions: list[PredictionRecord],
) -> list[PredictionTargetCalibrationReport]:
    grouped: defaultdict[str, list[PredictionRecord]] = defaultdict(list)
    for prediction in predictions:
        grouped[prediction.agent_name].append(prediction)

    reports = []
    for agent_name, rows in sorted(grouped.items()):
        issues = [issue for row in rows for issue in prediction_target_issues(row)]
        confusion = sum(issue != "knockout_missing_penalty_probability" for issue in issues)
        missing_penalty = issues.count("knockout_missing_penalty_probability")
        warnings = []
        if confusion:
            warnings.append("target_confusion")
        if missing_penalty:
            warnings.append("missing_penalty_probability")
        reports.append(
            PredictionTargetCalibrationReport(
                agent_name=agent_name,
                predictions_checked=len(rows),
                target_confusion_count=confusion,
                missing_penalty_probability_count=missing_penalty,
                warnings=warnings,
            )
        )
    return reports


__all__ = [
    "PredictionTargetCalibrationReport",
    "analyze_prediction_target_calibration",
    "prediction_target_issues",
]
