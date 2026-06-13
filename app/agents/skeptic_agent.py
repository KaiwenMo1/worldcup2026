"""Deterministic assumption and hallucination audit for Prediction Arena agents."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agents._shared import as_dict, fallback_notes
from app.prediction_arena.risk_guardrails import ensure_entertainment_disclaimer
from app.prediction_arena.schemas import (
    AgentPrediction,
    ConfidenceDowngrade,
    SkepticReview,
)
from app.simulation.hypothetical_event_quarantine import validate_no_unobserved_event_cascade


def _target_confusion(agent: AgentPrediction) -> list[str]:
    target = agent.prediction_target
    if agent.stage.value == "group" and any(
        value is not None
        for value in (target.after_extra_time, target.qualification, target.penalty_shootout_probability)
    ):
        return [f"{agent.agent_name} mixes group-stage and knockout prediction targets."]
    if agent.stage.value == "knockout" and target.qualification is None:
        return [f"{agent.agent_name} does not identify who advances."]
    return []


def run_skeptic_agent(
    match_id: str,
    expert: AgentPrediction,
    kevin: AgentPrediction,
    upset: AgentPrediction,
    *,
    forecast: dict[str, Any] | None = None,
    tactical_brief: BaseModel | dict[str, Any] | None = None,
    simulated_events: list[dict[str, Any]] | None = None,
) -> SkepticReview:
    """Critique agent outputs without producing or changing a final prediction."""
    agents = [expert, kevin, upset]
    unsupported = list(
        dict.fromkeys(
            assumption
            for agent in agents
            for assumption in agent.fragile_assumptions
            if assumption
        )
    )[:6]
    fake_precision = []
    for agent in agents:
        score = agent.prediction_target.regular_time_90.score
        if score and agent.prediction_target.regular_time_90.confidence > 0.25:
            fake_precision.append(
                f"{agent.agent_name}'s exact {score} score is less certain than its broader result call."
            )
    target_warnings = [warning for agent in agents for warning in _target_confusion(agent)]
    missing = fallback_notes(tactical_brief)
    payload = as_dict(forecast)
    if not payload.get("probabilities"):
        missing.append("Base match probabilities are unavailable.")
    if not payload.get("scorelines"):
        missing.append("Exact-score distribution is unavailable.")
    if tactical_brief is None:
        missing.append("Tactical brief is unavailable.")
    cascade = validate_no_unobserved_event_cascade(simulated_events or []).skeptic_warnings
    penalty = min(0.25, 0.03 * len(unsupported) + 0.04 * len(missing) + 0.08 * len(cascade))
    downgrades = [
        ConfidenceDowngrade(
            field=f"{agent.agent_name} confidence",
            old_confidence=agent.confidence,
            new_confidence=round(max(0, agent.confidence - penalty), 3),
            reason="Confidence reduced for fragile assumptions, missing data, or cascade risk.",
        )
        for agent in agents
        if penalty > 0
    ]
    risk_score = len(missing) + len(cascade) * 2 + len(unsupported) + len(fake_precision) // 2
    level = "high" if risk_score >= 6 else "medium" if risk_score >= 2 else "low"
    result = SkepticReview(
        match_id=match_id,
        unsupported_assumptions=unsupported,
        fake_precision_warnings=fake_precision,
        cascade_warnings=cascade,
        target_confusion_warnings=target_warnings,
        missing_data=list(dict.fromkeys(missing)),
        recommended_downgrades=downgrades,
        overall_risk_level=level,
    )
    return ensure_entertainment_disclaimer(result)
