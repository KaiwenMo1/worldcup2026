"""Deterministic final synthesis for the Prediction Arena."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agents._shared import as_dict, build_prediction_target, outcome_probabilities
from app.prediction_arena.arena_aggregator import (
    ArenaAggregationResult,
    aggregate_prediction_arena,
)
from app.prediction_arena.risk_guardrails import (
    ensure_entertainment_disclaimer,
    reject_betting_advice_language,
)
from app.prediction_arena.schemas import (
    ExpertAgentPrediction,
    FinalForecast,
    KevinAgentPrediction,
    PredictionStage,
    SkepticReview,
    UpsetAgentPrediction,
)


def _unique(values: list[str], limit: int | None = None) -> list[str]:
    result = list(dict.fromkeys(value.strip() for value in values if value and value.strip()))
    return result[:limit] if limit is not None else result


def _base_reason(
    team_a: str,
    team_b: str,
    aggregation: ArenaAggregationResult,
    forecast: dict[str, Any] | None,
) -> str:
    probabilities = outcome_probabilities(forecast)
    pick = aggregation.base_regular_time_pick
    if pick.casefold() == "draw":
        probability = probabilities["draw"]
    elif pick.casefold() == team_a.casefold():
        probability = probabilities["team_a_win"]
    else:
        probability = probabilities["team_b_win"]
    return f"The base model makes {pick} the leading 90-minute outcome at {probability:.1%}."


def _what_to_watch(
    expert: ExpertAgentPrediction,
    kevin: KevinAgentPrediction,
    upset: UpsetAgentPrediction,
    skeptic: SkepticReview,
    tactical_brief: BaseModel | dict[str, Any] | None,
    aggregation: ArenaAggregationResult,
) -> list[str]:
    values = [f"Decisive matchup: {kevin.one_decisive_matchup}."]
    values.extend(
        f"Watch {matchup.matchup}: {matchup.reason}"
        for matchup in expert.key_matchups[:2]
    )
    if aggregation.upset_warning:
        values.extend(f"Upset condition: {condition}" for condition in upset.required_conditions[:2])
    values.extend(f"Data watch: {item}" for item in skeptic.missing_data[:2])
    brief = as_dict(tactical_brief)
    values.extend(
        f"Availability watch: {risk.get('player', 'Player')} for {risk.get('team', 'their team')}."
        for risk in (brief.get("availability_risks") or [])[:1]
        if isinstance(risk, dict)
    )
    return _unique(values, 6)


def run_final_forecast_agent(
    match_id: str,
    team_a: str,
    team_b: str,
    stage: PredictionStage | str,
    *,
    expert: ExpertAgentPrediction,
    kevin: KevinAgentPrediction,
    upset: UpsetAgentPrediction,
    skeptic: SkepticReview,
    base_forecast: dict[str, Any] | None = None,
    tactical_brief: BaseModel | dict[str, Any] | None = None,
    calibration_warnings: Any = None,
) -> FinalForecast:
    """Synthesize the arena while preserving target separation and uncertainty."""
    stage = PredictionStage(stage)
    aggregation = aggregate_prediction_arena(
        match_id,
        team_a,
        team_b,
        stage,
        expert=expert,
        kevin=kevin,
        upset=upset,
        skeptic=skeptic,
        base_forecast=base_forecast,
        calibration_warnings=calibration_warnings,
    )
    final_prediction = build_prediction_target(
        team_a,
        team_b,
        stage,
        base_forecast,
        regular_pick=aggregation.regular_time_pick,
        regular_confidence=aggregation.final_confidence,
        qualification_pick=aggregation.qualification_pick,
        qualification_confidence=aggregation.qualification_confidence,
    )

    reasons = [_base_reason(team_a, team_b, aggregation, base_forecast)]
    reasons.extend(expert.core_reasons[:2])
    if any(item.code == "expert_kevin_base_agreement" for item in aggregation.confidence_adjustments):
        reasons.append("Expert and Kevin independently agree with the base-model result call.")
    if aggregation.upset_warning:
        reasons.append(aggregation.upset_warning)

    fragile = [
        *expert.fragile_assumptions,
        kevin.most_fragile_assumption,
        *upset.fragile_assumptions,
        *(f"Data gap: {item}" for item in skeptic.missing_data),
        *(f"Calibration warning: {item}" for item in aggregation.calibration_warnings),
    ]
    result = FinalForecast(
        match_id=match_id,
        team_a=team_a,
        team_b=team_b,
        stage=stage,
        final_prediction=final_prediction,
        final_confidence=aggregation.final_confidence,
        top_reasons=_unique(reasons, 5),
        fragile_assumptions=_unique(fragile, 8),
        what_to_watch=_what_to_watch(
            expert,
            kevin,
            upset,
            skeptic,
            tactical_brief,
            aggregation,
        ),
    )
    reject_betting_advice_language(result)
    return ensure_entertainment_disclaimer(result)


__all__ = ["run_final_forecast_agent"]
