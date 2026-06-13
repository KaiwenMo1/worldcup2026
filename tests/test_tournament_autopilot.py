from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.tournament_autopilot import ObservedMatch, provider_rows_to_observed, upsert_observed_matches


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
