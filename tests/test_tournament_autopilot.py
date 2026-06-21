from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.tournament_autopilot import (
    ObservedMatch,
    fifa_row_to_current_match,
    fifa_rows_to_observed,
    provider_rows_to_observed,
    upsert_observed_matches,
)


class TournamentAutopilotTests(unittest.TestCase):
    def test_provider_final_is_normalized_to_fixture(self) -> None:
        rows = provider_rows_to_observed(
            [
                {
                    "id": "provider-1",
                    "status": "final",
                    "home_team": {"name": "Mexico"},
                    "away_team": {"name": "South Africa"},
                    "home_score": 2,
                    "away_score": 0,
                }
            ]
        )
        self.assertEqual(rows[0].match_id, "1")
        self.assertEqual(rows[0].team_a_score, 2)

    def test_fifa_official_final_is_normalized(self) -> None:
        rows = fifa_rows_to_observed(
            [
                {
                    "IdMatch": "400021443",
                    "MatchNumber": 1,
                    "Date": "2026-06-11T19:00:00Z",
                    "StageName": [{"Locale": "en-GB", "Description": "First Stage"}],
                    "GroupName": [{"Locale": "en-GB", "Description": "Group A"}],
                    "Home": {"Score": 2, "TeamName": [{"Locale": "en-GB", "Description": "Mexico"}]},
                    "Away": {"Score": 0, "TeamName": [{"Locale": "en-GB", "Description": "South Africa"}]},
                    "ResultType": 1,
                }
            ]
        )
        self.assertEqual(rows[0].match_id, "1")
        self.assertEqual(rows[0].stage, "Group")
        self.assertEqual(rows[0].group, "A")
        self.assertEqual(rows[0].provider_match_id, "400021443")
        self.assertEqual(rows[0].source, "fifa_official_calendar_api")

    def test_fifa_live_score_stays_out_of_observed_matches(self) -> None:
        row = {
            "IdMatch": "400021465",
            "MatchNumber": 34,
            "Date": "2026-06-21T00:00:00Z",
            "StageName": [{"Locale": "en-GB", "Description": "First Stage"}],
            "GroupName": [{"Locale": "en-GB", "Description": "Group E"}],
            "Home": {"Score": 0, "TeamName": [{"Locale": "en-GB", "Description": "Ecuador"}]},
            "Away": {"Score": 0, "TeamName": [{"Locale": "en-GB", "Description": "Curaçao"}]},
            "ResultType": 0,
            "MatchStatus": 3,
            "MatchTime": "79'",
        }
        self.assertEqual(fifa_rows_to_observed([row]), [])
        current = fifa_row_to_current_match(row)
        self.assertEqual(current["status"], "live")
        self.assertEqual(current["team_b"], "Curacao")

    def test_lower_confidence_update_cannot_replace_verified_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observed.csv"
            at = datetime(2026, 6, 12, tzinfo=timezone.utc)
            verified = ObservedMatch(
                match_id="1",
                team_a="Mexico",
                team_b="South Africa",
                team_a_score=2,
                team_b_score=0,
                source="verified",
                source_confidence=0.95,
                updated_at=at,
            )
            weak = verified.model_copy(
                update={"team_a_score": 1, "source": "weak", "source_confidence": 0.3}
            )
            upsert_observed_matches([verified], path)
            rows, new_ids = upsert_observed_matches([weak], path)
            self.assertEqual(new_ids, [])
            self.assertEqual(rows[0].team_a_score, 2)


if __name__ == "__main__":
    unittest.main()
