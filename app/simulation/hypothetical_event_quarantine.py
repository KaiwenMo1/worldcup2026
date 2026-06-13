"""Quarantine hypothetical match events so imagined branches never become facts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SimulatedEventType(StrEnum):
    YELLOW_CARD = "yellow_card"
    RED_CARD = "red_card"
    PENALTY = "penalty"
    GOALKEEPER_MISTAKE = "goalkeeper_mistake"
    INJURY = "injury"
    GOAL = "goal"
    SUBSTITUTION = "substitution"
    TACTICAL_SWITCH = "tactical_switch"
    OTHER = "other"


class SimulatedEvent(StrictModel):
    event_type: SimulatedEventType | str = Field(min_length=1)
    team: str | None = None
    player: str | None = None
    minute_range: str | None = Field(default=None, pattern=r"^\d{1,3}(?:-\d{1,3})?$")
    probability: float = Field(ge=0, le=1)
    is_observed: bool = False
    allowed_to_cascade: bool = False
    impact_if_occurs: str = Field(min_length=1)
    reasoning_note: str = Field(min_length=1)

    @model_validator(mode="after")
    def quarantine_unobserved_event(self) -> "SimulatedEvent":
        if not self.is_observed and self.allowed_to_cascade:
            raise ValueError("unobserved simulated events cannot be allowed to cascade")
        if self.minute_range and "-" in self.minute_range:
            start, end = (int(value) for value in self.minute_range.split("-"))
            if start > end or end > 130:
                raise ValueError("minute_range must be ordered and end at or before minute 130")
        elif self.minute_range and int(self.minute_range) > 130:
            raise ValueError("minute_range must end at or before minute 130")
        return self


class CascadeValidationResult(StrictModel):
    valid: bool
    skeptic_warnings: list[str] = Field(default_factory=list)
    quarantined_events: list[str] = Field(default_factory=list)
    boundary_note: str = (
        "Unobserved simulated events are conditional branches, not facts, and cannot modify the main prediction."
    )


def _is_event_mapping(value: dict[str, Any]) -> bool:
    return "event_type" in value and any(
        key in value for key in ("is_observed", "allowed_to_cascade", "probability", "impact_if_occurs")
    )


def validate_no_unobserved_event_cascade(prediction_obj: Any) -> CascadeValidationResult:
    """Recursively audit raw or typed prediction objects for hypothetical-event leakage."""
    warnings: list[str] = []
    quarantined: list[str] = []

    def walk(value: Any, path: str, inside_branch: bool = False) -> None:
        if isinstance(value, BaseModel):
            branch = value.__class__.__name__ == "GameStatePath"
            walk(value.model_dump(mode="json"), path, inside_branch or branch)
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]", inside_branch)
            return
        if not isinstance(value, dict):
            return

        branch = inside_branch or (
            {"path_id", "description", "probability", "simulated_events"}.issubset(value)
        )
        if _is_event_mapping(value):
            event_type = str(value.get("event_type") or "unknown")
            observed = bool(value.get("is_observed", False))
            cascade = bool(value.get("allowed_to_cascade", False))
            if not observed:
                quarantined.append(event_type)
                if cascade:
                    warnings.append(
                        f"Unobserved simulated event {event_type} at {path} is incorrectly allowed to cascade."
                    )
                if not branch:
                    warnings.append(
                        f"Unobserved simulated event {event_type} at {path} appears outside an explicit GameStatePath "
                        "and may be treated as fact."
                    )

        for key, item in value.items():
            child_branch = branch or key in {"branches", "game_state_paths"}
            walk(item, f"{path}.{key}", child_branch)

    walk(prediction_obj, "$")
    unique_warnings = list(dict.fromkeys(warnings))
    return CascadeValidationResult(
        valid=not unique_warnings,
        skeptic_warnings=unique_warnings,
        quarantined_events=list(dict.fromkeys(quarantined)),
    )
