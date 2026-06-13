from __future__ import annotations

import unittest
from pathlib import Path

from app.main import (
    ai_matchroom,
    api_groups,
    api_teams,
    app,
    index,
    model_lab,
    prediction_arena_page,
    research_dashboard,
)


class ApiContractTests(unittest.TestCase):
    def test_core_routes_are_registered(self) -> None:
        routes = {route.path for route in app.routes}

        self.assertTrue(
            {
                "/",
                "/ai",
                "/arena",
                "/dashboard",
                "/model-lab",
                "/api/status",
                "/api/teams",
                "/api/groups",
                "/api/simulate",
                "/api/match",
                "/api/intelligence",
                "/api/tactics/managers",
                "/api/tactics/manager/{team}",
                "/api/tactics/coverage/{team}",
                "/api/tactics/matchups",
                "/api/tactics/brief",
                "/api/tactics/brief-with-lineups",
                "/api/analyst/log",
                "/api/analyst/logs",
                "/api/analyst/postgame-review",
                "/api/analyst/profile/{analyst}",
                "/api/refresh-player-stats",
                "/api/player-role-vector/{player_id}",
                "/api/team-role-depth/{team}",
                "/api/player-availability/{player_id}",
                "/api/refresh-injury-news",
                "/api/injury-status",
                "/api/refresh-tactical-evidence",
                "/api/manager-evidence/{manager_id}",
                "/api/manager-skill/refine-dry-run",
                "/api/manager-skill/apply-update",
                "/api/refresh-lineups",
                "/api/lineup-delta",
                "/api/refresh-event-data",
                "/api/evaluate-match",
                "/api/evaluation/match/{match_id}",
                "/api/evaluation/manager/{manager_id}",
                "/api/evaluation/analyst/{analyst}",
                "/api/evaluation/model",
                "/api/match-with-lineups",
                "/api/tournament-autopilot/run",
                "/api/observed-matches",
                "/api/prediction-arena/run",
                "/api/prediction-arena/match/{match_id}",
                "/api/prediction-arena/lock",
                "/api/prediction-arena/publish-card",
                "/api/prediction-arena/settle",
                "/api/prediction-arena/leaderboard",
                "/api/prediction-arena/calibration",
                "/api/ai/status",
                "/api/ai/live-board",
                "/api/ai/match-stories",
                "/api/ai/refresh-live",
                "/api/ai/player-comparison",
                "/api/ai/match",
                "/api/ai/tournament",
            }.issubset(routes)
        )

    def test_team_and_group_endpoints_match_tournament_shape(self) -> None:
        teams = api_teams()["teams"]
        groups = api_groups()["groups"]

        self.assertEqual(len(teams), 48)
        self.assertEqual(len(groups), 12)
        self.assertTrue(all(len(group) == 4 for group in groups.values()))

    def test_public_homepage_and_specialist_pages_are_separate(self) -> None:
        self.assertTrue(str(index().path).endswith("app/static/ai.html"))
        self.assertTrue(str(ai_matchroom().path).endswith("app/static/ai.html"))
        self.assertTrue(str(prediction_arena_page().path).endswith("app/static/arena.html"))
        self.assertTrue(str(research_dashboard().path).endswith("app/static/index.html"))
        self.assertTrue(str(model_lab().path).endswith("app/static/index.html"))

    def test_dashboard_scroll_navigation_only_queries_anchor_links(self) -> None:
        javascript = Path("app/static/app.js").read_text(encoding="utf-8")

        self.assertIn('link.getAttribute("href")?.startsWith("#")', javascript)
        self.assertIn("const anchorLinks =", javascript)
        self.assertNotIn(
            'const sections = navLinks\n    .map((link) => document.querySelector(link.getAttribute("href")))',
            javascript,
        )

    def test_ai_matchroom_leads_with_individual_match_stories(self) -> None:
        html = Path("app/static/ai.html").read_text(encoding="utf-8")
        javascript = Path("app/static/ai.js").read_text(encoding="utf-8")

        self.assertIn('id="matchStories"', html)
        self.assertIn("What happens next, and why.", html)
        self.assertIn("No data dump.", html)
        self.assertIn("/api/ai/match-stories", javascript)
        self.assertIn("data-story-match", javascript)
        self.assertIn("Likely script", javascript)
        self.assertIn("Player to watch", javascript)
        self.assertNotIn('id="matchForm"', html)
        self.assertNotIn('id="tournamentForm"', html)


if __name__ == "__main__":
    unittest.main()
