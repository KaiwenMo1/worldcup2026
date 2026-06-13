from __future__ import annotations

import unittest

from app.tactics.manager_skills import load_team_manager_skill
from scripts.curate_manager_skills_from_history import curate_skill
from scripts.sync_statsbomb_manager_history import (
    build_history_row,
    match_manager,
    normalized_tokens,
)


class StatsBombManagerHistoryTests(unittest.TestCase):
    def test_expanded_provider_name_matches_unique_registry_manager(self) -> None:
        managers = [
            {"manager_id": "argentina_scaloni", "manager_name": "Lionel Scaloni", "team": "Argentina"},
            {"manager_id": "portugal_martinez", "manager_name": "Roberto Martinez", "team": "Portugal"},
        ]

        matched = match_manager("Lionel Sebastián Scaloni", managers)

        self.assertEqual(matched["manager_id"], "argentina_scaloni")
        self.assertEqual(normalized_tokens("Martínez"), {"martinez"})

    def test_ambiguous_or_unrelated_names_do_not_match(self) -> None:
        managers = [
            {"manager_id": "one", "manager_name": "Rudi Garcia", "team": "A"},
            {"manager_id": "two", "manager_name": "Luis Garcia", "team": "B"},
        ]

        self.assertIsNone(match_manager("Marcelino Garcia Toral", managers))

    def test_history_row_derives_observed_tactical_metrics(self) -> None:
        match = {
            "match_id": 1,
            "match_date": "2024-01-01",
            "competition": {"name": "Test Cup"},
            "home_team": {
                "home_team_name": "France",
                "managers": [{"name": "Didier Deschamps"}],
            },
            "away_team": {"away_team_name": "Brazil", "managers": [{"name": "Test Coach"}]},
            "home_score": 1,
            "away_score": 0,
        }
        events = [
            {"type": {"name": "Starting XI"}, "team": {"name": "France"}, "tactics": {"formation": 433}},
            {
                "type": {"name": "Pass"},
                "team": {"name": "France"},
                "possession_team": {"name": "France"},
                "location": [30, 40],
                "pass": {"end_location": [55, 40]},
            },
            {
                "type": {"name": "Pressure"},
                "team": {"name": "France"},
                "possession_team": {"name": "Brazil"},
                "location": [70, 35],
            },
            {
                "type": {"name": "Shot"},
                "team": {"name": "France"},
                "possession_team": {"name": "France"},
                "minute": 60,
                "shot": {"outcome": {"name": "Goal"}, "statsbomb_xg": 0.25},
                "play_pattern": {"name": "From Corner"},
            },
            {"type": {"name": "Substitution"}, "team": {"name": "France"}, "minute": 65},
        ]
        manager = {"manager_id": "france_deschamps", "manager_name": "Didier Deschamps", "team": "France"}

        row = build_history_row(match, events, manager, {"Brazil": 90})

        self.assertEqual(row["formation"], "4-3-3")
        self.assertEqual(row["first_sub_minute"], 65)
        self.assertEqual(row["leading_minutes"], 30)
        self.assertGreater(row["build_up_directness"], 0)
        self.assertGreater(row["set_piece_xg"], 0)

    def test_manager_skill_curation_is_idempotent(self) -> None:
        skill = load_team_manager_skill("France")
        feature = {
            "sample_size": "12",
            "evidence_confidence": "0.4",
            "last_observed": "2024-07-09",
            "preferred_formation": "4-2-3-1",
            "pressing_score": "38",
            "possession_score": "52",
            "build_up_directness_score": "44",
            "transition_score": "41",
            "defensive_line_score": "43",
            "set_piece_score": "35",
        }

        once = curate_skill(skill, feature)
        twice = curate_skill(once, feature)

        self.assertEqual(twice.evidence_notes, once.evidence_notes)
        self.assertEqual(twice.version, "0.2-statsbomb-observed")
        self.assertEqual(twice.status, "evidence_backed")


if __name__ == "__main__":
    unittest.main()
