from __future__ import annotations

import unittest

from app.main import (
    api_tactics_brief,
    api_tactics_manager,
    api_tactics_managers,
    api_tactics_matchups,
)
from app.tactics.schemas import TacticalBriefRequest, TacticalMatchupRequest
from app.tactics.tactical_brief import build_tactical_brief


class TacticalBriefTests(unittest.TestCase):
    def test_brief_explains_forecast_without_rewriting_it(self) -> None:
        forecast = {
            "expected_score": {"team_a": 1.42, "team_b": 1.08},
            "probabilities": {"team_a_win": 44.0, "draw": 28.0, "team_b_win": 28.0},
            "scorelines": [
                {"team_a_score": 1, "team_b_score": 0, "probability": 13.0},
                {"team_a_score": 1, "team_b_score": 1, "probability": 12.0},
            ],
        }
        original = {
            "expected_score": dict(forecast["expected_score"]),
            "probabilities": dict(forecast["probabilities"]),
            "scorelines": [dict(row) for row in forecast["scorelines"]],
        }

        brief = build_tactical_brief("France", "Brazil", forecast=forecast)

        self.assertEqual(forecast, original)
        self.assertEqual(brief.forecast.expected_score, forecast["expected_score"])
        self.assertEqual(brief.forecast.probabilities, forecast["probabilities"])
        self.assertEqual(brief.manager_plan_a.team, "France")
        self.assertEqual(brief.manager_plan_b.team, "Brazil")
        self.assertTrue(brief.top_matchup_edges)
        self.assertTrue(brief.sources)
        self.assertEqual(set(brief.data_coverage), {"France", "Brazil"})
        self.assertFalse(brief.data_coverage["France"].context_feature_gate_enabled)
        self.assertEqual(brief.data_coverage["France"].observed_player_profiles, 0)
        self.assertIn("does not alter", brief.probability_boundary_note)
        self.assertIn("not match-outcome probability", brief.evidence_confidence.meaning)

    def test_missing_team_data_returns_visible_fallbacks(self) -> None:
        brief = build_tactical_brief("Unknown A", "Unknown B")

        self.assertFalse(brief.forecast.available)
        self.assertTrue(brief.manager_plan_a.fallback_used)
        self.assertTrue(brief.manager_plan_b.fallback_used)
        self.assertEqual(brief.data_quality, "mixed_with_fallback")
        self.assertTrue(any("No projected or confirmed lineup" in note for note in brief.fallback_notes))


class TacticalApiTests(unittest.TestCase):
    def test_manager_endpoints_return_full_coverage_and_provenance(self) -> None:
        catalog = api_tactics_managers()
        france = api_tactics_manager("France")
        brazil = api_tactics_manager("Brazil")

        self.assertEqual(catalog["count"], 48)
        self.assertEqual(catalog["skills_count"], 48)
        self.assertEqual(france["manager"]["manager_id"], "france_deschamps")
        self.assertFalse(france["plan"]["fallback_used"])
        self.assertEqual(brazil["manager"]["manager_id"], "brazil_ancelotti")
        self.assertEqual(brazil["manager"]["version"], "0.2-statsbomb-observed")
        self.assertEqual(brazil["manager"]["status"], "manual_prototype")
        self.assertEqual(brazil["registry"]["manager_name"], "Carlo Ancelotti")
        self.assertFalse(brazil["plan"]["fallback_used"])
        self.assertEqual(catalog["curation"]["observed_managers"], 30)
        self.assertEqual(catalog["curation"]["evidence_backed"], 10)

    def test_matchup_endpoint_returns_ranked_non_probability_edges(self) -> None:
        payload = api_tactics_matchups(TacticalMatchupRequest(team_a="France", team_b="Brazil", top_n=4))

        self.assertEqual(len(payload["edges"]), 4)
        self.assertEqual(
            payload["edges"],
            sorted(payload["edges"], key=lambda edge: edge["edge_score"], reverse=True),
        )
        self.assertIn("not a calibrated probability", payload["edge_score_meaning"])

    def test_brief_endpoint_includes_existing_forecast(self) -> None:
        payload = api_tactics_brief(
            TacticalBriefRequest(team_a="France", team_b="Brazil", use_model=False, top_matchups=3)
        )

        self.assertTrue(payload["forecast"]["available"])
        self.assertEqual(len(payload["top_matchup_edges"]), 3)
        self.assertIn("expected_score", payload["forecast"])
        self.assertIn("probabilities", payload["forecast"])
        self.assertIn("does not alter", payload["probability_boundary_note"])


if __name__ == "__main__":
    unittest.main()
