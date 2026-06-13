"""Deterministic evidence-first tactical analyst for the Prediction Arena."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agents._shared import (
    as_dict,
    build_prediction_target,
    fallback_notes,
    outcome_probabilities,
    tactical_edges,
)
from app.prediction_arena.risk_guardrails import ensure_entertainment_disclaimer
from app.prediction_arena.schemas import (
    ExpertAgentPrediction,
    ExpertMatchup,
    PredictionStage,
)


def _match_shape(team_a: str, team_b: str, forecast: dict[str, Any] | None) -> str:
    payload = as_dict(forecast)
    expected = payload.get("expected_score") or {}
    xg_a = float(expected.get("team_a") or 0)
    xg_b = float(expected.get("team_b") or 0)
    if abs(xg_a - xg_b) < 0.25:
        return f"{team_a} and {team_b} project as a low-margin match where the first goal could change the tactical shape."
    stronger = team_a if xg_a > xg_b else team_b
    weaker = team_b if stronger == team_a else team_a
    return f"{stronger} projects the greater chance volume, while {weaker} needs to keep the game compact and protect transitions."


def run_expert_agent(
    match_id: str,
    team_a: str,
    team_b: str,
    stage: PredictionStage | str,
    *,
    forecast: dict[str, Any] | None = None,
    tactical_brief: BaseModel | dict[str, Any] | None = None,
) -> ExpertAgentPrediction:
    """Interpret existing structured evidence without changing the base forecast."""
    stage = PredictionStage(stage)
    brief = as_dict(tactical_brief)
    edges = tactical_edges(tactical_brief)
    matchups = [
        ExpertMatchup(
            matchup=edge.get("matchup_type", "ranked matchup").replace("_", " "),
            favored_team=edge.get("favored_team"),
            edge_score=float(edge.get("edge_score") or 0),
            reason=str(edge.get("reason") or "No matchup explanation is available."),
        )
        for edge in edges[:3]
    ]
    plans = {
        team_a: str((brief.get("manager_plan_a") or {}).get("base_plan") or "plan unavailable"),
        team_b: str((brief.get("manager_plan_b") or {}).get("base_plan") or "plan unavailable"),
    }
    risks = fallback_notes(tactical_brief)[:3]
    risks.extend(
        f"{risk.get('player', 'Player')} availability may weaken {risk.get('team', 'a team')}."
        for risk in (brief.get("availability_risks") or [])[:2]
        if isinstance(risk, dict)
    )
    if not risks:
        risks.append("The projected tactical plans still depend on execution and confirmed lineups.")
    target = build_prediction_target(team_a, team_b, stage, forecast)
    probabilities = outcome_probabilities(forecast)
    confidence = max(probabilities.values())
    if fallback_notes(tactical_brief) or not forecast:
        confidence -= 0.08
    confidence = round(max(0.3, min(0.68, confidence)), 3)
    reasons = []
    if brief.get("tactical_summary"):
        reasons.append(str(brief["tactical_summary"]))
    reasons.extend(matchup.reason for matchup in matchups[:2])
    if not reasons:
        reasons.append("The current call follows the existing match probability and exact-score distribution.")
    fragile = fallback_notes(tactical_brief)[:3] or [
        "Projected lineups and tactical execution remain uncertain before kickoff."
    ]
    result = ExpertAgentPrediction(
        match_id=match_id,
        team_a=team_a,
        team_b=team_b,
        stage=stage,
        prediction_target=target,
        core_reasons=reasons[:3],
        fragile_assumptions=fragile,
        confidence=confidence,
        expected_match_shape=_match_shape(team_a, team_b, forecast),
        tactical_forecast=plans,
        key_matchups=matchups,
        execution_risks=risks[:5],
    )
    return ensure_entertainment_disclaimer(result)
