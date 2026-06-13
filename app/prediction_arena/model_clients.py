"""Optional OpenAI-compatible model clients for a real multi-model Arena."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import requests

from app.prediction_arena.prompt_contracts import ModelArenaOpinion, SYSTEM_PROMPT, build_model_prompt
from app.prediction_arena.risk_guardrails import reject_betting_advice_language
from app.prediction_arena.schemas import PredictionStage


@dataclass(frozen=True)
class ModelClientConfig:
    provider_name: str
    model: str
    base_url: str
    api_key_env: str
    timeout_seconds: int = 45


def configured_model_clients() -> list[ModelClientConfig]:
    """Load model metadata without ever storing API-key values in project files."""
    raw = os.getenv("WORLD_CUP_ARENA_MODELS_JSON", "").strip()
    if not raw:
        return []
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"WORLD_CUP_ARENA_MODELS_JSON is invalid JSON: {exc}") from exc
    return [
        ModelClientConfig(
            provider_name=str(row["provider_name"]),
            model=str(row["model"]),
            base_url=str(row["base_url"]).rstrip("/"),
            api_key_env=str(row["api_key_env"]),
            timeout_seconds=int(row.get("timeout_seconds", 45)),
        )
        for row in rows
    ]


def _json_object(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    if not candidate:
        raise ValueError("Model response did not contain a JSON object")
    return json.loads(candidate)


def run_model_client(
    config: ModelClientConfig,
    *,
    match_id: str,
    team_a: str,
    team_b: str,
    stage: PredictionStage | str,
    forecast: dict[str, Any] | None,
    tactical_brief: dict[str, Any] | None,
) -> ModelArenaOpinion:
    key = os.getenv(config.api_key_env, "").strip()
    if not key:
        raise ValueError(f"{config.api_key_env} is not configured")
    response = requests.post(
        f"{config.base_url}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": config.model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_model_prompt(match_id, team_a, team_b, stage, forecast, tactical_brief),
                },
            ],
        },
        timeout=config.timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    text = str(payload["choices"][0]["message"]["content"])
    parsed = _json_object(text)
    opinion = ModelArenaOpinion(
        provider_name=config.provider_name,
        model=config.model,
        match_id=match_id,
        raw_response=text,
        **parsed,
    )
    reject_betting_advice_language(opinion)
    return opinion


def run_configured_model_arena(
    *,
    match_id: str,
    team_a: str,
    team_b: str,
    stage: PredictionStage | str,
    forecast: dict[str, Any] | None,
    tactical_brief: dict[str, Any] | None,
) -> tuple[list[ModelArenaOpinion], list[str]]:
    opinions = []
    warnings = []
    for config in configured_model_clients():
        try:
            opinions.append(
                run_model_client(
                    config,
                    match_id=match_id,
                    team_a=team_a,
                    team_b=team_b,
                    stage=stage,
                    forecast=forecast,
                    tactical_brief=tactical_brief,
                )
            )
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            warnings.append(f"{config.provider_name}/{config.model} unavailable: {exc}")
    return opinions, warnings


__all__ = [
    "ModelClientConfig",
    "configured_model_clients",
    "run_configured_model_arena",
    "run_model_client",
]
