from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.ingestion.player_stats_ingestion import (
    MATCH_FIELDS,
    ROLE_WEIGHTS,
    SEASON_FIELDS,
    ManualCsvPlayerStatsAdapter,
    PlayerMatchStat,
    PlayerSeasonStat,
    build_form_signals,
    build_role_vectors,
    ingest_player_stats,
    load_normalized_match_stats,
    load_normalized_season_stats,
    write_derived_outputs,
    write_normalized_stats,
)


UPDATED = datetime(2026, 6, 11, 12, tzinfo=timezone.utc)


def season_stat(player_id: str = "test_forward", position: str = "FW") -> PlayerSeasonStat:
    return PlayerSeasonStat(
        player_id=player_id,
        player="Test Player",
        team="Test Team",
        national_team="Test Team",
        club="Test Club",
        season="2025-26",
        competition="Test League",
        position=position,
        minutes=1800,
        goals=16 if position != "GK" else 0,
        assists=7,
        shots=70,
        shots_on_target=35,
        xg=14,
        xa=6,
        key_passes=42,
        progressive_passes=100,
        progressive_carries=110,
        passes_completed=700,
        passes_attempted=850,
        pass_completion=0.824,
        dribbles_completed=50,
        dribbles_attempted=85,
        tackles=25,
        interceptions=15,
        pressures=240,
        aerials_won=24,
        aerials_lost=20,
        saves=55 if position == "GK" else 0,
        goals_conceded=20 if position == "GK" else 0,
        source="manual_csv",
        source_confidence=0.8,
        updated_at=UPDATED,
    )


def match_stat(index: int, goals: int = 1) -> PlayerMatchStat:
    return PlayerMatchStat(
        match_id=f"match-{index}",
        player_id="test_forward",
        player="Test Player",
        team="Test Team",
        opponent="Opponent",
        date=f"2026-06-{index:02d}",
        competition="Test",
        position="FW",
        started=True,
        minutes=90,
        goals=goals,
        assists=1,
        xg=0.7,
        xa=0.3,
        shots=4,
        shots_on_target=2,
        key_passes=2,
        progressive_passes=4,
        progressive_carries=5,
        duels_won=5,
        duels_lost=3,
        pressures=10,
        tackles=1,
        interceptions=0,
        aerials_won=1,
        aerials_lost=1,
        source="manual_csv",
        source_confidence=0.8,
        updated_at=UPDATED,
    )


class PlayerStatsIngestionTests(unittest.TestCase):
    def test_manual_adapter_keeps_valid_rows_and_reports_invalid_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manual.csv"
            fields = ["record_type", *dict.fromkeys([*SEASON_FIELDS, *MATCH_FIELDS])]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"record_type": "season", **season_stat().model_dump(mode="json")})
                writer.writerow(
                    {
                        "record_type": "season",
                        **season_stat("bad").model_dump(mode="json"),
                        "minutes": "-1",
                        "pass_completion": "2",
                    }
                )

            result = ingest_player_stats(ManualCsvPlayerStatsAdapter(path))

            self.assertEqual(len(result.season_stats), 1)
            self.assertEqual(len(result.match_stats), 0)
            self.assertGreaterEqual(len(result.issues), 2)
            self.assertTrue(all(issue.row_number == 3 for issue in result.issues))

    def test_normalized_outputs_round_trip_through_shared_csv_foundation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = type("Result", (), {"season_stats": [season_stat()], "match_stats": [match_stat(1)]})()

            issues = write_normalized_stats(result, root / "season.csv", root / "match.csv")
            seasons, season_issues = load_normalized_season_stats(root / "season.csv")
            matches, match_issues = load_normalized_match_stats(root / "match.csv")

            self.assertFalse(issues or season_issues or match_issues)
            self.assertEqual(seasons[0].player_id, "test_forward")
            self.assertEqual(matches[0].match_id, "match-1")

    def test_role_engine_supports_required_archetypes(self) -> None:
        required = {
            "inverted_winger",
            "target_striker",
            "deep_lying_playmaker",
            "ball_winning_midfielder",
            "overlapping_fullback",
            "ball_playing_centerback",
            "shot_stopper",
        }

        self.assertTrue(required.issubset(ROLE_WEIGHTS))

    def test_compact_positions_receive_position_appropriate_roles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile_path = Path(directory) / "profiles.csv"
            profile_path.write_text(
                "player_id,player,team,primary_position,role_archetypes,source\n"
                "centerback,Center Back,Test Team,CB,ball_playing_centerback|ball_playing_centerback,manual\n"
                "midfielder,Midfielder,Test Team,DM,ball_winning_midfielder,manual\n",
                encoding="utf-8",
            )

            vectors, issues = build_role_vectors([], [], curated_profiles_path=profile_path, updated_at=UPDATED)

            self.assertFalse(issues)
            roles = {(vector.player_id, vector.role_archetype) for vector in vectors}
            self.assertEqual(roles, {("centerback", "ball_playing_centerback"), ("midfielder", "ball_winning_midfielder")})

    def test_role_vectors_use_observed_stats_and_curated_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile_path = Path(directory) / "profiles.csv"
            profile_path.write_text(
                "player_id,player,team,primary_position,role_archetypes,finishing,chance_creation,progression,passing,dribbling,press_resistance,pressing,tackling,recovery,aerial,pace,set_piece_delivery,source\n"
                "fallback_player,Fallback Player,Test Team,CM,deep_lying_playmaker,50,70,80,86,65,82,70,68,74,55,60,72,manual\n",
                encoding="utf-8",
            )
            signals = build_form_signals([], [season_stat()])

            vectors, issues = build_role_vectors([season_stat()], signals, curated_profiles_path=profile_path, updated_at=UPDATED)

            self.assertFalse(issues)
            self.assertTrue(any(vector.player_id == "test_forward" and vector.data_quality == "observed_season_stats" for vector in vectors))
            self.assertTrue(any(vector.player_id == "fallback_player" and vector.data_quality == "manual_profile_fallback" for vector in vectors))
            self.assertTrue(all(0 <= vector.role_fit_score <= 100 for vector in vectors))

    def test_recent_matches_override_season_baseline_form(self) -> None:
        matches = [match_stat(index) for index in range(1, 7)]

        signals = build_form_signals(matches, [season_stat()], updated_at=UPDATED)

        signal = signals[0]
        self.assertEqual(signal.recent_matches, 5)
        self.assertEqual(signal.data_quality, "observed_recent_matches")
        self.assertGreater(signal.confidence, 0.7)

    def test_derived_outputs_are_written_with_stable_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signals = build_form_signals([match_stat(1)], [season_stat()], updated_at=UPDATED)
            vectors, _ = build_role_vectors([season_stat()], signals, curated_profiles_path=root / "missing.csv", updated_at=UPDATED)

            issues = write_derived_outputs(vectors, signals, root / "roles.csv", root / "forms.csv")

            self.assertTrue((root / "roles.csv").exists())
            self.assertTrue((root / "forms.csv").exists())
            self.assertTrue(all(issue.severity.value == "warning" for issue in issues))


if __name__ == "__main__":
    unittest.main()
