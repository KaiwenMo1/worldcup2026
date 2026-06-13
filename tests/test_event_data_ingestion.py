from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.ingestion.event_data_ingestion import (
    MatchEvent,
    MatchEventType,
    ManualCsvEventAdapter,
    build_match_summary_signals,
    ingest_event_data,
    load_match_summary_signals,
    load_normalized_events,
    normalize_event_type,
    write_match_summary_signals,
    write_normalized_events,
)
from scripts.predict_worldcup import load_teams, match_probabilities


UPDATED = datetime(2026, 6, 12, 12, tzinfo=timezone.utc)


def event(
    event_id: str,
    team: str,
    event_type: MatchEventType,
    *,
    opponent: str,
    x: float | None = None,
    y: float | None = None,
    end_x: float | None = None,
    end_y: float | None = None,
    xg: float | None = None,
    is_goal: bool = False,
    is_set_piece: bool = False,
    is_counterattack: bool = False,
    outcome: str = "",
) -> MatchEvent:
    return MatchEvent(
        event_id=event_id,
        match_id="test-match",
        match_date="2026-06-12",
        team=team,
        opponent=opponent,
        player="Test Player",
        event_type=event_type,
        minute=10,
        outcome=outcome,
        x=x,
        y=y,
        end_x=end_x,
        end_y=end_y,
        xg=xg,
        is_goal=is_goal,
        is_set_piece=is_set_piece,
        is_counterattack=is_counterattack,
        goalkeeper="Test Keeper" if event_type == MatchEventType.SAVE else "",
        source="manual_csv",
        source_event_type=event_type.value,
        source_confidence=0.8,
        updated_at=UPDATED,
    )


class EventDataIngestionTests(unittest.TestCase):
    def test_supported_event_vocabulary_is_complete(self) -> None:
        required = {
            "shot",
            "goal",
            "pass",
            "key_pass",
            "progressive_pass",
            "carry",
            "progressive_carry",
            "cross",
            "tackle",
            "interception",
            "duel",
            "aerial_duel",
            "foul",
            "card",
            "substitution",
            "set_piece",
            "corner",
            "penalty",
            "save",
        }

        self.assertEqual({item.value for item in MatchEventType}, required)
        self.assertEqual(normalize_event_type("Goalkeeper Save"), MatchEventType.SAVE)
        self.assertEqual(normalize_event_type("Foul Committed"), MatchEventType.FOUL)

    def test_custom_provider_aliases_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provider.csv"
            path.write_text(
                "provider_game,country,event_kind,clock,provider_id\n"
                "match-1,France,Pass,7,event-1\n",
                encoding="utf-8",
            )
            aliases = {
                "match_id": ("provider_game",),
                "team": ("country",),
                "event_type": ("event_kind",),
                "minute": ("clock",),
                "event_id": ("provider_id",),
            }

            result = ingest_event_data(ManualCsvEventAdapter(path, field_aliases=aliases))

            self.assertEqual(len(result.events), 1)
            self.assertEqual(result.events[0].event_type, MatchEventType.PASS)
            self.assertTrue(all(issue.severity.value == "info" for issue in result.issues))

    def test_bad_event_is_rejected_but_missing_optional_fields_are_informational(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.csv"
            fields = ["match_id", "team", "event_type", "minute", "player", "x", "y", "end_x", "end_y"]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"match_id": "m1", "team": "France", "event_type": "pass", "minute": "5", "player": "A", "x": "10", "y": "20", "end_x": "50"})
                writer.writerow({"match_id": "m1", "team": "France", "event_type": "dance", "minute": "6"})

            result = ingest_event_data(ManualCsvEventAdapter(path))

            self.assertEqual(len(result.events), 1)
            self.assertTrue(any(issue.severity.value == "info" and issue.field == "end_y" for issue in result.issues))
            self.assertTrue(any(issue.severity.value == "error" and issue.field == "event_type" for issue in result.issues))

    def test_match_summary_metrics_are_transparent(self) -> None:
        events = [
            event("f-pass", "France", MatchEventType.PROGRESSIVE_PASS, opponent="Brazil", x=75, y=40, end_x=105, end_y=40),
            event("f-goal", "France", MatchEventType.GOAL, opponent="Brazil", x=108, y=40, xg=0.5, is_goal=True, is_counterattack=True, outcome="Goal"),
            event("f-tackle", "France", MatchEventType.TACKLE, opponent="Brazil", x=85, y=40),
            event("f-save", "France", MatchEventType.SAVE, opponent="Brazil", xg=0.25, outcome="Saved"),
            event("b-pass", "Brazil", MatchEventType.PASS, opponent="France", x=30, y=40, end_x=50, end_y=40),
            event("b-shot", "Brazil", MatchEventType.SHOT, opponent="France", x=110, y=40, xg=0.25, outcome="Saved"),
            event("b-set-shot", "Brazil", MatchEventType.SHOT, opponent="France", x=108, y=42, xg=0.15, is_set_piece=True, outcome="Off Target"),
        ]

        summaries = {summary.team: summary for summary in build_match_summary_signals(events, updated_at=UPDATED)}
        france = summaries["France"]
        brazil = summaries["Brazil"]

        self.assertEqual(france.goals, 1)
        self.assertEqual(france.xg, 0.5)
        self.assertEqual(france.box_entries, 1)
        self.assertEqual(france.counterattack_xg, 0.5)
        self.assertEqual(france.xg_faced, 0.4)
        self.assertEqual(france.goalkeeper_impact, 0.4)
        self.assertEqual(brazil.set_piece_xg, 0.15)
        self.assertAlmostEqual(france.field_tilt + brazil.field_tilt, 1.0, places=3)
        self.assertTrue(0 <= france.pressing_proxy <= 100)

    def test_normalized_events_and_summaries_round_trip(self) -> None:
        events = [
            event("f-shot", "France", MatchEventType.SHOT, opponent="Brazil", x=110, y=40, xg=0.25, outcome="Saved"),
            event("b-save", "Brazil", MatchEventType.SAVE, opponent="France", xg=0.25, outcome="Saved"),
        ]
        signals = build_match_summary_signals(events, updated_at=UPDATED)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_issues = [
                *write_normalized_events(events, root / "events.csv"),
                *write_match_summary_signals(signals, root / "summary.csv"),
            ]
            loaded_events, event_issues = load_normalized_events(root / "events.csv")
            loaded_signals, signal_issues = load_match_summary_signals(root / "summary.csv")

            self.assertFalse(write_issues or event_issues or signal_issues)
            self.assertEqual(loaded_events[0].event_id, "f-shot")
            self.assertEqual(len(loaded_signals), 2)

    def test_event_summary_does_not_change_match_probabilities(self) -> None:
        teams = load_teams()
        before = match_probabilities(teams["France"], teams["Brazil"])

        build_match_summary_signals(
            [event("f-goal", "France", MatchEventType.GOAL, opponent="Brazil", xg=0.5, is_goal=True)],
            updated_at=UPDATED,
        )
        after = match_probabilities(teams["France"], teams["Brazil"])

        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
