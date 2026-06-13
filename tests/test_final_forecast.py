from __future__ import annotations

import unittest

from app.agents import (
    run_expert_agent,
    run_final_forecast_agent,
    run_kevin_agent,
    run_skeptic_agent,
    run_upset_agent,
)
from app.prediction_arena.arena_aggregator import aggregate_prediction_arena
from app.prediction_arena.schemas import (
    ENTERTAINMENT_DISCLAIMER,
    KevinAgentPrediction,
    PredictionStage,
)


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
    "tactical_summary": "France has the clearer transition route, but Brazil can slow the game.",
}


def build_agents(stage: PredictionStage, *, upset_context: dict | None = None):
    expert = run_expert_agent("M001", "France", "Brazil", stage, forecast=FORECAST, tactical_brief=BRIEF)
    kevin = run_kevin_agent("M001", "France", "Brazil", stage, forecast=FORECAST, tactical_brief=BRIEF)
    upset = run_upset_agent(
        "M001",
        "France",
        "Brazil",
        stage,
        forecast=FORECAST,
        tactical_brief=BRIEF,
        context=upset_context,
    )
    skeptic = run_skeptic_agent(
        "M001",
        expert,
        kevin,
        upset,
        forecast=FORECAST,
        tactical_brief=BRIEF,
    )
    return expert, kevin, upset, skeptic


class FinalForecastTests(unittest.TestCase):
    def test_group_stage_keeps_knockout_targets_empty(self) -> None:
        expert, kevin, upset, skeptic = build_agents(PredictionStage.GROUP)
        final = run_final_forecast_agent(
            "M001",
            "France",
            "Brazil",
            "group",
            expert=expert,
            kevin=kevin,
            upset=upset,
            skeptic=skeptic,
            base_forecast=FORECAST,
            tactical_brief=BRIEF,
        )

        self.assertEqual(final.final_prediction.regular_time_90.pick, "France")
        self.assertEqual(final.final_prediction.regular_time_90.score, "1-0")
        self.assertIsNone(final.final_prediction.qualification)
        self.assertIsNone(final.final_prediction.after_extra_time)
        self.assertIsNone(final.final_prediction.penalty_shootout_probability)
        self.assertEqual(final.entertainment_disclaimer, ENTERTAINMENT_DISCLAIMER)

    def test_knockout_separates_regular_time_and_qualification(self) -> None:
        expert, kevin, upset, skeptic = build_agents(
            PredictionStage.KNOCKOUT,
            upset_context={"weather": "humid", "favorite_fatigue": True},
        )
        final = run_final_forecast_agent(
            "M001",
            "France",
            "Brazil",
            "knockout",
            expert=expert,
            kevin=kevin,
            upset=upset,
            skeptic=skeptic,
            base_forecast=FORECAST,
            tactical_brief=BRIEF,
        )

        self.assertEqual(final.final_prediction.regular_time_90.pick, "France")
        self.assertEqual(final.final_prediction.qualification.pick, "France advance")
        self.assertEqual(final.final_prediction.after_extra_time.pick, "France advance")
        self.assertIsNotNone(final.final_prediction.penalty_shootout_probability)
        self.assertLessEqual(final.final_confidence, 0.75)
        self.assertTrue(any("Credible upset path" in reason for reason in final.top_reasons))

    def test_missing_lineup_data_reduces_confidence(self) -> None:
        expert, kevin, upset, skeptic = build_agents(PredictionStage.GROUP)
        baseline = aggregate_prediction_arena(
            "M001",
            "France",
            "Brazil",
            "group",
            expert=expert,
            kevin=kevin,
            upset=upset,
            skeptic=skeptic,
            base_forecast=FORECAST,
        )
        missing_lineups = skeptic.model_copy(
            update={"missing_data": ["Confirmed lineups are unavailable."]}
        )
        downgraded = aggregate_prediction_arena(
            "M001",
            "France",
            "Brazil",
            "group",
            expert=expert,
            kevin=kevin,
            upset=upset,
            skeptic=missing_lineups,
            base_forecast=FORECAST,
        )

        self.assertLess(downgraded.final_confidence, baseline.final_confidence)
        self.assertIn("missing_lineups", [item.code for item in downgraded.confidence_adjustments])

    def test_expert_kevin_disagreement_does_not_override_base_pick(self) -> None:
        expert, kevin, upset, skeptic = build_agents(PredictionStage.GROUP)
        payload = kevin.model_dump(mode="json")
        payload["prediction_target"]["regular_time_90"] = {
            "pick": "Brazil",
            "score": "0-1",
            "confidence": 0.42,
        }
        disagreeing_kevin = KevinAgentPrediction.model_validate(payload)
        aggregation = aggregate_prediction_arena(
            "M001",
            "France",
            "Brazil",
            "group",
            expert=expert,
            kevin=disagreeing_kevin,
            upset=upset,
            skeptic=skeptic,
            base_forecast=FORECAST,
        )

        self.assertFalse(aggregation.expert_kevin_agree)
        self.assertEqual(aggregation.regular_time_pick, "France")
        self.assertIn(
            "expert_kevin_disagreement",
            [item.code for item in aggregation.confidence_adjustments],
        )

    def test_skeptic_target_and_cascade_warnings_downgrade_confidence(self) -> None:
        expert, kevin, upset, skeptic = build_agents(PredictionStage.KNOCKOUT)
        baseline = aggregate_prediction_arena(
            "M001",
            "France",
            "Brazil",
            "knockout",
            expert=expert,
            kevin=kevin,
            upset=upset,
            skeptic=skeptic,
            base_forecast=FORECAST,
        )
        warning_skeptic = skeptic.model_copy(
            update={
                "target_confusion_warnings": ["The 90-minute and qualification calls are mixed."],
                "cascade_warnings": ["An unobserved red card was treated as fact."],
            }
        )
        downgraded = aggregate_prediction_arena(
            "M001",
            "France",
            "Brazil",
            "knockout",
            expert=expert,
            kevin=kevin,
            upset=upset,
            skeptic=warning_skeptic,
            base_forecast=FORECAST,
        )

        self.assertLess(downgraded.final_confidence, baseline.final_confidence)
        codes = [item.code for item in downgraded.confidence_adjustments]
        self.assertIn("skeptic_target_confusion", codes)
        self.assertIn("skeptic_unobserved_event_cascade", codes)


if __name__ == "__main__":
    unittest.main()
