from __future__ import annotations

import unittest

from app.ai_forecast import build_player_matchup_intelligence, live_match_board
from app.main import (
    AiMatchRequest,
    AiTournamentRequest,
    api_ai_match,
    api_ai_match_stories,
    api_ai_status,
    api_ai_tournament,
    load_live_state,
)
from app.tactics.manager_skills import list_manager_skills, load_team_manager_skill


class AiForecastTests(unittest.TestCase):
    def test_all_tournament_teams_have_transparent_manager_skill_coverage(self) -> None:
        skills = list_manager_skills()
        brazil = load_team_manager_skill("Brazil")

        self.assertEqual(len(skills), 48)
        self.assertIsNotNone(brazil)
        self.assertEqual(brazil.status, "manual_prototype")
        self.assertTrue(any("not observed manager behavior" in note for note in brazil.evidence_notes))

    def test_player_intelligence_compares_positions_and_scorers(self) -> None:
        result = build_player_matchup_intelligence("France", "Brazil", 1.3, 1.1)

        self.assertEqual([row["position"] for row in result["position_advantages"]], ["GK", "DF", "MF", "FW"])
        self.assertGreater(len(result["scorer_watch"]["France"]), 0)
        self.assertIn("position_percentile", result["scorer_watch"]["France"][0])
        self.assertIn("risk_note", result)

    def test_live_board_preserves_completed_state_and_fixture_context(self) -> None:
        board = live_match_board(load_live_state())

        self.assertGreaterEqual(board["completed_count"], 2)
        self.assertTrue(board["recent_completed"])
        self.assertTrue(board["upcoming"])
        self.assertIn("source", board)

    def test_live_board_uses_official_scheduled_knockout_assignments(self) -> None:
        state = load_live_state()
        scheduled = next(
            (
                row
                for row in state.get("current_matches", [])
                if row.get("status") == "scheduled"
                and row.get("stage") == "Round of 32"
                and row.get("team_a")
                and row.get("team_b")
            ),
            None,
        )
        if scheduled is None:
            self.skipTest("Official feed has not published a ready Round of 32 assignment yet.")

        board = live_match_board(state, limit=104)
        board_row = next(row for row in board["upcoming"] if row["match_id"] == scheduled["match_id"])

        self.assertEqual(board_row["team_a"], scheduled["team_a"])
        self.assertEqual(board_row["team_b"], scheduled["team_b"])
        self.assertEqual(board_row["stage"], "Round of 32")
        self.assertEqual(board_row["official_status"], "scheduled")

    def test_reasoned_match_wraps_existing_forecast_without_changing_it(self) -> None:
        result = api_ai_match(AiMatchRequest(team_a="France", team_b="Brazil", use_model=False))
        forecast = result["forecast"]

        self.assertEqual(result["team_a"], forecast["team_a"])
        self.assertEqual(result["team_b"], forecast["team_b"])
        self.assertEqual(result["analysis_mode"], "deterministic_evidence_reasoning")
        self.assertTrue(result["score_reason"])
        self.assertTrue(result["deductions"])
        self.assertIn("France", result["manager_duel"])
        self.assertIn("Brazil", result["manager_duel"])

    def test_match_stories_give_each_upcoming_fixture_a_compact_reason(self) -> None:
        result = api_ai_match_stories(limit=2, use_model=False)

        self.assertEqual(len(result["stories"]), 2)
        self.assertFalse(result["warnings"])
        self.assertEqual(result["next_offset"], 2)
        self.assertTrue(result["has_more"])
        for story in result["stories"]:
            self.assertTrue(story["headline"])
            self.assertTrue(story["reason"])
            self.assertTrue(story["deduction"]["likely_script"])
            self.assertTrue(story["deduction"]["manager_move"])
            self.assertTrue(story["deduction"]["player_watch"])
            self.assertEqual(len(story["managers"]), 2)
            self.assertIn("team_a", story["predicted_score"])
            self.assertIn("team_a_win", story["probabilities"])
            self.assertEqual(story["reasoning_boundary"], "This story summarizes the existing forecast; it does not alter it.")

    def test_ai_status_exposes_coverage_and_reasoning_boundary(self) -> None:
        status = api_ai_status()

        self.assertEqual(status["manager_profiles"], 48)
        self.assertEqual(status["manager_skills"], 48)
        self.assertEqual(status["manager_profiles_without_skill"], 0)
        self.assertEqual(status["manager_curation"]["observed_managers"], 30)
        self.assertEqual(status["manager_curation"]["observed_matches"], 236)
        self.assertIn("do not alter", status["reasoning_boundary"])

    def test_tournament_reasoning_exposes_odds_and_full_exact_score_path(self) -> None:
        result = api_ai_tournament(AiTournamentRequest(sims=2, seed=26, use_model=False))
        contenders = result["contenders"]
        bracket = result["simulation"]["bracket"]

        self.assertTrue(contenders)
        self.assertTrue(all("win_pct" in contender for contender in contenders))
        self.assertTrue(any(contender["win_pct"] > 0 for contender in contenders))
        self.assertEqual(len(bracket["groups"]), 12)
        self.assertEqual(
            [round_payload["name"] for round_payload in bracket["bracket"]["rounds"]],
            ["Round of 32", "Round of 16", "Quarterfinals", "Semifinals", "Bronze Final", "Final"],
        )
        self.assertTrue(
            all(
                "score_a" in match and "score_b" in match and match.get("reasoning_summary")
                for round_payload in bracket["bracket"]["rounds"]
                for match in round_payload["matches"]
            )
        )


if __name__ == "__main__":
    unittest.main()
