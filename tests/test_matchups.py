from __future__ import annotations

import unittest

from app.tactics.matchup_engine import (
    build_matchup_edges,
    score_midfield_control,
    score_set_piece_edge,
    score_striker_vs_centerbacks,
    score_transition_risk,
    score_winger_vs_fullback,
)
from app.tactics.player_profiles import (
    get_team_role_depth,
    load_player_availability,
    load_player_profiles,
    load_projected_lineup,
)
from scripts.predict_worldcup import load_teams, match_probabilities


class PlayerProfileTests(unittest.TestCase):
    def test_profiles_include_explicit_and_existing_derived_players(self) -> None:
        profiles = load_player_profiles()

        self.assertEqual(profiles["france_kylian_mbappe"].data_quality, "manual_prototype")
        self.assertIn("england_bukayo_saka", profiles)
        self.assertEqual(profiles["england_bukayo_saka"].data_quality, "derived_estimate")

    def test_projected_lineup_uses_role_specific_slots(self) -> None:
        lineup = load_projected_lineup("France")
        slots = {item.position_slot for item in lineup}

        self.assertEqual(len(lineup), 11)
        self.assertTrue({"GK", "LW", "RW", "CF", "LB", "RB", "LCB", "RCB", "DM"}.issubset(slots))

    def test_existing_lineup_fallback_normalizes_tactical_slots(self) -> None:
        lineup = load_projected_lineup("England")
        slots = {item.position_slot for item in lineup}

        self.assertTrue({"GK", "RW", "LW", "CF", "DM", "CM", "CB", "RB"}.issubset(slots))

    def test_availability_reuses_existing_table(self) -> None:
        availability = load_player_availability()

        self.assertIn("france_kylian_mbappe", availability)
        self.assertGreater(availability["france_kylian_mbappe"].availability, 0)

    def test_role_depth_summarizes_player_roles(self) -> None:
        depth = get_team_role_depth("France")

        self.assertGreaterEqual(depth["players"], 10)
        self.assertIn("direct_transition_winger", depth["roles"])


class MatchupEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profiles = load_player_profiles()

    def test_transparent_scoring_functions_are_bounded(self) -> None:
        france_midfield = [
            self.profiles["france_aurelien_tchouameni"],
            self.profiles["france_adrien_rabiot"],
            self.profiles["france_ngolo_kante"],
        ]
        brazil_midfield = [
            self.profiles["brazil_casemiro"],
            self.profiles["brazil_bruno_guimaraes"],
            self.profiles["brazil_lucas_paqueta"],
        ]

        scores = [
            score_winger_vs_fullback(
                self.profiles["france_kylian_mbappe"],
                self.profiles["brazil_wesley"],
            ),
            score_striker_vs_centerbacks(
                self.profiles["france_marcus_thuram"],
                [self.profiles["brazil_bremer"], self.profiles["brazil_marquinhos"]],
            ),
            score_midfield_control(france_midfield, brazil_midfield),
            score_set_piece_edge("France", "Brazil"),
            score_transition_risk("France", "Brazil"),
        ]

        self.assertTrue(all(-1 <= score <= 1 for score in scores))

    def test_france_brazil_edges_are_ranked_and_inspectable(self) -> None:
        edges = build_matchup_edges("France", "Brazil")
        matchup_types = {edge.matchup_type for edge in edges}

        self.assertGreaterEqual(len(edges), 9)
        self.assertEqual(edges, sorted(edges, key=lambda edge: edge.edge_score, reverse=True))
        self.assertTrue(
            {
                "winger_vs_fullback",
                "striker_vs_centerbacks",
                "midfield_control",
                "set_piece_edge",
                "transition_defense_risk",
                "press_vs_build_up",
            }.issubset(matchup_types)
        )
        self.assertTrue(all(0 <= edge.edge_score <= 1 for edge in edges))
        self.assertTrue(all(edge.reason and edge.relevant_features and edge.data_quality for edge in edges))
        self.assertTrue(all("probability" not in edge.edge_label for edge in edges))

    def test_matchup_analysis_does_not_change_existing_probabilities(self) -> None:
        teams = load_teams()
        before = match_probabilities(teams["France"], teams["Brazil"])

        build_matchup_edges("France", "Brazil")
        after = match_probabilities(teams["France"], teams["Brazil"])

        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
