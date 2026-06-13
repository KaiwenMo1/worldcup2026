"""Underdog-call frequency and path-quality calibration."""

from __future__ import annotations

from collections import defaultdict

from pydantic import Field

from app.prediction_arena.schemas import PredictionRecord, StrictModel, VirtualPickResult


MIN_WARNING_SAMPLE = 3
OVERPICK_RATE = 0.5
PATH_MECHANISMS = (
    "transition",
    "counter",
    "set piece",
    "compact",
    "press",
    "matchup",
    "goalkeeper",
    "fatigue",
    "weather",
)
CONDITIONAL_LANGUAGE = (" if ", " can ", " must ", " depends", " path", " needs ")


class UpsetBiasReport(StrictModel):
    agent_name: str = Field(min_length=1)
    evaluated_predictions: int = Field(ge=0)
    underdog_picks: int = Field(ge=0)
    underdog_pick_rate: float = Field(ge=0, le=1)
    actual_upsets: int = Field(ge=0)
    correct_upset_calls: int = Field(ge=0)
    upset_call_accuracy: float | None = Field(default=None, ge=0, le=1)
    average_underdog_path_quality: float | None = Field(default=None, ge=0, le=1)
    never_picks_underdogs: bool = False
    overpicks_underdogs: bool = False
    warnings: list[str] = Field(default_factory=list)


def score_underdog_path_quality(prediction: PredictionRecord) -> float:
    """Score reasoning structure independently from whether the upset occurs."""
    text = f" {prediction.core_reason.casefold()} "
    score = 0.0
    if len(prediction.core_reason.split()) >= 8:
        score += 0.3
    if prediction.fragile_assumptions:
        score += 0.25
    if any(token in text for token in CONDITIONAL_LANGUAGE):
        score += 0.2
    if any(token in text for token in PATH_MECHANISMS):
        score += 0.25
    return round(min(1.0, score), 3)


def analyze_upset_calibration(
    predictions: list[PredictionRecord],
    results: list[VirtualPickResult],
) -> list[UpsetBiasReport]:
    """Compare agent calls with each match's saved Base Model anchor."""
    predictions_by_id = {prediction.prediction_id: prediction for prediction in predictions}
    results_by_agent: defaultdict[str, list[VirtualPickResult]] = defaultdict(list)
    for result in results:
        results_by_agent[result.agent_name].append(result)
    base_by_match = {
        prediction.match_id: prediction.regular_time_pick
        for prediction in predictions
        if prediction.agent_name == "Base Model"
    }

    reports = []
    for agent_name, rows in sorted(results_by_agent.items()):
        comparable_rows = [row for row in rows if row.match_id in base_by_match]
        underdog_rows = [
            row
            for row in comparable_rows
            if row.regular_time_pick.casefold() != "draw"
            and row.regular_time_pick.casefold() != base_by_match[row.match_id].casefold()
        ]
        quality_scores = [
            score_underdog_path_quality(predictions_by_id[row.prediction_id])
            for row in underdog_rows
            if row.prediction_id in predictions_by_id
        ]
        comparison_sample = len(comparable_rows)
        underdog_rate = len(underdog_rows) / comparison_sample if comparison_sample else 0.0
        actual_upsets = sum(
            row.actual_regular_time_result.casefold() != base_by_match[row.match_id].casefold()
            for row in comparable_rows
        )
        correct_upsets = sum(row.upset_bonus > 0 for row in underdog_rows)
        never = (
            agent_name != "Base Model"
            and comparison_sample >= MIN_WARNING_SAMPLE
            and not underdog_rows
        )
        overpicks = (
            agent_name != "Base Model"
            and comparison_sample >= MIN_WARNING_SAMPLE
            and underdog_rate > OVERPICK_RATE
        )
        warnings = []
        if never:
            warnings.append("never_picks_underdogs")
        if overpicks:
            warnings.append("overpicks_underdogs")
        reports.append(
            UpsetBiasReport(
                agent_name=agent_name,
                evaluated_predictions=len(rows),
                underdog_picks=len(underdog_rows),
                underdog_pick_rate=round(underdog_rate, 3),
                actual_upsets=actual_upsets,
                correct_upset_calls=correct_upsets,
                upset_call_accuracy=(
                    round(correct_upsets / len(underdog_rows), 3) if underdog_rows else None
                ),
                average_underdog_path_quality=(
                    round(sum(quality_scores) / len(quality_scores), 3) if quality_scores else None
                ),
                never_picks_underdogs=never,
                overpicks_underdogs=overpicks,
                warnings=warnings,
            )
        )
    return reports


__all__ = [
    "UpsetBiasReport",
    "analyze_upset_calibration",
    "score_underdog_path_quality",
]
