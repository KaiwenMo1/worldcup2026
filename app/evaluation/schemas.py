"""Typed, explainable contracts for the post-match feedback loop."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evaluated_at must include a timezone")
    return value


class EvaluationStatus(StrEnum):
    EVALUATED = "evaluated"
    PARTIAL = "partial"
    NOT_EVALUABLE = "not_evaluable"


class CompletedMatch(StrictModel):
    match_id: str = Field(min_length=1)
    team_a: str = Field(min_length=1)
    team_b: str = Field(min_length=1)
    team_a_score: int = Field(ge=0, le=30)
    team_b_score: int = Field(ge=0, le=30)
    source: str = "live_state.json"

    @model_validator(mode="after")
    def validate_teams(self) -> "CompletedMatch":
        if self.team_a.casefold() == self.team_b.casefold():
            raise ValueError("completed match teams must be different")
        return self


class ModelPredictionSnapshot(StrictModel):
    match_id: str = Field(min_length=1)
    team_a: str = Field(min_length=1)
    team_b: str = Field(min_length=1)
    predicted_team_a_score: int = Field(ge=0, le=30)
    predicted_team_b_score: int = Field(ge=0, le=30)
    team_a_win_probability: float = Field(ge=0, le=1)
    draw_probability: float = Field(ge=0, le=1)
    team_b_win_probability: float = Field(ge=0, le=1)
    model_version: str = Field(min_length=1)
    prediction_source: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_probabilities(self) -> "ModelPredictionSnapshot":
        total = self.team_a_win_probability + self.draw_probability + self.team_b_win_probability
        if abs(total - 1.0) > 0.001:
            raise ValueError("model result probabilities must sum to 1")
        return self


class PostmatchModelEvaluation(StrictModel):
    evaluation_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    match_id: str
    team_a: str
    team_b: str
    predicted_team_a_score: int = Field(ge=0)
    predicted_team_b_score: int = Field(ge=0)
    actual_team_a_score: int = Field(ge=0)
    actual_team_b_score: int = Field(ge=0)
    predicted_outcome: str
    actual_outcome: str
    exact_score_hit: bool
    winner_hit: bool
    team_a_win_probability: float = Field(ge=0, le=1)
    draw_probability: float = Field(ge=0, le=1)
    team_b_win_probability: float = Field(ge=0, le=1)
    predicted_outcome_confidence: float = Field(ge=0, le=1)
    brier_score: float = Field(ge=0, le=2)
    calibration_bucket: str
    model_version: str
    prediction_source: str
    status: EvaluationStatus
    explanation: str
    evaluated_at: datetime

    _evaluated_at_aware = field_validator("evaluated_at")(_aware)


class ManagerSkillEvaluation(StrictModel):
    evaluation_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    match_id: str
    team: str
    opponent: str
    manager_id: str | None = None
    manager_name: str | None = None
    expected_formation: str | None = None
    actual_formation: str | None = None
    formation_hit: bool | None = None
    pressing_expectation: str | None = None
    actual_pressing_proxy: float | None = Field(default=None, ge=0, le=100)
    pressing_hit: bool | None = None
    transition_expected: bool | None = None
    actual_transition_xg: float | None = Field(default=None, ge=0)
    transition_hit: bool | None = None
    substitution_patterns_expected: int = Field(ge=0)
    actual_substitution_count: int | None = Field(default=None, ge=0)
    substitution_hit: bool | None = None
    component_score: float | None = Field(default=None, ge=0, le=1)
    evaluated_components: int = Field(ge=0, le=4)
    status: EvaluationStatus
    evidence_confidence: float = Field(ge=0, le=1)
    data_quality: str
    explanation: str
    evaluated_at: datetime

    _evaluated_at_aware = field_validator("evaluated_at")(_aware)


class MatchupEvaluation(StrictModel):
    evaluation_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    match_id: str
    matchup_type: str
    team_a: str
    team_b: str
    team_a_player: str | None = None
    team_b_player: str | None = None
    predicted_favored_team: str | None = None
    observed_favored_team: str | None = None
    edge_score: float = Field(ge=0, le=1)
    observed_edge: float | None = Field(default=None, ge=-1, le=1)
    edge_confirmed: bool | None = None
    evidence_metric: str
    team_a_evidence: float | None = None
    team_b_evidence: float | None = None
    status: EvaluationStatus
    explanation: str
    data_quality: str
    evaluated_at: datetime

    _evaluated_at_aware = field_validator("evaluated_at")(_aware)


class AnalystEvaluation(StrictModel):
    evaluation_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    match_id: str
    log_id: str
    analyst: str
    team_a: str
    team_b: str
    predicted_team_a_score: int = Field(ge=0)
    predicted_team_b_score: int = Field(ge=0)
    actual_team_a_score: int = Field(ge=0)
    actual_team_b_score: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    winner_hit: bool
    exact_score_hit: bool
    key_matchup_correct: bool | None = None
    tactical_correct: bool | None = None
    status: EvaluationStatus
    explanation: str
    evaluated_at: datetime

    _evaluated_at_aware = field_validator("evaluated_at")(_aware)


class CompletedMatchEvaluation(StrictModel):
    completed_match: CompletedMatch
    model: PostmatchModelEvaluation
    managers: list[ManagerSkillEvaluation] = Field(default_factory=list)
    matchups: list[MatchupEvaluation] = Field(default_factory=list)
    analysts: list[AnalystEvaluation] = Field(default_factory=list)
