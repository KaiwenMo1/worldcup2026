"""Run and persist one complete deterministic Prediction Arena forecast."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import Field

from app.agents import (
    run_expert_agent,
    run_final_forecast_agent,
    run_kevin_agent,
    run_skeptic_agent,
    run_upset_agent,
)
from app.agents._shared import build_prediction_target, outcome_probabilities
from app.calibration.agent_performance_tracker import AGENT_PERFORMANCE_PATH
from app.ingestion.normalizers import safe_read_csv
from app.prediction_arena.public_ledger import (
    PRE_MATCH_PREDICTIONS_PATH,
    append_prediction_record,
    load_predictions,
    lock_prediction,
)
from app.prediction_arena.model_clients import run_configured_model_arena
from app.prediction_arena.prompt_contracts import ModelArenaOpinion
from app.prediction_arena.schemas import (
    AgentPrediction,
    ExpertAgentPrediction,
    FinalForecast,
    KevinAgentPrediction,
    PredictionRecord,
    PredictionStage,
    SkepticReview,
    StrictModel,
    UpsetAgentPrediction,
)
from app.tactics.tactical_brief import build_tactical_brief
from app.simulation.game_state_branching import example_game_state_paths


ROOT = Path(__file__).resolve().parents[2]
MODEL_PREDICTIONS_PATH = ROOT / "data" / "prediction_arena" / "ledgers" / "model_predictions.csv"

ForecastProvider = Callable[[str, str], dict[str, Any] | None]
TacticalBriefProvider = Callable[[str, str, str, dict[str, Any] | None], Any]


class PredictionArenaRun(StrictModel):
    """Complete structured output and persistence receipt for one arena run."""

    match_id: str = Field(min_length=1)
    team_a: str = Field(min_length=1)
    team_b: str = Field(min_length=1)
    stage: PredictionStage
    version: int = Field(ge=1)
    base_forecast: dict[str, Any] | None = None
    tactical_brief: dict[str, Any] | None = None
    expert: ExpertAgentPrediction
    kevin: KevinAgentPrediction
    upset: UpsetAgentPrediction
    skeptic: SkepticReview
    final_forecast: FinalForecast
    game_state_paths: list[dict[str, Any]] = Field(default_factory=list)
    calibration_warnings: list[str] = Field(default_factory=list)
    model_opinions: list[ModelArenaOpinion] = Field(default_factory=list)
    prediction_records: list[PredictionRecord] = Field(default_factory=list)
    model_records: list[PredictionRecord] = Field(default_factory=list)
    public_card_path: str | None = None
    fallback_notes: list[str] = Field(default_factory=list)


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip().lower()).strip("-")
    return slug or "prediction"


def _default_forecast_provider(team_a: str, team_b: str) -> dict[str, Any] | None:
    """Use the existing match forecast without making it a hard runner dependency."""
    from app.main import MatchRequest, api_match

    return api_match(MatchRequest(team_a=team_a, team_b=team_b, use_model=True, top_scores=8))


def _default_tactical_brief_provider(
    team_a: str,
    team_b: str,
    match_id: str,
    forecast: dict[str, Any] | None,
) -> Any:
    return build_tactical_brief(team_a, team_b, match_id=match_id, forecast=forecast)


def _available_payload(
    provider: Callable[..., Any],
    *args: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = provider(*args)
        if value is None:
            return None, "Provider returned no data."
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json"), None
        return dict(value), None
    except Exception as exc:  # Provider availability is optional by contract.
        provider_name = getattr(provider, "__name__", type(provider).__name__)
        return None, f"{provider_name} unavailable: {exc}"


def _next_version(match_id: str, paths: list[Path]) -> int:
    versions = [
        record.version
        for path in paths
        for record in load_predictions(path)
        if record.match_id == match_id
    ]
    return max(versions, default=0) + 1


def _prediction_id(match_id: str, agent_name: str, version: int) -> str:
    return f"{_safe_slug(match_id)}-{_safe_slug(agent_name)}-v{version}"


def _record(
    *,
    match_id: str,
    team_a: str,
    team_b: str,
    stage: PredictionStage,
    version: int,
    agent_name: str,
    regular_time_pick: str,
    regular_time_score: str | None,
    qualification_pick: str | None,
    penalty_probability: float | None,
    confidence: float,
    core_reason: str,
    fragile_assumptions: list[str],
    created_at: datetime,
) -> PredictionRecord:
    return PredictionRecord(
        prediction_id=_prediction_id(match_id, agent_name, version),
        version=version,
        match_id=match_id,
        created_at=created_at,
        team_a=team_a,
        team_b=team_b,
        stage=stage,
        agent_name=agent_name,
        regular_time_pick=regular_time_pick,
        regular_time_score=regular_time_score or "1-1",
        qualification_pick=qualification_pick,
        penalty_probability=penalty_probability,
        confidence=confidence,
        core_reason=core_reason,
        fragile_assumptions=fragile_assumptions,
    )


def _agent_record(
    agent: AgentPrediction,
    version: int,
    created_at: datetime,
    *,
    core_reason: str | None = None,
) -> PredictionRecord:
    target = agent.prediction_target
    return _record(
        match_id=agent.match_id,
        team_a=agent.team_a,
        team_b=agent.team_b,
        stage=agent.stage,
        version=version,
        agent_name=agent.agent_name,
        regular_time_pick=target.regular_time_90.pick,
        regular_time_score=target.regular_time_90.score,
        qualification_pick=target.qualification.pick if target.qualification else None,
        penalty_probability=target.penalty_shootout_probability,
        confidence=agent.confidence,
        core_reason=core_reason or (agent.core_reasons[0] if agent.core_reasons else "No main reason available."),
        fragile_assumptions=agent.fragile_assumptions,
        created_at=created_at,
    )


def _final_record(final: FinalForecast, version: int, created_at: datetime) -> PredictionRecord:
    target = final.final_prediction
    return _record(
        match_id=final.match_id,
        team_a=final.team_a,
        team_b=final.team_b,
        stage=final.stage,
        version=version,
        agent_name="Final Forecast Agent",
        regular_time_pick=target.regular_time_90.pick,
        regular_time_score=target.regular_time_90.score,
        qualification_pick=target.qualification.pick if target.qualification else None,
        penalty_probability=target.penalty_shootout_probability,
        confidence=final.final_confidence,
        core_reason=final.top_reasons[0],
        fragile_assumptions=final.fragile_assumptions,
        created_at=created_at,
    )


def _base_model_record(
    match_id: str,
    team_a: str,
    team_b: str,
    stage: PredictionStage,
    version: int,
    forecast: dict[str, Any],
    created_at: datetime,
) -> PredictionRecord:
    target = build_prediction_target(team_a, team_b, stage, forecast)
    probabilities = outcome_probabilities(forecast)
    confidence = max(probabilities.values())
    return _record(
        match_id=match_id,
        team_a=team_a,
        team_b=team_b,
        stage=stage,
        version=version,
        agent_name="Base Model",
        regular_time_pick=target.regular_time_90.pick,
        regular_time_score=target.regular_time_90.score,
        qualification_pick=target.qualification.pick if target.qualification else None,
        penalty_probability=target.penalty_shootout_probability,
        confidence=confidence,
        core_reason="Existing match model probability and exact-score distribution.",
        fragile_assumptions=["The forecast depends on the model and data snapshot available at run time."],
        created_at=created_at,
    )


def _load_calibration_warnings(path: Path = AGENT_PERFORMANCE_PATH) -> list[str]:
    warnings = []
    for row in safe_read_csv(path).rows:
        raw = str(row.get("warnings") or "").strip()
        if not raw:
            continue
        if raw.startswith("["):
            try:
                import json

                values = json.loads(raw)
            except (ValueError, TypeError):
                values = [raw]
        else:
            values = [item.strip() for item in raw.split("|") if item.strip()]
        warnings.extend(f"{row.get('agent_name', 'Agent')}: {value}" for value in values)
    return list(dict.fromkeys(warnings))


def run_prediction_arena(
    match_id: str,
    team_a: str,
    team_b: str,
    stage: PredictionStage | str,
    *,
    lock: bool = False,
    publish_card: bool = False,
    forecast_provider: ForecastProvider | None = None,
    tactical_brief_provider: TacticalBriefProvider | None = None,
    pre_match_path: Path = PRE_MATCH_PREDICTIONS_PATH,
    model_path: Path = MODEL_PREDICTIONS_PATH,
    cards_dir: Path | None = None,
    card_ledger_path: Path | None = None,
) -> PredictionArenaRun:
    """Run all arena agents, append a new version, and optionally lock/publish it."""
    stage = PredictionStage(stage)
    if team_a.casefold() == team_b.casefold():
        raise ValueError("team_a and team_b must be different")

    forecast, forecast_note = _available_payload(
        forecast_provider or _default_forecast_provider,
        team_a,
        team_b,
    )
    brief, brief_note = _available_payload(
        tactical_brief_provider or _default_tactical_brief_provider,
        team_a,
        team_b,
        match_id,
        forecast,
    )
    expert = run_expert_agent(match_id, team_a, team_b, stage, forecast=forecast, tactical_brief=brief)
    kevin = run_kevin_agent(match_id, team_a, team_b, stage, forecast=forecast, tactical_brief=brief)
    upset = run_upset_agent(match_id, team_a, team_b, stage, forecast=forecast, tactical_brief=brief)
    paths = example_game_state_paths(team_a, team_b)
    simulated_events = [
        event.model_dump(mode="json")
        for path in paths
        for event in path.simulated_events
    ]
    skeptic = run_skeptic_agent(
        match_id,
        expert,
        kevin,
        upset,
        forecast=forecast,
        tactical_brief=brief,
        simulated_events=simulated_events,
    )
    calibration_warnings = _load_calibration_warnings()
    model_opinions, model_warnings = run_configured_model_arena(
        match_id=match_id,
        team_a=team_a,
        team_b=team_b,
        stage=stage,
        forecast=forecast,
        tactical_brief=brief,
    )
    final = run_final_forecast_agent(
        match_id,
        team_a,
        team_b,
        stage,
        expert=expert,
        kevin=kevin,
        upset=upset,
        skeptic=skeptic,
        base_forecast=forecast,
        tactical_brief=brief,
        calibration_warnings=calibration_warnings,
    )
    final = final.model_copy(
        update={
            "what_to_watch": list(
                dict.fromkeys(
                    [
                        *final.what_to_watch,
                        *(f"Conditional branch: {path.description}" for path in paths[:3]),
                    ]
                )
            )[:8]
        }
    )

    version = _next_version(match_id, [pre_match_path, model_path])
    created_at = datetime.now(timezone.utc)
    prediction_records = [
        _agent_record(expert, version, created_at, core_reason=expert.expected_match_shape),
        _agent_record(kevin, version, created_at, core_reason=f"{kevin.bold_pick}. {kevin.core_reason}"),
        _agent_record(upset, version, created_at, core_reason=upset.upset_path),
        _final_record(final, version, created_at),
    ]
    model_records = (
        [_base_model_record(match_id, team_a, team_b, stage, version, forecast, created_at)]
        if forecast
        else []
    )

    persisted_predictions = [append_prediction_record(record, pre_match_path) for record in prediction_records]
    persisted_models = [append_prediction_record(record, model_path) for record in model_records]
    if lock:
        persisted_predictions = [lock_prediction(record.prediction_id, pre_match_path) for record in persisted_predictions]
        persisted_models = [lock_prediction(record.prediction_id, model_path) for record in persisted_models]

    fallback_notes = [note for note in (forecast_note, brief_note) if note] + model_warnings
    result = PredictionArenaRun(
        match_id=match_id,
        team_a=team_a,
        team_b=team_b,
        stage=stage,
        version=version,
        base_forecast=forecast,
        tactical_brief=brief,
        expert=expert,
        kevin=kevin,
        upset=upset,
        skeptic=skeptic,
        final_forecast=final,
        game_state_paths=[path.model_dump(mode="json") for path in paths],
        calibration_warnings=calibration_warnings,
        model_opinions=model_opinions,
        prediction_records=persisted_predictions,
        model_records=persisted_models,
        fallback_notes=fallback_notes,
    )
    if publish_card:
        from app.prediction_arena.public_card_renderer import publish_run_card

        path = publish_run_card(
            result,
            cards_dir=cards_dir,
            ledger_path=card_ledger_path,
        )
        result = result.model_copy(update={"public_card_path": str(path)})
    return result


__all__ = [
    "MODEL_PREDICTIONS_PATH",
    "PredictionArenaRun",
    "run_prediction_arena",
]
