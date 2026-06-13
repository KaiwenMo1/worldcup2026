"""Deterministic bold-intuition lens for the Prediction Arena."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agents._shared import (
    build_prediction_target,
    fallback_notes,
    favorite_and_underdog,
    tactical_edges,
)
from app.prediction_arena.risk_guardrails import ensure_entertainment_disclaimer
from app.prediction_arena.schemas import KevinAgentPrediction, PredictionStage


def run_kevin_agent(
    match_id: str,
    team_a: str,
    team_b: str,
    stage: PredictionStage | str,
    *,
    forecast: dict[str, Any] | None = None,
    tactical_brief: BaseModel | dict[str, Any] | None = None,
) -> KevinAgentPrediction:
    """Make one decisive, uncertainty-aware call from the same structured inputs."""
    stage = PredictionStage(stage)
    target = build_prediction_target(team_a, team_b, stage, forecast)
    favorite, underdog, _, _ = favorite_and_underdog(team_a, team_b, forecast)
    edges = tactical_edges(tactical_brief)
    decisive = edges[0] if edges else {}
    if decisive.get("team_a_player") or decisive.get("team_b_player"):
        matchup = f"{decisive.get('team_a_player') or team_a} vs {decisive.get('team_b_player') or team_b}"
    elif decisive.get("matchup_type"):
        matchup = str(decisive["matchup_type"]).replace("_", " ")
    else:
        matchup = f"{favorite}'s strongest attacking route vs {underdog}'s defensive response"
    core_reason = str(
        decisive.get("reason")
        or f"{favorite} has the clearest single route to creating the better chances."
    )
    assumptions = list(decisive.get("lineup_assumptions") or []) if decisive else []
    assumptions.extend(fallback_notes(tactical_brief))
    fragile = assumptions[0] if assumptions else "The decisive matchup depends on the projected starters actually playing."
    score = target.regular_time_90.score or "score unavailable"
    bold_pick = f"{team_a} {score} {team_b}"
    confidence = round(max(0.34, min(0.68, target.regular_time_90.confidence + 0.05)), 3)
    wrong = [
        f"{underdog} prevents the decisive matchup from becoming repeatable.",
        f"{underdog} scores first and changes the game state.",
        fragile,
    ]
    result = KevinAgentPrediction(
        match_id=match_id,
        team_a=team_a,
        team_b=team_b,
        stage=stage,
        prediction_target=target,
        core_reasons=[core_reason],
        fragile_assumptions=[fragile],
        confidence=confidence,
        bold_pick=bold_pick,
        core_reason=core_reason,
        one_decisive_matchup=matchup,
        upset_path=(
            f"{underdog} can overturn the call by surviving the first pressure wave, scoring first, "
            "and forcing the favorite away from its preferred route."
        ),
        most_fragile_assumption=fragile,
        what_would_make_me_wrong=wrong[:3],
    )
    return ensure_entertainment_disclaimer(result)
