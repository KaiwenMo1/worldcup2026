from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.prediction_arena.api_service import (
    get_arena_calibration,
    get_arena_leaderboard,
    get_arena_match,
    lock_arena_match,
    publish_arena_card,
    run_arena_match,
    settle_arena_match,
)


FORECAST = {
    "expected_score": {"team_a": 1.42, "team_b": 1.08},
    "probabilities": {"team_a_win": 44.0, "draw": 29.0, "team_b_win": 27.0},
    "scorelines": [
        {"team_a_score": 1, "team_b_score": 1, "probability": 13.0},
        {"team_a_score": 1, "team_b_score": 0, "probability": 12.5},
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
            "reason": "France can isolate the right back.",
        }
    ],
    "tactical_summary": "France has the clearer transition route.",
}


def forecast_provider(team_a: str, team_b: str):
    return FORECAST


def brief_provider(team_a: str, team_b: str, match_id: str, forecast):
    return BRIEF


class PredictionArenaApiServiceTests(unittest.TestCase):
    def test_full_service_lifecycle_is_serializable_and_missing_data_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pre_match = root / "ledgers" / "pre_match.csv"
            models = root / "ledgers" / "models.csv"
            results = root / "ledgers" / "results.csv"
            cards = root / "cards"
            card_ledger = root / "ledgers" / "cards.csv"

            missing = get_arena_match(
                "M404",
                pre_match_path=pre_match,
                model_path=models,
                results_path=results,
                cards_dir=cards,
            )
            self.assertFalse(missing["found"])
            self.assertTrue(missing["warnings"])

            run = run_arena_match(
                "M 101",
                "France",
                "Brazil",
                "knockout",
                pre_match_path=pre_match,
                model_path=models,
                results_path=results,
                cards_dir=cards,
                card_ledger_path=card_ledger,
                forecast_provider=forecast_provider,
                tactical_brief_provider=brief_provider,
            )
            self.assertEqual(run["run"]["version"], 1)
            self.assertTrue(run["match"]["found"])
            self.assertEqual(len(run["match"]["records"]), 5)

            locked = lock_arena_match(
                "M 101",
                pre_match_path=pre_match,
                model_path=models,
                results_path=results,
                cards_dir=cards,
            )
            self.assertTrue(all(row["status"] == "locked" for row in locked["locked_records"]))

            published = publish_arena_card(
                "M 101",
                pre_match_path=pre_match,
                model_path=models,
                results_path=results,
                cards_dir=cards,
                card_ledger_path=card_ledger,
            )
            self.assertTrue(published["match"]["public_card"]["available"])
            self.assertIn("Final Forecast", published["markdown"])

            settled = settle_arena_match(
                "M 101",
                "1-1",
                "Draw",
                "France advance",
                pre_match_path=pre_match,
                model_path=models,
                results_path=results,
                cards_dir=cards,
            )
            self.assertEqual(settled["leaderboard"]["matches_settled"], 1)
            self.assertEqual(len(settled["results"]), 5)
            self.assertEqual(get_arena_leaderboard(results_path=results)["matches_settled"], 1)

            calibration = get_arena_calibration(
                prediction_paths=[pre_match, models],
                results_path=results,
                scoreline_path=root / "calibration" / "scoreline.csv",
                upset_path=root / "calibration" / "upset.csv",
                performance_path=root / "calibration" / "performance.csv",
            )
            self.assertEqual(len(calibration["agent_performance"]), 5)
            self.assertIn("entertainment_disclaimer", calibration)

    def test_frontend_exposes_complete_arena_workspace_without_financial_language(self) -> None:
        html = Path("app/static/arena.html").read_text(encoding="utf-8")
        javascript = Path("app/static/arena.js").read_text(encoding="utf-8")
        section = html.split('<section id="predictionArena"', 1)[1].split("</section>", 1)[0]

        for element_id in (
            "arenaRunBtn",
            "arenaAgentBattle",
            "arenaPublicCard",
            "arenaFragile",
            "arenaWatch",
            "arenaLeaderboard",
            "arenaCalibration",
        ):
            self.assertIn(f'id="{element_id}"', section)
            self.assertIn(element_id, javascript)
        for term in ("bankroll", "payout", "guaranteed profit", "risk-free", "sure bet"):
            self.assertNotIn(term, section.casefold())

        dashboard = Path("app/static/index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="predictionArena"', dashboard)
        self.assertIn('href="/arena"', dashboard)


if __name__ == "__main__":
    unittest.main()
