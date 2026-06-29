from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from app.ingestion.manager_observation_ingestion import (
    build_formation_prediction_signals,
    build_manager_match_observations,
    write_formation_prediction_signals,
    write_manager_match_observations,
)
from app.main import (
    automatic_fixture_context,
    detailed_match_event_signal,
    load_teams,
    thermal_comfort_signal,
)


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class ManagerObservationIngestionTests(unittest.TestCase):
    def test_manager_observations_combine_scores_lineups_and_event_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observed = root / "observed.csv"
            managers = root / "managers.csv"
            summaries = root / "summaries.csv"
            lineups = root / "lineups.csv"
            events = root / "events.csv"

            write_csv(
                observed,
                [
                    {
                        "match_id": "M1",
                        "stage": "Group",
                        "group": "A",
                        "kickoff_utc": "2026-06-11T19:00:00Z",
                        "team_a": "France",
                        "team_b": "Brazil",
                        "team_a_score": 2,
                        "team_b_score": 1,
                    }
                ],
                ["match_id", "stage", "group", "kickoff_utc", "team_a", "team_b", "team_a_score", "team_b_score"],
            )
            write_csv(
                managers,
                [{"team": "France", "manager_id": "france_deschamps", "manager_name": "Didier Deschamps"}],
                ["team", "manager_id", "manager_name"],
            )
            write_csv(
                summaries,
                [
                    {
                        "match_id": "M1",
                        "team": "France",
                        "xg": 1.8,
                        "shots": 12,
                        "field_tilt": 0.61,
                        "box_entries": 14,
                        "set_piece_xg": 0.3,
                        "counterattack_xg": 0.4,
                        "pressing_proxy": 68,
                    },
                    {"match_id": "M1", "team": "Brazil", "xg": 0.9, "pressing_proxy": 42},
                ],
                ["match_id", "team", "xg", "shots", "field_tilt", "box_entries", "set_piece_xg", "counterattack_xg", "pressing_proxy"],
            )
            write_csv(
                lineups,
                [{"match_id": "M1", "team": "France", "formation": "4-2-3-1"}],
                ["match_id", "team", "formation"],
            )
            write_csv(
                events,
                [{"match_id": "M1", "team": "France", "event_type": "substitution"}],
                ["match_id", "team", "event_type"],
            )

            observations = build_manager_match_observations(
                observed_matches_path=observed,
                managers_path=managers,
                summaries_path=summaries,
                lineups_path=lineups,
                events_path=events,
            )
            france = next(row for row in observations if row["team"] == "France")
            self.assertEqual(france["manager_id"], "france_deschamps")
            self.assertEqual(france["actual_formation"], "4-2-3-1")
            self.assertEqual(france["data_quality"], "observed_events_and_confirmed_lineup")
            self.assertEqual(france["substitutions"], 1)

            signals = build_formation_prediction_signals(observations)
            france_signal = next(row for row in signals if row["team"] == "France")
            self.assertEqual(france_signal["last_confirmed_formation"], "4-2-3-1")
            self.assertGreater(float(france_signal["formation_confidence"]), 0.8)

            write_manager_match_observations(observations, root / "manager_obs.csv")
            write_formation_prediction_signals(signals, root / "formation_signals.csv")
            with (root / "manager_obs.csv").open(newline="", encoding="utf-8") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 2)
            with (root / "formation_signals.csv").open(newline="", encoding="utf-8") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 2)

    def test_fixture_context_adds_travel_distance_and_thermal_comfort(self) -> None:
        teams = load_teams()
        route_state = {
            "France": {"last_venue": "Boston", "last_kickoff": "2026-06-20T20:00:00+00:00", "last_match_id": "42"},
            "Brazil": {"last_venue": "Dallas", "last_kickoff": "2026-06-21T20:00:00+00:00", "last_match_id": "43"},
        }
        fixture = {
            "match_id": 99,
            "stage": "Quarterfinals",
            "venue": "Miami",
            "kickoff_utc": "2026-07-05T20:00:00+00:00",
            "kickoff_local": "2026-07-05T16:00:00-04:00",
            "venue_source": "published-schedule",
        }
        context = automatic_fixture_context({"weather": "auto"}, fixture, teams["France"], teams["Brazil"], route_state)

        self.assertIn("team_travel_distance_km", context)
        self.assertGreater(context["team_travel_distance_km"]["France"], 0)
        self.assertIn("thermal_comfort", context)
        self.assertIsNotNone(context["thermal_comfort"]["France"]["temperature_c"])

    def test_event_and_thermal_signals_are_bounded_and_explainable(self) -> None:
        teams = load_teams()
        context = {
            "weather": "heat",
            "venue_weather": {
                "venue": {"venue": "Miami", "altitude_m": 2},
                "current": {"temperature_2m": 32.0},
            },
        }
        thermal = thermal_comfort_signal(teams["England"], teams["Brazil"], context)
        event = detailed_match_event_signal(teams["France"], teams["Brazil"])

        self.assertEqual(thermal["label"], "Thermal comfort")
        self.assertGreaterEqual(thermal["xg_delta"], -0.045)
        self.assertLessEqual(thermal["xg_delta"], 0.045)
        self.assertEqual(event["label"], "Observed match events")
        self.assertIn("detail", event)


if __name__ == "__main__":
    unittest.main()
