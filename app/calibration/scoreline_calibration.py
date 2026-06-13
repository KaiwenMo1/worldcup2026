"""Transparent scoreline-bias calibration for Prediction Arena agents."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from pydantic import Field

from app.prediction_arena.schemas import StrictModel, VirtualPickResult


COMMON_SCORELINES = ("0-0", "1-0", "1-1", "2-1")
MIN_WARNING_SAMPLE = 3
RATE_GAP_THRESHOLD = 0.2
EXACT_CONFIDENCE_GAP_THRESHOLD = 0.25


class ScorelineBiasReport(StrictModel):
    agent_name: str = Field(min_length=1)
    settled_predictions: int = Field(ge=0)
    exact_score_hits: int = Field(ge=0)
    exact_score_hit_rate: float = Field(ge=0, le=1)
    average_confidence: float = Field(ge=0, le=1)
    exact_score_confidence_gap: float
    predicted_three_plus_rate: float = Field(ge=0, le=1)
    actual_three_plus_rate: float = Field(ge=0, le=1)
    overpredicted_scorelines: list[str] = Field(default_factory=list)
    underpredicts_three_plus: bool = False
    exact_score_confidence_too_high: bool = False
    warnings: list[str] = Field(default_factory=list)


def _three_plus(score: str) -> bool:
    goals_a, goals_b = (int(value) for value in score.split("-"))
    return goals_a + goals_b >= 3


def _rate(values: Iterable[bool]) -> float:
    rows = list(values)
    return sum(rows) / len(rows) if rows else 0.0


def analyze_scoreline_calibration(results: list[VirtualPickResult]) -> list[ScorelineBiasReport]:
    """Detect common-score bias and exact-score overconfidence."""
    grouped: defaultdict[str, list[VirtualPickResult]] = defaultdict(list)
    for result in results:
        grouped[result.agent_name].append(result)

    reports = []
    for agent_name, rows in sorted(grouped.items()):
        sample = len(rows)
        predicted_three_plus = _rate(_three_plus(row.score_pick) for row in rows)
        actual_three_plus = _rate(_three_plus(row.actual_score) for row in rows)
        exact_hits = sum(row.score_points > 0 for row in rows)
        exact_hit_rate = exact_hits / sample
        average_confidence = sum(row.confidence for row in rows) / sample
        confidence_gap = average_confidence - exact_hit_rate
        overpredicted = []
        if sample >= MIN_WARNING_SAMPLE:
            for score in COMMON_SCORELINES:
                predicted_rate = sum(row.score_pick == score for row in rows) / sample
                actual_rate = sum(row.actual_score == score for row in rows) / sample
                if predicted_rate - actual_rate >= RATE_GAP_THRESHOLD:
                    overpredicted.append(score)
        underpredicts_three_plus = (
            sample >= MIN_WARNING_SAMPLE
            and actual_three_plus - predicted_three_plus >= RATE_GAP_THRESHOLD
        )
        confidence_too_high = (
            sample >= MIN_WARNING_SAMPLE
            and confidence_gap >= EXACT_CONFIDENCE_GAP_THRESHOLD
        )
        warnings = [f"overpredicts_{score.replace('-', '_')}" for score in overpredicted]
        if underpredicts_three_plus:
            warnings.append("underpredicts_three_plus_goal_games")
        if confidence_too_high:
            warnings.append("exact_score_confidence_too_high")
        reports.append(
            ScorelineBiasReport(
                agent_name=agent_name,
                settled_predictions=sample,
                exact_score_hits=exact_hits,
                exact_score_hit_rate=round(exact_hit_rate, 3),
                average_confidence=round(average_confidence, 3),
                exact_score_confidence_gap=round(confidence_gap, 3),
                predicted_three_plus_rate=round(predicted_three_plus, 3),
                actual_three_plus_rate=round(actual_three_plus, 3),
                overpredicted_scorelines=overpredicted,
                underpredicts_three_plus=underpredicts_three_plus,
                exact_score_confidence_too_high=confidence_too_high,
                warnings=warnings,
            )
        )
    return reports


__all__ = ["ScorelineBiasReport", "analyze_scoreline_calibration"]
