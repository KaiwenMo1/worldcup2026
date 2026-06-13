from __future__ import annotations

import unittest

from app.agents import run_expert_agent, run_kevin_agent, run_skeptic_agent, run_upset_agent
from app.prediction_arena.schemas import ENTERTAINMENT_DISCLAIMER, PredictionStage


FORECAST = {
    "expected_score": {"team_a": 1.42, "team_b": 1.08},
    "probabilities": {"team_a_win": 44.0, "draw": 29.0, "team_b_win": 27.0},
    "scorelines": [
        {"team_a_score": 1, "team_b_score": 1, "probability": 13.0},
        {"team_a_score": 1, "team_b_score": 0, "probability": 12.5},
        {"team_a_score": 2, "team_b_score": 1, "probability": 9.5},
    ],
}
BRIEF = {
    "manager_plan_a": {"base_plan": "controlled transition"},
    "manager_plan_b": {"base_plan": "balanced possession"},
    "top_matchup_edges": [
        {
            "matchup_type": "winger_vs_fullback",
            "team_a_player": "France LW",
            "team_b_player": "Brazil RB",
            "favored_team": "France",
            "edge_score": 0.67,
            "reason": "France can repeatedly isolate Brazil's right back.",
            "lineup_assumptions": ["Brazil starts an attack-minded right back."],
        }
    ],
    "availability_risks": [
        {"player": "Favorite Defender", "team": "France", "risk_score": 0.2}
    ],
    "tactical_summary": "France has the clearer transition route, but Brazil can slow the game.",
    "fallback_notes": ["Confirmed lineups are unavailable."],
}


class DeterministicAgentTests(unittest.TestCase):
    def test_expert_consumes_forecast_and_brief_without_mutating_them(self) -> None:
        forecast_before = {**FORECAST, "probabilities": dict(FORECAST["probabilities"])}
        expert = run_expert_agent(
            "M001", "France", "Brazil", PredictionStage.KNOCKOUT, forecast=FORECAST, tactical_brief=BRIEF
        )

        self.assertEqual(FORECAST, forecast_before)
        self.assertEqual(expert.prediction_target.regular_time_90.pick, "France")
        self.assertEqual(expert.prediction_target.regular_time_90.score, "1-0")
        self.assertEqual(expert.prediction_target.qualification.pick, "France advance")
        self.assertEqual(expert.key_matchups[0].favored_team, "France")
        self.assertTrue(expert.execution_risks)
        self.assertEqual(expert.entertainment_disclaimer, ENTERTAINMENT_DISCLAIMER)

    def test_kevin_is_decisive_but_names_uncertainty(self) -> None:
        kevin = run_kevin_agent("M001", "France", "Brazil", "knockout", forecast=FORECAST, tactical_brief=BRIEF)

        self.assertIn("France LW", kevin.one_decisive_matchup)
        self.assertLessEqual(len(kevin.core_reasons), 3)
        self.assertTrue(kevin.what_would_make_me_wrong)
        self.assertTrue(kevin.most_fragile_assumption)
        self.assertEqual(kevin.tone, "bold_but_uncertain")

    def test_upset_agent_constructs_conditional_underdog_path(self) -> None:
        upset = run_upset_agent(
            "M001",
            "France",
            "Brazil",
            "knockout",
            forecast=FORECAST,
            tactical_brief=BRIEF,
            context={"weather": "humid", "favorite_fatigue": True},
        )

        self.assertEqual(upset.underdog, "Brazil")
        self.assertEqual(upset.prediction_target.regular_time_90.pick, "Brazil")
        self.assertEqual(upset.prediction_target.qualification.pick, "Brazil advance")
        self.assertGreaterEqual(len(upset.required_conditions), 3)
        self.assertTrue(any("Weather" in warning for warning in upset.warning_signs))
        self.assertTrue(any("fatigue" in warning for warning in upset.warning_signs))

    def test_skeptic_only_critiques_and_flags_cascade_risk(self) -> None:
        expert = run_expert_agent("M001", "France", "Brazil", "knockout", forecast=FORECAST, tactical_brief=BRIEF)
        kevin = run_kevin_agent("M001", "France", "Brazil", "knockout", forecast=FORECAST, tactical_brief=BRIEF)
        upset = run_upset_agent("M001", "France", "Brazil", "knockout", forecast=FORECAST, tactical_brief=BRIEF)
        skeptic = run_skeptic_agent(
            "M001",
            expert,
            kevin,
            upset,
            forecast=FORECAST,
            tactical_brief=BRIEF,
            simulated_events=[{"event_type": "yellow_card", "is_observed": False, "allowed_to_cascade": True}],
        )

        self.assertTrue(skeptic.unsupported_assumptions)
        self.assertTrue(skeptic.fake_precision_warnings)
        self.assertTrue(skeptic.cascade_warnings)
        self.assertTrue(skeptic.recommended_downgrades)
        self.assertEqual(skeptic.overall_risk_level, "high")
        self.assertFalse(hasattr(skeptic, "final_prediction"))

    def test_group_stage_agents_leave_knockout_targets_empty(self) -> None:
        expert = run_expert_agent("M002", "France", "Brazil", "group", forecast=FORECAST)

        self.assertIsNone(expert.prediction_target.after_extra_time)
        self.assertIsNone(expert.prediction_target.qualification)
        self.assertIsNone(expert.prediction_target.penalty_shootout_probability)


if __name__ == "__main__":
    unittest.main()
