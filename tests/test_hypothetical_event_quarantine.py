from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.agents import run_expert_agent, run_kevin_agent, run_skeptic_agent, run_upset_agent
from app.simulation import (
    SimulatedEvent,
    attach_game_state_paths,
    example_game_state_paths,
    validate_no_unobserved_event_cascade,
)


FORECAST = {
    "expected_score": {"team_a": 1.42, "team_b": 1.08},
    "probabilities": {"team_a_win": 44.0, "draw": 29.0, "team_b_win": 27.0},
    "scorelines": [{"team_a_score": 1, "team_b_score": 0, "probability": 12.5}],
}


class HypotheticalEventQuarantineTests(unittest.TestCase):
    def test_unobserved_event_defaults_to_quarantined(self) -> None:
        event = SimulatedEvent(
            event_type="yellow_card",
            team="Brazil",
            player="Brazil RB",
            minute_range="0-30",
            probability=0.24,
            impact_if_occurs="France may attack the affected side more directly.",
            reasoning_note="This is a branch, not a fact.",
        )

        self.assertFalse(event.is_observed)
        self.assertFalse(event.allowed_to_cascade)

    def test_typed_unobserved_event_cannot_enable_cascade(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unobserved simulated events cannot be allowed to cascade"):
            SimulatedEvent(
                event_type="red_card",
                team="France",
                probability=0.08,
                allowed_to_cascade=True,
                impact_if_occurs="France defends with ten players.",
                reasoning_note="Unsafe test payload.",
            )

    def test_raw_unsafe_payload_returns_skeptic_warnings(self) -> None:
        result = validate_no_unobserved_event_cascade(
            {
                "main_prediction": {"pick": "France"},
                "assumed_event": {
                    "event_type": "goalkeeper_mistake",
                    "probability": 0.07,
                    "is_observed": False,
                    "allowed_to_cascade": True,
                    "impact_if_occurs": "Brazil scores.",
                },
            }
        )

        self.assertFalse(result.valid)
        self.assertEqual(result.quarantined_events, ["goalkeeper_mistake"])
        self.assertTrue(any("incorrectly allowed to cascade" in warning for warning in result.skeptic_warnings))
        self.assertTrue(any("outside an explicit GameStatePath" in warning for warning in result.skeptic_warnings))

    def test_four_example_branches_validate_and_do_not_modify_main_prediction(self) -> None:
        main = {"regular_time_90": {"pick": "France", "score": "1-0", "confidence": 0.44}}
        original = {"regular_time_90": dict(main["regular_time_90"])}
        paths = example_game_state_paths("France", "Brazil")
        result = attach_game_state_paths(main, paths)

        self.assertEqual(main, original)
        self.assertEqual(result["main_prediction"], original)
        self.assertEqual(
            [path.path_id for path in paths],
            [
                "branch_early_yellow",
                "branch_red_card",
                "branch_penalty",
                "branch_goalkeeper_mistake",
            ],
        )
        self.assertTrue(validate_no_unobserved_event_cascade(result).valid)
        self.assertTrue(all(not event.allowed_to_cascade for path in paths for event in path.simulated_events))

    def test_observed_event_may_cascade(self) -> None:
        event = SimulatedEvent(
            event_type="goal",
            team="France",
            minute_range="12",
            probability=1,
            is_observed=True,
            allowed_to_cascade=True,
            impact_if_occurs="Brazil must respond to the observed score state.",
            reasoning_note="This goal is recorded as observed live-state evidence.",
        )

        self.assertTrue(event.allowed_to_cascade)
        self.assertTrue(validate_no_unobserved_event_cascade({"observed_events": [event]}).valid)

    def test_skeptic_agent_uses_shared_quarantine_validator(self) -> None:
        expert = run_expert_agent("M001", "France", "Brazil", "knockout", forecast=FORECAST)
        kevin = run_kevin_agent("M001", "France", "Brazil", "knockout", forecast=FORECAST)
        upset = run_upset_agent("M001", "France", "Brazil", "knockout", forecast=FORECAST)
        review = run_skeptic_agent(
            "M001",
            expert,
            kevin,
            upset,
            forecast=FORECAST,
            simulated_events=[
                {
                    "event_type": "penalty",
                    "probability": 0.16,
                    "is_observed": False,
                    "allowed_to_cascade": True,
                }
            ],
        )

        self.assertTrue(review.cascade_warnings)
        self.assertTrue(any("penalty" in warning for warning in review.cascade_warnings))


if __name__ == "__main__":
    unittest.main()
