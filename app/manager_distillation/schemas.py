"""Typed contracts for evidence-backed manager-skill distillation."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.tactics.schemas import ConditionCode, DecisionRule, SubstitutionPattern


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceCategory(StrEnum):
    TACTICAL_REPORTS = "tactical_reports"
    PRESS_CONFERENCES = "press_conferences"
    EXPRESSION_DNA = "expression_dna"
    EXTERNAL_VIEWS = "external_views"
    DECISION_RECORDS = "decision_records"
    TIMELINE = "timeline"


class ClaimType(StrEnum):
    TACTICAL_IDENTITY = "tactical_identity"
    PREFERRED_FORMATION = "preferred_formation"
    BUILD_UP_RULE = "build_up_rule"
    DEFENSIVE_SHAPE_RULE = "defensive_shape_rule"
    IN_POSSESSION_RULE = "in_possession_rule"
    OUT_OF_POSSESSION_RULE = "out_of_possession_rule"
    TRANSITION_RULE = "transition_rule"
    PRESSING_TRIGGER = "pressing_trigger"
    SET_PIECE_TENDENCY = "set_piece_tendency"
    SUBSTITUTION_PATTERN = "substitution_pattern"
    GAME_STATE_RULE = "game_state_rule"
    PLAYER_ARCHETYPE_PREFERENCE = "player_archetype_preference"
    ANTI_PATTERN = "anti_pattern"
    EXPRESSION_DNA = "expression_dna"
    TIMELINE_NOTE = "timeline_note"


class EvidenceRecord(StrictModel):
    evidence_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    manager_id: str = Field(pattern=r"^[a-z0-9_]+$")
    category: EvidenceCategory
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str | None = None
    observed_at: date | None = None
    match_id: str | None = None
    claim_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    claim_type: ClaimType
    claim_text: str = Field(min_length=1)
    normalized_value: str | None = None
    condition_code: ConditionCode | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    match_state: Literal["tied", "leading", "trailing"] | None = None
    minute_window: str | None = Field(default=None, pattern=r"^\d{1,3}-\d{1,3}$")
    reliability_score: float = Field(ge=0, le=1)
    predictive_power: bool = False
    distinctive: bool = False
    notes: str | None = None

    @model_validator(mode="after")
    def validate_executable_contract(self) -> "EvidenceRecord":
        if self.condition_code is not None:
            DecisionRule(
                condition_code=self.condition_code,
                parameters=self.parameters,
                recommendation=self.claim_text,
                evidence_confidence=self.reliability_score,
            )
        elif self.parameters:
            raise ValueError("parameters require a supported condition_code")
        if self.claim_type == ClaimType.SUBSTITUTION_PATTERN:
            if not self.match_state or not self.minute_window:
                raise ValueError("substitution_pattern requires match_state and minute_window")
            SubstitutionPattern(
                match_state=self.match_state,
                likely_sub_type=self.normalized_value or self.claim_text,
                minute_window=self.minute_window,
                evidence_confidence=self.reliability_score,
            )
        return self


class EvidenceDocument(StrictModel):
    document_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    category: EvidenceCategory
    title: str = Field(min_length=1)
    path: str = Field(min_length=1)
    content: str = Field(min_length=1)


class DistillationSource(StrictModel):
    source_id: str
    title: str
    url: str | None = None
    observed_at: date | None = None
    categories: list[EvidenceCategory] = Field(default_factory=list)


class ClaimValidation(StrictModel):
    cross_match_recurrence: bool
    predictive_power: bool
    distinctiveness: bool
    distinct_matches: int = Field(ge=0)
    distinct_sources: int = Field(ge=0)
    status: Literal["core", "low_confidence"]
    reason: str


class DistilledClaim(StrictModel):
    claim_id: str
    claim_type: ClaimType
    claim_text: str
    normalized_value: str | None = None
    condition_code: ConditionCode | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    match_state: Literal["tied", "leading", "trailing"] | None = None
    minute_window: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    match_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    validation: ClaimValidation


class DistilledTacticalIdentity(StrictModel):
    primary_style: str
    preferred_formations: list[str] = Field(default_factory=list)
    build_up: str
    defensive_shape: str
    pressing: str
    transition: str
    set_pieces: str


class DistilledManagerSkill(StrictModel):
    manager_id: str = Field(pattern=r"^[a-z0-9_]+$")
    manager_name: str = Field(min_length=1)
    team: str = Field(min_length=1)
    version: str = Field(default="0.1")
    generated_at: datetime
    tactical_identity: DistilledTacticalIdentity
    core_tactical_models: list[DistilledClaim] = Field(default_factory=list)
    decision_heuristics: list[DistilledClaim] = Field(default_factory=list)
    low_confidence_heuristics: list[DistilledClaim] = Field(default_factory=list)
    player_archetype_preferences: list[str] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)
    expression_dna: list[str] = Field(default_factory=list)
    timeline_notes: list[str] = Field(default_factory=list)
    honest_boundaries: list[str] = Field(default_factory=list)
    sources: list[DistillationSource] = Field(default_factory=list)
    evidence_notes: list[str] = Field(default_factory=list)

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        return value


class ValidationCheck(StrictModel):
    name: str
    passed: bool
    severity: Literal["warning", "error"]
    detail: str


class ManagerSkillValidationReport(StrictModel):
    manager_id: str
    status: Literal["PASS", "WARN", "FAIL"]
    checks: list[ValidationCheck]
    core_tactical_models: int = Field(ge=0)
    decision_heuristics: int = Field(ge=0)
    low_confidence_heuristics: int = Field(ge=0)
    source_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
