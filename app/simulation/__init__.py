"""Explicit game-state branches and hypothetical-event quarantine."""

from app.simulation.game_state_branching import (
    GameStatePath,
    attach_game_state_paths,
    early_yellow_card_branch,
    example_game_state_paths,
    goalkeeper_mistake_branch,
    penalty_branch,
    red_card_branch,
)
from app.simulation.hypothetical_event_quarantine import (
    CascadeValidationResult,
    SimulatedEvent,
    SimulatedEventType,
    validate_no_unobserved_event_cascade,
)

__all__ = [
    "CascadeValidationResult",
    "GameStatePath",
    "SimulatedEvent",
    "SimulatedEventType",
    "attach_game_state_paths",
    "early_yellow_card_branch",
    "example_game_state_paths",
    "goalkeeper_mistake_branch",
    "penalty_branch",
    "red_card_branch",
    "validate_no_unobserved_event_cascade",
]
