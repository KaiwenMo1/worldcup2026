from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from app.ingestion.event_data_ingestion import MatchEvent, MatchEventType
from app.ingestion.lineup_ingestion import ActualLineupPlayer
from app.ingestion.player_stats_ingestion import PlayerMatchStat
from app.ingestion.postmatch_player_ingestion import (
    build_live_player_team_features,
    build_player_match_stats_from_events,
    build_player_postmatch_signals,
    merge_player_match_stats,
    write_live_player_team_features,
    write_player_match_stats,
    write_player_postmatch_signals,
)


UPDATED = datetime(2026, 6, 28, 12, tzinfo=timezone.utc)


def event(
    event_id: str,
    player: str,
    event_type: MatchEventType,
    minute: int,
    *,
    related_player: str = "",
    outcome: str = "Complete",
    xg: float | None = None,
    is_goal: bool = False,
    goalkeeper: str = "",
) -> MatchEvent:
    return MatchEvent(
        event_id=event_id,
        match_id="42",
        match_date=date(2026, 6, 28),
        competition="FIFA World Cup",
        team="France",
        opponent="Brazil",
        player=player,
        related_player=related_player,
        event_type=event_type,
        period=1 if minute <= 45 else 2,
        minute=minute,
        second=0,
        possession_id=event_id,
        possession_team="France",
        play_pattern="Open Play",
        outcome=outcome,
        x=108 if event_type in {MatchEventType.SHOT, MatchEventType.GOAL} else 80,
        y=40,
        xg=xg,
        is_goal=is_goal,
        goalkeeper=goalkeeper,
        source="unit_test",
        source_event_type=event_type.value,
        source_confidence=0.9,
        updated_at=UPDATED,
    )


class PostmatchPlayerIngestionTests(unittest.TestCase):
    def test_events_build_player_stats_ratings_and_team_overlay(self) -> None:
        events = [
            event("e1", "Kylian Mbappe", MatchEventType.GOAL, 18, related_player="Ousmane Dembele", xg=0.42, is_goal=True),
            event("e2", "Kylian Mbappe", MatchEventType.SHOT, 35, outcome="Saved", xg=0.18, goalkeeper="Alisson"),
            event("e3", "Ousmane Dembele", MatchEventType.KEY_PASS, 35),
            event("e4", "Aurelien Tchouameni", MatchEventType.TACKLE, 54, outcome="Won"),
            event("e5", "Mike Maignan", MatchEventType.SAVE, 76, outcome="Saved", xg=0.25, goalkeeper="Mike Maignan"),
            event("e6", "Kylian Mbappe", MatchEventType.SUBSTITUTION, 84),
        ]
        lineups = [
            ActualLineupPlayer(
                match_id="42",
                team="France",
                opponent="Brazil",
                formation="4-3-3",
                player_id="france_kylian_mbappe",
                player="Kylian Mbappe",
                position="LW",
                starter=True,
                confirmed=True,
                source="unit_test",
                source_confidence=0.9,
                updated_at=UPDATED,
            )
        ]

        with tempfile.TemporaryDirectory() as directory:
            observed = Path(directory) / "observed.csv"
            observed.write_text(
                "match_id,team_a,team_b,team_a_score,team_b_score,kickoff_utc\n"
                "42,France,Brazil,2,1,2026-06-28T21:00:00Z\n",
                encoding="utf-8",
            )
            stats = build_player_match_stats_from_events(events, lineups, observed_matches_path=observed, updated_at=UPDATED)
            by_player = {row.player: row for row in stats}
            self.assertEqual(by_player["Kylian Mbappe"].goals, 1)
            self.assertEqual(by_player["Kylian Mbappe"].assists, 0)
            self.assertEqual(by_player["Ousmane Dembele"].assists, 1)
            self.assertEqual(by_player["Kylian Mbappe"].minutes, 84)

            merged = merge_player_match_stats([], stats)
            signals = build_player_postmatch_signals(merged, events, updated_at=UPDATED)
            rating = next(row for row in signals if row.player == "Kylian Mbappe")
            self.assertGreater(rating.player_rating, 6.5)

            team_rows = build_live_player_team_features(signals, baseline_path=Path(directory) / "missing.csv")
            self.assertEqual(team_rows[0]["team"], "France")
            self.assertGreater(team_rows[0]["player_shooting_score"], 65)

            self.assertFalse(write_player_match_stats(merged, Path(directory) / "player_matches.csv"))
            self.assertFalse(write_player_postmatch_signals(signals, Path(directory) / "player_signals.csv"))
            self.assertFalse(write_live_player_team_features(team_rows, Path(directory) / "team_overlay.csv"))


if __name__ == "__main__":
    unittest.main()
