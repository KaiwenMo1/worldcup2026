"""Typed contracts for the tournament update agent."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UpdateObservation(StrictModel):
    live_state_exists: bool = False
    live_state_updated_at: str | None = None
    completed_matches: int = 0
    current_matches: int = 0
    live_matches: int = 0
    official_knockout_assignments: int = 0
    event_rows: int = 0
    match_summary_signals: int = 0
    actual_lineup_rows: int = 0
    lineup_delta_signals: int = 0
    player_postmatch_signals: int = 0
    live_player_team_features: int = 0
    manager_observation_rows: int = 0
    formation_prediction_signals: int = 0
    official_snapshot_exists: bool = False
    official_snapshot_match_count: int = 0
    provider_key_configured: bool = False
    event_feed_configured: bool = False
    sportmonks_configured: bool = False
    generated_at: datetime


class AgentToolPlan(StrictModel):
    tool_id: str
    description: str
    will_run: bool
    requires_network: bool = False
    requires_secret: bool = False
    reason: str
    command_preview: list[str] = Field(default_factory=list)


class AgentToolResult(StrictModel):
    tool_id: str
    status: Literal["planned", "skipped", "success", "warning", "failed"]
    started_at: datetime
    finished_at: datetime
    message: str
    metrics: dict[str, Any] = Field(default_factory=dict)


class AgenticUpdateConfig(StrictModel):
    apply: bool = False
    refresh_official: bool = True
    include_provider: bool = False
    include_event_feed: bool = True
    include_lineups: bool = True
    run_arena: bool = False
    verify: bool = False
    allow_subprocess: bool = True
    hours_ahead: int = Field(default=36, ge=1, le=168)
    report_path: str | None = None
    runs_path: str | None = None


class AgenticUpdateReport(StrictModel):
    run_id: str
    mode: Literal["dry_run", "apply"]
    created_at: datetime
    observations_before: UpdateObservation
    plan: list[AgentToolPlan]
    results: list[AgentToolResult]
    observations_after: UpdateObservation | None = None
    warnings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
