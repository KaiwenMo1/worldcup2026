"""Typed contracts for the entertainment-only Prediction Arena."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ENTERTAINMENT_DISCLAIMER = "This is a technical/entertainment prediction, not betting advice."


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PredictionStage(StrEnum):
    GROUP = "group"
    KNOCKOUT = "knockout"


class PredictionStatus(StrEnum):
    DRAFT = "draft"
    LOCKED = "locked"
    PUBLISHED = "published"
    SETTLED = "settled"
    EVALUATED = "evaluated"


class TargetPick(StrictModel):
    pick: str = Field(min_length=1)
    score: str | None = Field(default=None, pattern=r"^\d{1,2}-\d{1,2}$")
    confidence: float = Field(ge=0, le=1)


class PredictionTarget(StrictModel):
    regular_time_90: TargetPick
    after_extra_time: TargetPick | None = None
    qualification: TargetPick | None = None
    penalty_shootout_probability: float | None = Field(default=None, ge=0, le=1)
    exact_score_candidates: list[TargetPick] = Field(default_factory=list, max_length=8)


class AgentPrediction(StrictModel):
    agent_name: str = Field(min_length=1)
    match_id: str = Field(min_length=1)
    team_a: str = Field(min_length=1)
    team_b: str = Field(min_length=1)
    stage: PredictionStage
    prediction_target: PredictionTarget
    core_reasons: list[str] = Field(default_factory=list, max_length=3)
    fragile_assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    entertainment_disclaimer: str = ENTERTAINMENT_DISCLAIMER

    @model_validator(mode="after")
    def validate_stage_targets(self) -> "AgentPrediction":
        if self.team_a.casefold() == self.team_b.casefold():
            raise ValueError("team_a and team_b must be different")
        if self.stage == PredictionStage.GROUP and any(
            value is not None
            for value in (
                self.prediction_target.after_extra_time,
                self.prediction_target.qualification,
                self.prediction_target.penalty_shootout_probability,
            )
        ):
            raise ValueError("group-stage predictions cannot include extra time, qualification, or penalties")
        if self.stage == PredictionStage.KNOCKOUT and self.prediction_target.qualification is None:
            raise ValueError("knockout predictions must include a qualification target")
        return self


class KevinAgentPrediction(AgentPrediction):
    agent_name: Literal["Kevin Agent"] = "Kevin Agent"
    bold_pick: str = Field(min_length=1)
    core_reason: str = Field(min_length=1)
    one_decisive_matchup: str = Field(min_length=1)
    upset_path: str = Field(min_length=1)
    most_fragile_assumption: str = Field(min_length=1)
    what_would_make_me_wrong: list[str] = Field(min_length=1, max_length=5)
    tone: Literal["bold_but_uncertain"] = "bold_but_uncertain"


class ExpertMatchup(StrictModel):
    matchup: str = Field(min_length=1)
    favored_team: str | None = None
    edge_score: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)


class ExpertAgentPrediction(AgentPrediction):
    agent_name: Literal["Expert Agent"] = "Expert Agent"
    expected_match_shape: str = Field(min_length=1)
    tactical_forecast: dict[str, str] = Field(default_factory=dict)
    key_matchups: list[ExpertMatchup] = Field(default_factory=list)
    execution_risks: list[str] = Field(default_factory=list)


class UpsetAgentPrediction(AgentPrediction):
    agent_name: Literal["Upset Agent"] = "Upset Agent"
    underdog: str = Field(min_length=1)
    upset_path: str = Field(min_length=1)
    required_conditions: list[str] = Field(min_length=1)
    warning_signs: list[str] = Field(default_factory=list)
    upset_probability_adjustment: float = Field(default=0, ge=-0.25, le=0.25)


class ConfidenceDowngrade(StrictModel):
    field: str = Field(min_length=1)
    old_confidence: float = Field(ge=0, le=1)
    new_confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_downgrade(self) -> "ConfidenceDowngrade":
        if self.new_confidence > self.old_confidence:
            raise ValueError("new_confidence must not exceed old_confidence")
        return self


class SkepticReview(StrictModel):
    agent_name: Literal["Skeptic Agent"] = "Skeptic Agent"
    match_id: str = Field(min_length=1)
    unsupported_assumptions: list[str] = Field(default_factory=list)
    fake_precision_warnings: list[str] = Field(default_factory=list)
    cascade_warnings: list[str] = Field(default_factory=list)
    target_confusion_warnings: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    recommended_downgrades: list[ConfidenceDowngrade] = Field(default_factory=list)
    overall_risk_level: Literal["low", "medium", "high"]
    entertainment_disclaimer: str = ENTERTAINMENT_DISCLAIMER


class FinalForecast(StrictModel):
    match_id: str = Field(min_length=1)
    team_a: str = Field(min_length=1)
    team_b: str = Field(min_length=1)
    stage: PredictionStage
    final_prediction: PredictionTarget
    final_confidence: float = Field(ge=0, le=0.75)
    top_reasons: list[str] = Field(min_length=1, max_length=5)
    fragile_assumptions: list[str] = Field(default_factory=list)
    what_to_watch: list[str] = Field(default_factory=list)
    entertainment_disclaimer: str = ENTERTAINMENT_DISCLAIMER

    @model_validator(mode="after")
    def validate_stage_targets(self) -> "FinalForecast":
        if self.team_a.casefold() == self.team_b.casefold():
            raise ValueError("team_a and team_b must be different")
        if self.stage == PredictionStage.GROUP and any(
            value is not None
            for value in (
                self.final_prediction.after_extra_time,
                self.final_prediction.qualification,
                self.final_prediction.penalty_shootout_probability,
            )
        ):
            raise ValueError("group-stage final forecasts cannot include knockout targets")
        if self.stage == PredictionStage.KNOCKOUT and self.final_prediction.qualification is None:
            raise ValueError("knockout final forecasts must include a qualification target")
        return self


class PublicPredictionCard(StrictModel):
    card_id: str = Field(min_length=1)
    prediction_id: str = Field(min_length=1)
    match_id: str = Field(min_length=1)
    team_a: str = Field(min_length=1)
    team_b: str = Field(min_length=1)
    stage: PredictionStage
    final_forecast: FinalForecast
    kevin_take: str = Field(min_length=1)
    expert_view: str = Field(min_length=1)
    upset_path: str = Field(min_length=1)
    published_at: datetime | None = None
    entertainment_disclaimer: str = ENTERTAINMENT_DISCLAIMER

    @field_validator("published_at")
    @classmethod
    def validate_published_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("published_at must include a timezone")
        return value


class PredictionRecord(StrictModel):
    prediction_id: str = Field(pattern=r"^[a-zA-Z0-9_.-]+$")
    version: int = Field(default=1, ge=1)
    match_id: str = Field(min_length=1)
    created_at: datetime
    team_a: str = Field(min_length=1)
    team_b: str = Field(min_length=1)
    stage: PredictionStage
    agent_name: str = Field(min_length=1)
    regular_time_pick: str = Field(min_length=1)
    regular_time_score: str = Field(pattern=r"^\d{1,2}-\d{1,2}$")
    qualification_pick: str | None = None
    penalty_probability: float | None = Field(default=None, ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    core_reason: str = Field(min_length=1)
    fragile_assumptions: list[str] = Field(default_factory=list)
    public_card_path: str | None = None
    status: PredictionStatus = PredictionStatus.DRAFT
    entertainment_disclaimer: str = ENTERTAINMENT_DISCLAIMER

    @field_validator("created_at")
    @classmethod
    def validate_created_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_record_targets(self) -> "PredictionRecord":
        if self.team_a.casefold() == self.team_b.casefold():
            raise ValueError("team_a and team_b must be different")
        if self.stage == PredictionStage.GROUP and (
            self.qualification_pick is not None or self.penalty_probability is not None
        ):
            raise ValueError("group-stage records cannot include qualification or penalty targets")
        if self.stage == PredictionStage.KNOCKOUT and not self.qualification_pick:
            raise ValueError("knockout records must include qualification_pick")
        return self


class VirtualPickResult(StrictModel):
    result_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    prediction_id: str = Field(min_length=1)
    match_id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    regular_time_pick: str = Field(min_length=1)
    actual_regular_time_result: str = Field(min_length=1)
    qualification_pick: str | None = None
    actual_qualification_result: str | None = None
    score_pick: str = Field(pattern=r"^\d{1,2}-\d{1,2}$")
    actual_score: str = Field(pattern=r"^\d{1,2}-\d{1,2}$")
    winner_points: int
    score_points: int
    qualification_points: int
    upset_bonus: int = 0
    confidence_penalty: int = 0
    total_points: int
    confidence: float = Field(ge=0, le=1)
    settled_at: datetime

    @field_validator("settled_at")
    @classmethod
    def validate_settled_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("settled_at must include a timezone")
        return value


class LeaderboardEntry(StrictModel):
    agent_name: str
    matches_predicted: int = Field(ge=0)
    total_points: int
    winner_accuracy: float = Field(ge=0, le=1)
    exact_score_hits: int = Field(ge=0)
    qualification_accuracy: float | None = Field(default=None, ge=0, le=1)
    average_confidence: float = Field(ge=0, le=1)
    calibration_warning: str | None = None
