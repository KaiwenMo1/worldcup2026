from __future__ import annotations

import unittest

from app.tactics.data_coverage import team_data_coverage
from scripts.backtest_context_features import build_frame, evaluate_gate
from scripts.build_player_identity_map import build_map
from scripts.distill_manager_profiles import distill_manager
from scripts.predict_worldcup import ROOT
from scripts.sync_managers import read_csv, validate_registry
from scripts.sync_manager_match_history import normalize_rows as normalize_manager_history
from scripts.sync_observed_player_stats import normalize_rows


class TacticalDataPipelineTests(unittest.TestCase):
    def test_manager_registry_satisfies_48_team_contract(self) -> None:
        report = validate_registry(read_csv(ROOT / "data" / "managers.csv"))

        self.assertTrue(report["valid"])
        self.assertEqual(report["registered"], 48)

    def test_manager_history_distillation_is_observed_and_transparent(self) -> None:
        manager = {"manager_id": "test_manager", "manager_name": "Test Manager", "team": "Test", "preferred_formations": "4-3-3"}
        history = [
            {
                "date": f"2026-05-{day:02d}",
                "goals_for": "2",
                "goals_against": "1",
                "opponent_strength": "80",
                "formation": "4-3-3",
                "ppda": "10",
                "possession_share": "0.55",
                "source": "observed-test",
            }
            for day in range(1, 11)
        ]

        profile = distill_manager(manager, history)

        self.assertEqual(profile["sample_size"], 10)
        self.assertEqual(profile["preferred_formation"], "4-3-3")
        self.assertEqual(profile["data_quality"], "observed")
        self.assertGreater(profile["pressing_score"], 0)

    def test_manager_history_adapter_requires_explicit_identity(self) -> None:
        managers = read_csv(ROOT / "data" / "managers.csv")
        rows, rejected = normalize_manager_history(
            [
                {
                    "fixture_id": "test-1",
                    "match_date": "2026-05-10",
                    "team": "France",
                    "manager_name": "Didier Deschamps",
                    "opponent": "Brazil",
                    "team_score": "2",
                    "opponent_score": "1",
                },
                {
                    "fixture_id": "test-2",
                    "match_date": "2020-05-10",
                    "team": "France",
                    "opponent": "Brazil",
                },
            ],
            managers,
            "sample-provider",
        )

        self.assertEqual(rows[0]["manager_id"], "france_deschamps")
        self.assertEqual(rows[0]["source"], "sample-provider")
        self.assertEqual(len(rejected), 1)

    def test_player_identity_map_links_exact_team_and_normalized_name(self) -> None:
        squads = [{"team": "France", "player": "Kylian Mbappe", "club": "Real Madrid", "source": "squad"}]
        provider = [{"team": "France", "player": "Kylian Mbappé", "player_id": "provider-10"}]

        rows = build_map(squads, provider, "sample-provider")

        self.assertEqual(rows[0]["provider_player_id"], "provider-10")
        self.assertEqual(rows[0]["status"], "provider_linked")

    def test_observed_provider_adapter_normalizes_common_aliases(self) -> None:
        rows = normalize_rows(
            [
                {
                    "team": "France",
                    "player": "Kylian Mbappe",
                    "player_id": "provider-10",
                    "minutes_played": "1500",
                    "pass_accuracy": "84.2",
                }
            ],
            "sample-provider",
        )

        self.assertEqual(rows[0]["provider_player_id"], "provider-10")
        self.assertEqual(rows[0]["minutes"], "1500")
        self.assertEqual(rows[0]["pass_completion_pct"], "84.2")

    def test_context_features_remain_disabled_without_observed_coverage(self) -> None:
        frame = build_frame(
            ROOT / "data" / "historical_matches.csv",
            ROOT / "data" / "historical_context_features.csv",
        )
        result = evaluate_gate(frame)

        self.assertFalse(result["enabled"])
        self.assertEqual(result["coverage"], 0.0)
        self.assertIn("Insufficient", result["reason"])

    def test_team_coverage_reports_observed_vs_estimated_data(self) -> None:
        coverage = team_data_coverage("France")

        self.assertTrue(coverage.manager_registered)
        self.assertEqual(coverage.manager_history_matches, 12)
        self.assertEqual(coverage.manager_data_quality, "observed")
        self.assertGreater(coverage.identity_mapped_players, 0)
        self.assertEqual(coverage.provider_linked_identities, 0)
        self.assertEqual(coverage.observed_player_profiles, 0)
        self.assertFalse(coverage.context_feature_gate_enabled)


if __name__ == "__main__":
    unittest.main()
