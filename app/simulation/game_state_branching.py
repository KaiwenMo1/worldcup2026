"""Explicit conditional game-state branches that preserve the main prediction."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.simulation.hypothetical_event_quarantine import SimulatedEvent, SimulatedEventType


class GameStatePath(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    path_id: str = Field(pattern=r"^[a-z0-9_.-]+$")
    description: str = Field(min_length=1)
    probability: float = Field(ge=0, le=1)
    simulated_events: list[SimulatedEvent] = Field(min_length=1)
    tactical_implications: list[str] = Field(default_factory=list)
    score_implications: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_branch_events(self) -> "GameStatePath":
        if any(not event.is_observed and event.allowed_to_cascade for event in self.simulated_events):
            raise ValueError("GameStatePath cannot allow an unobserved event to cascade")
        return self


def attach_game_state_paths(
    main_prediction: BaseModel | dict[str, Any],
    paths: list[GameStatePath],
) -> dict[str, Any]:
    """Attach conditional paths without applying their events to the main prediction."""
    prediction = (
        main_prediction.model_dump(mode="json")
        if isinstance(main_prediction, BaseModel)
        else deepcopy(main_prediction)
    )
    return {
        "main_prediction": prediction,
        "game_state_paths": [path.model_dump(mode="json") for path in paths],
        "branching_boundary": (
            "Game-state paths are conditional scenarios. Their events and implications do not modify the main "
            "prediction unless an event is later observed and a new prediction version is created."
        ),
    }


def early_yellow_card_branch(team: str, player: str = "Opponent fullback") -> GameStatePath:
    return GameStatePath(
        path_id="branch_early_yellow",
        description=f"If {player} receives an early yellow card.",
        probability=0.24,
        simulated_events=[
            SimulatedEvent(
                event_type=SimulatedEventType.YELLOW_CARD,
                team=team,
                player=player,
                minute_range="0-30",
                probability=0.24,
                impact_if_occurs="The opposing winger may attack more directly and the defender may avoid risky duels.",
                reasoning_note="This is a branch, not a claim that the yellow card will happen.",
            )
        ],
        tactical_implications=["Increase attention on one-v-one protection and possible fullback cover."],
        score_implications=["Chance quality may rise on the affected defensive side if the event occurs."],
    )


def red_card_branch(team: str) -> GameStatePath:
    return GameStatePath(
        path_id="branch_red_card",
        description=f"If {team} receives a red card.",
        probability=0.08,
        simulated_events=[
            SimulatedEvent(
                event_type=SimulatedEventType.RED_CARD,
                team=team,
                minute_range="0-90",
                probability=0.08,
                impact_if_occurs=f"{team} would likely defend deeper with reduced attacking coverage.",
                reasoning_note="Red-card variance is represented only as a conditional branch.",
            )
        ],
        tactical_implications=[f"{team} may sacrifice an attacker and protect central space."],
        score_implications=["The opponent's win and multi-goal paths become more plausible only inside this branch."],
    )


def penalty_branch(team: str) -> GameStatePath:
    return GameStatePath(
        path_id="branch_penalty",
        description=f"If {team} is awarded a penalty.",
        probability=0.16,
        simulated_events=[
            SimulatedEvent(
                event_type=SimulatedEventType.PENALTY,
                team=team,
                minute_range="0-90",
                probability=0.16,
                impact_if_occurs=f"{team} receives a high-value scoring opportunity.",
                reasoning_note="Penalty occurrence and conversion remain uncertain conditional events.",
            )
        ],
        tactical_implications=["A converted penalty could force the trailing team to attack with greater risk."],
        score_implications=[f"{team}'s scoring paths improve if the penalty occurs and is converted."],
    )


def goalkeeper_mistake_branch(team: str, player: str = "Goalkeeper") -> GameStatePath:
    return GameStatePath(
        path_id="branch_goalkeeper_mistake",
        description=f"If {team}'s {player} makes a costly mistake.",
        probability=0.07,
        simulated_events=[
            SimulatedEvent(
                event_type=SimulatedEventType.GOALKEEPER_MISTAKE,
                team=team,
                player=player,
                minute_range="0-90",
                probability=0.07,
                impact_if_occurs="A low-probability error creates an unusually high-value chance.",
                reasoning_note="Goalkeeper-error variance is a branch and must never be narrated as observed.",
            )
        ],
        tactical_implications=[f"{team} may need to chase the game after an otherwise unforced swing."],
        score_implications=["The opponent's scoring tail becomes wider only within this branch."],
    )


def example_game_state_paths(team_a: str, team_b: str) -> list[GameStatePath]:
    """Return the four required demonstration branches."""
    return [
        early_yellow_card_branch(team_b),
        red_card_branch(team_a),
        penalty_branch(team_a),
        goalkeeper_mistake_branch(team_b),
    ]
