"""Deterministic underdog-path analyst for the Prediction Arena."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agents._shared import (
    availability_risks,
    build_prediction_target,
    favorite_and_underdog,
    outcome_probabilities,
    scenario_score,
    tactical_edges,
)
from app.prediction_arena.risk_guardrails import ensure_entertainment_disclaimer
from app.prediction_arena.schemas import PredictionStage, UpsetAgentPrediction


def run_upset_agent(
    match_id: str,
    team_a: str,
    team_b: str,
    stage: PredictionStage | str,
    *,
    forecast: dict[str, Any] | None = None,
    tactical_brief: BaseModel | dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> UpsetAgentPrediction:
    """Construct a plausible underdog path without claiming that it will happen."""
    stage = PredictionStage(stage)
    context = dict(context or {})
    favorite, underdog, _, underdog_probability = favorite_and_underdog(team_a, team_b, forecast)
    edges = tactical_edges(tactical_brief)
    underdog_edges = [edge for edge in edges if edge.get("favored_team") == underdog]
    favorite_risks = [risk for risk in availability_risks(tactical_brief) if risk.get("team") == favorite]
    adjustment = 0.0
    if underdog_edges:
        adjustment += 0.03
    if favorite_risks:
        adjustment += 0.025
    if stage == PredictionStage.KNOCKOUT:
        adjustment += 0.01
    if context.get("weather") not in (None, "", "normal"):
        adjustment += 0.01
    adjustment = round(min(0.1, adjustment), 3)
    confidence = round(max(0.15, min(0.45, underdog_probability + adjustment)), 3)
    score = scenario_score(team_a, underdog)
    qualification_pick = f"{underdog} advance" if stage == PredictionStage.KNOCKOUT else None
    target = build_prediction_target(
        team_a,
        team_b,
        stage,
        forecast,
        regular_pick=underdog,
        regular_score=score,
        regular_confidence=confidence,
        qualification_pick=qualification_pick,
        qualification_confidence=confidence,
    )
    conditions = [
        f"{underdog} avoids conceding first.",
        f"{underdog} creates meaningful threat from set pieces or counterattacks.",
        f"{underdog} keeps the favorite away from its strongest repeated matchup.",
    ]
    if underdog_edges:
        conditions[2] = str(underdog_edges[0].get("reason") or conditions[2])
    warning_signs = [
        f"{favorite} starts with an availability or minutes-limit concern."
        for _ in favorite_risks[:1]
    ]
    if context.get("weather") not in (None, "", "normal"):
        warning_signs.append(f"Weather context ({context['weather']}) may increase match variance.")
    if context.get("favorite_fatigue"):
        warning_signs.append(f"{favorite} carries a fatigue concern.")
    if stage == PredictionStage.KNOCKOUT:
        warning_signs.append("Knockout pressure can reward a compact low-variance game.")
    path = (
        f"{underdog} keeps the game compact, survives the favorite's best route, and turns set pieces, "
        "counterattacks, or goalkeeper variance into the decisive moment."
    )
    result = UpsetAgentPrediction(
        match_id=match_id,
        team_a=team_a,
        team_b=team_b,
        stage=stage,
        prediction_target=target,
        core_reasons=[path, *conditions[:2]][:3],
        fragile_assumptions=[
            f"The upset path depends on {underdog} executing a low-margin plan with little room for error."
        ],
        confidence=confidence,
        underdog=underdog,
        upset_path=path,
        required_conditions=conditions,
        warning_signs=warning_signs,
        upset_probability_adjustment=adjustment,
    )
    return ensure_entertainment_disclaimer(result)
