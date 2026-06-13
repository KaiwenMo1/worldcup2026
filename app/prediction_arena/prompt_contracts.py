"""Strict prompt and response contracts for optional external Arena models."""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field

from app.prediction_arena.schemas import ENTERTAINMENT_DISCLAIMER, PredictionStage, StrictModel


class ModelArenaOpinion(StrictModel):
    provider_name: str = Field(min_length=1)
    model: str = Field(min_length=1)
    match_id: str = Field(min_length=1)
    regular_time_pick: str = Field(min_length=1)
    regular_time_score: str = Field(pattern=r"^\d{1,2}-\d{1,2}$")
    qualification_pick: str | None = None
    confidence: float = Field(ge=0, le=0.75)
    core_reason: str = Field(min_length=1)
    fragile_assumption: str = Field(min_length=1)
    raw_response: str = ""
    entertainment_disclaimer: str = ENTERTAINMENT_DISCLAIMER


SYSTEM_PROMPT = """You are one independent football forecasting analyst.
Return JSON only. Separate the 90-minute result from qualification. Use supplied evidence only.
Do not treat hypothetical events as observed facts. Confidence must be between 0 and 0.75.
This is a technical entertainment forecast and must not contain betting advice."""


def build_model_prompt(
    match_id: str,
    team_a: str,
    team_b: str,
    stage: PredictionStage | str,
    forecast: dict[str, Any] | None,
    tactical_brief: dict[str, Any] | None,
) -> str:
    stage = PredictionStage(stage)
    contract = {
        "regular_time_pick": f"{team_a} | Draw | {team_b}",
        "regular_time_score": "N-N",
        "qualification_pick": f"null for group; {team_a} advance | {team_b} advance for knockout",
        "confidence": "number from 0 to 0.75",
        "core_reason": "one evidence-backed sentence",
        "fragile_assumption": "one sentence explaining what could invalidate the call",
    }
    evidence = {
        "match_id": match_id,
        "team_a": team_a,
        "team_b": team_b,
        "stage": stage.value,
        "base_forecast": forecast or {},
        "tactical_brief": tactical_brief or {},
        "response_contract": contract,
    }
    return json.dumps(evidence, ensure_ascii=True, default=str)


__all__ = ["ModelArenaOpinion", "SYSTEM_PROMPT", "build_model_prompt"]
