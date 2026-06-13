from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.future_data import (
    EvaluateMatchRequest,
    get_injury_status,
    get_lineup_delta,
    get_manager_evidence,
    get_match_evaluation,
    get_model_evaluation,
    get_player_availability,
    get_player_role_vector,
    get_role_depth,
)


class FutureDataTests(unittest.TestCase):
    def test_player_role_vector_combines_role_and_form_surfaces(self) -> None:
        payload = get_player_role_vector("france_kylian_mbappe")

        self.assertTrue(payload["found"])
        self.assertEqual(payload["team"], "France")
        self.assertTrue(payload["roles"])
        self.assertIsNotNone(payload["form"])

    def test_injury_status_filters_by_team(self) -> None:
        payload = get_injury_status("France")

        self.assertTrue(payload["available"])
        self.assertTrue(all(row["team"] == "France" for row in payload["signals"]))

    def test_player_availability_read_surface(self) -> None:
        payload = get_player_availability("france_kylian_mbappe")

        self.assertTrue(payload["found"])
        self.assertEqual(payload["availability"]["team"], "France")

    def test_team_role_depth_read_surface(self) -> None:
        payload = get_role_depth("France")

        self.assertTrue(payload["found"])
        self.assertGreater(payload["players"], 0)
        self.assertTrue(payload["roles"])

    def test_manager_evidence_is_reviewable(self) -> None:
        payload = get_manager_evidence("france_deschamps")

        self.assertTrue(payload["found"])
        self.assertTrue(payload["evidence"])
        self.assertTrue(all(update["evidence_ids"] for update in payload["suggested_updates"]))

    def test_lineup_delta_uses_projection_fallback_without_confirmed_xi(self) -> None:
        payload = get_lineup_delta("France")

        self.assertFalse(payload["available"])
        self.assertTrue(payload["projected_starters"])
        self.assertIn("No confirmed starting XI", payload["fallback_note"])

    def test_match_evaluation_read_surface(self) -> None:
        payload = get_match_evaluation("FRA-BRA-TEST")

        self.assertTrue(payload["found"])
        self.assertTrue(payload["model"])
        self.assertTrue(payload["managers"])
        self.assertTrue(payload["matchups"])

    def test_model_evaluation_read_surface(self) -> None:
        payload = get_model_evaluation()

        self.assertTrue(payload["found"])
        self.assertGreater(payload["summary"]["matches"], 0)
        self.assertIsNotNone(payload["summary"]["average_brier_score"])

    def test_partial_manual_evaluation_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            EvaluateMatchRequest(match_id="test", team_a="France")


if __name__ == "__main__":
    unittest.main()
