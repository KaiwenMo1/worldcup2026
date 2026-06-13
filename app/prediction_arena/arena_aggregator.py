"""Inspectable deterministic aggregation for Prediction Arena agent outputs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.prediction_arena.schemas import (
    ExpertAgentPrediction,
    KevinAgentPrediction,
    PredictionStage,
    SkepticReview,
    StrictModel,
    UpsetAgentPrediction,
)


def _as_dict(value: BaseModel | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return dict(value or {})


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _outcome_probabilities(forecast: dict[str, Any] | None) -> dict[str, float]:
    raw = _as_dict(forecast).get("probabilities") or {}
    values = {
        key: float(raw.get(key) or 0)
        for key in ("team_a_win", "draw", "team_b_win")
    }
    if max(values.values(), default=0) > 1:
        values = {key: value / 100 for key, value in values.items()}
    total = sum(values.values())
    if total <= 0:
        return {"team_a_win": 1 / 3, "draw": 1 / 3, "team_b_win": 1 / 3}
    return {key: value / total for key, value in values.items()}


class ConfidenceAdjustment(StrictModel):
    """One visible reason for changing confidence from the base-model anchor."""

    code: str = Field(min_length=1)
    amount: float = Field(ge=-0.25, le=0.1)
    reason: str = Field(min_length=1)


class ArenaAggregationResult(StrictModel):
    """Decision trace used by the Final Forecast Agent."""

    match_id: str = Field(min_length=1)
    stage: PredictionStage
    base_regular_time_pick: str = Field(min_length=1)
    base_confidence: float = Field(ge=0, le=1)
    regular_time_pick: str = Field(min_length=1)
    qualification_pick: str | None = None
    qualification_confidence: float | None = Field(default=None, ge=0, le=0.75)
    agent_regular_time_picks: dict[str, str]
    expert_kevin_agree: bool
    strong_upset_path: bool
    upset_warning: str | None = None
    calibration_warnings: list[str] = Field(default_factory=list)
    confidence_adjustments: list[ConfidenceAdjustment] = Field(default_factory=list)
    final_confidence: float = Field(ge=0, le=0.75)
    confidence_cap_applied: bool = False


def _unique_text(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _calibration_warning_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return _unique_text([str(item) for item in value.values() if item])
    if isinstance(value, (list, tuple, set)):
        return _unique_text([str(item) for item in value if item])
    return [str(value)]


def _validate_agent_context(
    match_id: str,
    team_a: str,
    team_b: str,
    stage: PredictionStage,
    agents: list[BaseModel],
) -> None:
    for agent in agents:
        if getattr(agent, "match_id", match_id) != match_id:
            raise ValueError(f"{getattr(agent, 'agent_name', 'agent')} match_id does not match")
        if getattr(agent, "team_a", team_a) != team_a or getattr(agent, "team_b", team_b) != team_b:
            raise ValueError(f"{getattr(agent, 'agent_name', 'agent')} teams do not match")
        if getattr(agent, "stage", stage) != stage:
            raise ValueError(f"{getattr(agent, 'agent_name', 'agent')} stage does not match")


def _skeptic_rejects_upset(skeptic: SkepticReview) -> bool:
    explicit_warnings = [
        *skeptic.target_confusion_warnings,
        *skeptic.cascade_warnings,
    ]
    return any("upset agent" in warning.casefold() for warning in explicit_warnings)


def aggregate_prediction_arena(
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
    calibration_warnings: Any = None,
) -> ArenaAggregationResult:
    """Aggregate opinions while keeping the base model as the forecast anchor."""
    stage = PredictionStage(stage)
    _validate_agent_context(match_id, team_a, team_b, stage, [expert, kevin, upset])
    if skeptic.match_id != match_id:
        raise ValueError("Skeptic Agent match_id does not match")

    probabilities = _outcome_probabilities(base_forecast)
    labels = {"team_a_win": team_a, "draw": "Draw", "team_b_win": team_b}
    leading_key = max(probabilities, key=probabilities.get)
    base_pick = labels[leading_key]
    base_confidence = probabilities[leading_key]
    confidence = base_confidence
    adjustments: list[ConfidenceAdjustment] = []

    def adjust(code: str, amount: float, reason: str) -> None:
        nonlocal confidence
        amount = round(amount, 3)
        adjustments.append(ConfidenceAdjustment(code=code, amount=amount, reason=reason))
        confidence += amount

    forecast_payload = _as_dict(base_forecast)
    if not forecast_payload.get("probabilities"):
        adjust("missing_base_probabilities", -0.08, "Base-model match probabilities are unavailable.")

    expert_pick = expert.prediction_target.regular_time_90.pick
    kevin_pick = kevin.prediction_target.regular_time_90.pick
    agree = expert_pick.casefold() == kevin_pick.casefold()
    if agree and expert_pick.casefold() == base_pick.casefold():
        adjust(
            "expert_kevin_base_agreement",
            0.03,
            "Expert and Kevin independently agree with the base-model 90-minute pick.",
        )
    elif agree:
        adjust(
            "agent_consensus_conflicts_with_base",
            -0.04,
            "Expert and Kevin agree with each other but conflict with the base-model anchor.",
        )
    else:
        adjust(
            "expert_kevin_disagreement",
            -0.03,
            "Expert and Kevin disagree on the 90-minute result.",
        )

    strong_upset = len(upset.required_conditions) >= 3 and (
        upset.upset_probability_adjustment >= 0.03 or len(upset.warning_signs) >= 2
    )
    upset_warning = None
    if strong_upset and not _skeptic_rejects_upset(skeptic):
        upset_warning = f"Credible upset path: {upset.upset_path}"
        adjust(
            "credible_upset_path",
            -0.02,
            "The underdog has a coherent conditional path that survives the Skeptic review.",
        )

    if skeptic.target_confusion_warnings:
        adjust("skeptic_target_confusion", -0.06, "Skeptic flagged prediction-target confusion.")
    if skeptic.cascade_warnings:
        adjust(
            "skeptic_unobserved_event_cascade",
            -0.08,
            "Skeptic flagged an unobserved-event cascade.",
        )

    missing_text = " ".join(skeptic.missing_data).casefold()
    if "lineup" in missing_text:
        adjust("missing_lineups", -0.05, "Confirmed or projected lineup data is incomplete.")
    if "injur" in missing_text or "availability" in missing_text:
        adjust("injury_uncertainty", -0.04, "Injury or availability information is uncertain.")
    if skeptic.missing_data and not any(
        token in missing_text for token in ("lineup", "injur", "availability")
    ):
        adjust("other_missing_data", -0.02, "Skeptic identified other material data gaps.")

    warnings = _calibration_warning_text(calibration_warnings)
    if warnings:
        adjust(
            "calibration_warning",
            -min(0.06, 0.02 * len(warnings)),
            "Historical calibration warnings reduce confidence in the probability estimate.",
        )

    uncapped_confidence = _clamp(confidence, 0.15, 1.0)
    final_confidence = round(min(0.75, uncapped_confidence), 3)
    cap_applied = uncapped_confidence > 0.75

    qualification_pick = None
    qualification_confidence = None
    if stage == PredictionStage.KNOCKOUT:
        expert_qualification = expert.prediction_target.qualification
        kevin_qualification = kevin.prediction_target.qualification
        if (
            expert_qualification
            and kevin_qualification
            and expert_qualification.pick.casefold() == kevin_qualification.pick.casefold()
        ):
            qualification_pick = expert_qualification.pick
        else:
            favorite = team_a if probabilities["team_a_win"] >= probabilities["team_b_win"] else team_b
            qualification_pick = f"{favorite} advance"
        favorite_probability = max(probabilities["team_a_win"], probabilities["team_b_win"])
        base_qualification_confidence = _clamp(
            favorite_probability + probabilities["draw"] * 0.35,
            0.35,
            0.74,
        )
        net_adjustment = sum(item.amount for item in adjustments)
        qualification_confidence = round(
            min(0.75, _clamp(base_qualification_confidence + net_adjustment, 0.15, 1.0)),
            3,
        )

    return ArenaAggregationResult(
        match_id=match_id,
        stage=stage,
        base_regular_time_pick=base_pick,
        base_confidence=round(base_confidence, 3),
        regular_time_pick=base_pick,
        qualification_pick=qualification_pick,
        qualification_confidence=qualification_confidence,
        agent_regular_time_picks={
            "Expert Agent": expert_pick,
            "Kevin Agent": kevin_pick,
            "Upset Agent": upset.prediction_target.regular_time_90.pick,
        },
        expert_kevin_agree=agree,
        strong_upset_path=strong_upset,
        upset_warning=upset_warning,
        calibration_warnings=warnings,
        confidence_adjustments=adjustments,
        final_confidence=final_confidence,
        confidence_cap_applied=cap_applied,
    )


__all__ = [
    "ArenaAggregationResult",
    "ConfidenceAdjustment",
    "aggregate_prediction_arena",
]
