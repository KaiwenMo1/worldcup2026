"""Typed contracts for the manager-skill tactical subsystem."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConditionCode(StrEnum):
    OPPONENT_HIGH_LINE = "opponent_high_line"
    OPPONENT_HIGH_PRESS = "opponent_high_press"
    OPPONENT_MIDFIELD_CONTROL = "opponent_midfield_control"
    LEADING_AFTER_MINUTE = "leading_after_minute"
    TRAILING_AFTER_MINUTE = "trailing_after_minute"
    TIED_AFTER_MINUTE = "tied_after_minute"
    KNOCKOUT_MATCH = "knockout_match"


class EvidenceReference(StrictModel):
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str | None = None
    observed_at: date | None = None
    note: str | None = None


class MatchContext(StrictModel):
    match_state: Literal["pre_match", "tied", "leading", "trailing"] = "pre_match"
    minute: int = Field(default=0, ge=0, le=130)
    knockout: bool = False
    opponent_high_line: bool | None = None
    opponent_high_press: bool | None = None
    opponent_midfield_control: bool | None = None
    opponent_recovery_defender_score: float | None = Field(default=None, ge=0, le=100)
    opponent_possession_share: float | None = Field(default=None, ge=0, le=1)
    notes: list[str] = Field(default_factory=list)


class TacticalIdentity(StrictModel):
    primary_style: str = Field(min_length=1)
    preferred_formations: list[str] = Field(min_length=1)
    build_up: str = Field(min_length=1)
    defensive_shape: str = Field(min_length=1)
    pressing: str = Field(min_length=1)
    transition: str = Field(min_length=1)
    set_pieces: str = Field(min_length=1)
    in_possession: list[str] = Field(default_factory=list)
    out_of_possession: list[str] = Field(default_factory=list)
    transition_actions: list[str] = Field(default_factory=list)
    set_piece_actions: list[str] = Field(default_factory=list)


class DecisionRule(StrictModel):
    condition_code: ConditionCode
    parameters: dict[str, Any] = Field(default_factory=dict)
    recommendation: str = Field(min_length=1)
    evidence_confidence: float = Field(ge=0, le=1)
    source_refs: list[EvidenceReference] = Field(default_factory=list)
    last_verified: date | None = None
    sample_size: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_condition_parameters(self) -> "DecisionRule":
        allowed_parameters = {
            ConditionCode.OPPONENT_HIGH_LINE: {"recovery_defender_score_max"},
            ConditionCode.OPPONENT_MIDFIELD_CONTROL: {"possession_share_min"},
            ConditionCode.LEADING_AFTER_MINUTE: {"minute"},
            ConditionCode.TRAILING_AFTER_MINUTE: {"minute"},
            ConditionCode.TIED_AFTER_MINUTE: {"minute"},
            ConditionCode.OPPONENT_HIGH_PRESS: set(),
            ConditionCode.KNOCKOUT_MATCH: set(),
        }
        unknown = set(self.parameters) - allowed_parameters[self.condition_code]
        if unknown:
            raise ValueError(f"unsupported parameters for {self.condition_code}: {sorted(unknown)}")

        if self.condition_code in {
            ConditionCode.LEADING_AFTER_MINUTE,
            ConditionCode.TRAILING_AFTER_MINUTE,
            ConditionCode.TIED_AFTER_MINUTE,
        }:
            minute = self.parameters.get("minute")
            if not isinstance(minute, int) or isinstance(minute, bool) or not 0 <= minute <= 130:
                raise ValueError(f"{self.condition_code} requires integer parameter minute between 0 and 130")

        recovery_max = self.parameters.get("recovery_defender_score_max")
        if recovery_max is not None and (
            not isinstance(recovery_max, (int, float))
            or isinstance(recovery_max, bool)
            or not 0 <= recovery_max <= 100
        ):
            raise ValueError("recovery_defender_score_max must be between 0 and 100")

        possession_min = self.parameters.get("possession_share_min")
        if possession_min is not None and (
            not isinstance(possession_min, (int, float))
            or isinstance(possession_min, bool)
            or not 0 <= possession_min <= 1
        ):
            raise ValueError("possession_share_min must be between 0 and 1")
        return self


class SubstitutionPattern(StrictModel):
    match_state: Literal["tied", "leading", "trailing"]
    likely_sub_type: str = Field(min_length=1)
    minute_window: str = Field(pattern=r"^\d{1,3}-\d{1,3}$")
    evidence_confidence: float = Field(default=0.5, ge=0, le=1)
    source_refs: list[EvidenceReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_minute_window(self) -> "SubstitutionPattern":
        start, end = (int(value) for value in self.minute_window.split("-"))
        if start > end or end > 130:
            raise ValueError("minute_window must be ordered and end at or before minute 130")
        return self


class ManagerSkill(StrictModel):
    manager_id: str = Field(pattern=r"^[a-z0-9_]+$")
    manager_name: str = Field(min_length=1)
    team: str = Field(min_length=1)
    skill_name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: Literal["manual_prototype", "evidence_backed", "observed"]
    last_verified: date | None = None
    source_refs: list[EvidenceReference] = Field(default_factory=list)
    tactical_identity: TacticalIdentity
    decision_rules: list[DecisionRule] = Field(default_factory=list)
    substitution_patterns: list[SubstitutionPattern] = Field(default_factory=list)
    evidence_notes: list[str] = Field(default_factory=list)


class RuleEvaluation(StrictModel):
    condition_code: ConditionCode
    recommendation: str
    reason: str
    evidence_confidence: float = Field(ge=0, le=1)
    source_refs: list[EvidenceReference] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class PlanConfidence(StrictModel):
    level: Literal["low", "medium", "high"]
    score: float = Field(ge=0, le=1)
    meaning: str


class ManagerPlan(StrictModel):
    team: str
    opponent: str
    manager_id: str | None
    manager_name: str | None
    base_plan: str
    expected_formation: str | None
    in_possession: list[str] = Field(default_factory=list)
    out_of_possession: list[str] = Field(default_factory=list)
    transition: list[str] = Field(default_factory=list)
    set_pieces: list[str] = Field(default_factory=list)
    applied_rules: list[RuleEvaluation] = Field(default_factory=list)
    contingent_rules: list[DecisionRule] = Field(default_factory=list)
    substitution_patterns: list[SubstitutionPattern] = Field(default_factory=list)
    confidence: PlanConfidence
    source_refs: list[EvidenceReference] = Field(default_factory=list)
    data_quality: str
    fallback_used: bool = False
    fallback_note: str | None = None


class PlayerProfile(StrictModel):
    player_id: str = Field(pattern=r"^[a-z0-9_]+$")
    player: str = Field(min_length=1)
    team: str = Field(min_length=1)
    club: str = ""
    primary_position: str = Field(min_length=1)
    secondary_positions: list[str] = Field(default_factory=list)
    preferred_foot: str = "Unknown"
    role_archetypes: list[str] = Field(min_length=1)
    starter_probability: float = Field(ge=0, le=1)
    minutes_projection: int = Field(ge=0, le=130)
    availability_status: str = "unknown"
    pace: float = Field(ge=0, le=100)
    finishing: float = Field(ge=0, le=100)
    passing: float = Field(ge=0, le=100)
    chance_creation: float = Field(ge=0, le=100)
    progression: float = Field(ge=0, le=100)
    dribbling: float = Field(ge=0, le=100)
    crossing: float = Field(ge=0, le=100)
    pressing: float = Field(ge=0, le=100)
    tackling: float = Field(ge=0, le=100)
    aerial: float = Field(ge=0, le=100)
    recovery: float = Field(ge=0, le=100)
    press_resistance: float = Field(ge=0, le=100)
    build_up: float = Field(ge=0, le=100)
    set_piece_delivery: float = Field(ge=0, le=100)
    source: str
    data_quality: str
    updated_at: str | None = None


class PlayerAvailability(StrictModel):
    match_id: str | None = None
    player_id: str = Field(pattern=r"^[a-z0-9_]+$")
    player: str = Field(min_length=1)
    team: str = Field(min_length=1)
    status: str = "unknown"
    availability: float = Field(default=1.0, ge=0, le=1)
    minutes_limit: int = Field(default=90, ge=0, le=130)
    impact_score: float = Field(default=50.0, ge=0)
    source: str
    updated_at: str | None = None


class ProjectedLineupPlayer(StrictModel):
    match_id: str | None = None
    team: str = Field(min_length=1)
    formation: str = Field(min_length=1)
    player_id: str = Field(pattern=r"^[a-z0-9_]+$")
    player: str = Field(min_length=1)
    position_slot: str = Field(min_length=1)
    role: str = Field(min_length=1)
    starter_probability: float = Field(ge=0, le=1)
    source: str
    data_quality: str
    updated_at: str | None = None


class MatchupEdge(StrictModel):
    matchup_type: str
    team_a: str
    team_b: str
    team_a_player: str | None = None
    team_b_player: str | None = None
    favored_team: str | None = None
    edge_score: float = Field(ge=0, le=1)
    edge_label: str
    reason: str
    relevant_features: dict[str, Any] = Field(default_factory=dict)
    lineup_assumptions: list[str] = Field(default_factory=list)
    data_quality: str
    source: str = "transparent_rule_engine"


class TacticalMatchupRequest(StrictModel):
    team_a: str = Field(min_length=1)
    team_b: str = Field(min_length=1)
    match_id: str | None = None
    top_n: int = Field(default=8, ge=1, le=20)


class TacticalBriefRequest(StrictModel):
    team_a: str = Field(default="France", min_length=1)
    team_b: str = Field(default="Brazil", min_length=1)
    match_id: str | None = None
    top_matchups: int = Field(default=5, ge=1, le=12)
    match_context_a: MatchContext | None = None
    match_context_b: MatchContext | None = None
    use_model: bool = True
    top_scores: int = Field(default=5, ge=1, le=20)
    weather: str = "normal"
    travel: int = Field(default=20, ge=0, le=100)
    fatigue: int = Field(default=20, ge=0, le=100)
    home_advantage: float = Field(default=1.0, ge=0.0, le=2.0)
    venue: str | None = None


class TacticalForecastSnapshot(StrictModel):
    available: bool
    expected_score: dict[str, float] | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    most_likely_score: dict[str, Any] | None = None
    source: str
    data_quality: str
    fallback_note: str | None = None


class AvailabilityRisk(StrictModel):
    player_id: str
    player: str
    team: str
    projected_role: str
    starter_probability: float = Field(ge=0, le=1)
    status: str
    availability: float = Field(ge=0, le=1)
    minutes_limit: int = Field(ge=0, le=130)
    impact_score: float = Field(ge=0)
    risk_score: float = Field(ge=0, le=1)
    reason: str
    source: str
    data_quality: str


class TacticalDataCoverage(StrictModel):
    team: str
    manager_registered: bool
    manager_skill_available: bool
    manager_history_matches: int = Field(ge=0)
    manager_data_quality: str
    player_profiles: int = Field(ge=0)
    observed_player_profiles: int = Field(ge=0)
    estimated_player_profiles: int = Field(ge=0)
    player_observed_coverage: float = Field(ge=0, le=1)
    projected_lineup_players: int = Field(ge=0)
    availability_entries: int = Field(ge=0)
    identity_mapped_players: int = Field(ge=0)
    provider_linked_identities: int = Field(ge=0)
    context_feature_gate_enabled: bool
    context_feature_gate_reason: str
    notes: list[str] = Field(default_factory=list)


class TacticalBrief(StrictModel):
    team_a: str
    team_b: str
    forecast: TacticalForecastSnapshot
    manager_plan_a: ManagerPlan
    manager_plan_b: ManagerPlan
    top_matchup_edges: list[MatchupEdge] = Field(default_factory=list)
    availability_risks: list[AvailabilityRisk] = Field(default_factory=list)
    tactical_summary: str
    data_coverage: dict[str, TacticalDataCoverage] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    evidence_confidence: PlanConfidence
    data_quality: str
    fallback_notes: list[str] = Field(default_factory=list)
    probability_boundary_note: str = (
        "The tactical brief explains the existing forecast and does not alter match probabilities or expected goals."
    )


class PredictionLogCreate(StrictModel):
    analyst: str = Field(min_length=1, max_length=120)
    match_id: str | None = None
    team_a: str = Field(min_length=1)
    team_b: str = Field(min_length=1)
    predicted_team_a_score: int = Field(ge=0, le=20)
    predicted_team_b_score: int = Field(ge=0, le=20)
    confidence: float = Field(ge=0, le=1)
    key_matchup_prediction: str | None = Field(default=None, max_length=1000)
    tactical_prediction: str | None = Field(default=None, max_length=2000)
    kickoff_at: datetime
    model_version: str | None = Field(default=None, max_length=160)
    data_snapshot_id: str | None = Field(default=None, max_length=160)

    @field_validator("kickoff_at")
    @classmethod
    def validate_kickoff_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("kickoff_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_distinct_teams(self) -> "PredictionLogCreate":
        if self.team_a.casefold() == self.team_b.casefold():
            raise ValueError("team_a and team_b must be different")
        return self


class PredictionLog(PredictionLogCreate):
    log_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    predicted_winner: str = Field(min_length=1)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_created_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_pre_match_record(self) -> "PredictionLog":
        expected_winner = (
            self.team_a
            if self.predicted_team_a_score > self.predicted_team_b_score
            else self.team_b
            if self.predicted_team_b_score > self.predicted_team_a_score
            else "Draw"
        )
        if self.predicted_winner != expected_winner:
            raise ValueError("predicted_winner does not match the predicted score")
        if self.created_at >= self.kickoff_at:
            raise ValueError("prediction log must have been created before kickoff")
        return self


class PostgameReviewCreate(StrictModel):
    log_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    actual_team_a_score: int = Field(ge=0, le=20)
    actual_team_b_score: int = Field(ge=0, le=20)
    key_matchup_correct: bool | None = None
    tactical_correct: bool | None = None
    notes: str | None = Field(default=None, max_length=4000)


class PostgameReview(PostgameReviewCreate):
    review_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    actual_winner: str = Field(min_length=1)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_created_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value


class AnalystProfile(StrictModel):
    analyst: str
    number_of_predictions: int = Field(ge=0)
    reviewed_predictions: int = Field(ge=0)
    winner_accuracy: float | None = Field(default=None, ge=0, le=100)
    score_exact_accuracy: float | None = Field(default=None, ge=0, le=100)
    average_confidence: float | None = Field(default=None, ge=0, le=1)
    key_matchup_accuracy: float | None = Field(default=None, ge=0, le=100)
    tactical_accuracy: float | None = Field(default=None, ge=0, le=100)
    source: str = "append_only_csv_journal"
    metric_meaning: str = (
        "Accuracy percentages use reviewed predictions only; average confidence uses all predictions."
    )
