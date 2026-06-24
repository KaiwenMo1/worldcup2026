from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sync_squads  # noqa: E402


class SyncSquadsResilienceTests(unittest.TestCase):
    def test_optional_fetch_returns_empty_instead_of_crashing_after_gateway_timeout(self) -> None:
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError("504 Server Error: Gateway Time-out")

        with patch.object(sync_squads.requests, "get", return_value=response), patch.object(sync_squads.time, "sleep"):
            self.assertEqual(sync_squads.fetch("https://example.test/team", optional=True, retries=1), "")

    def test_market_values_skips_failed_team_pages_and_keeps_world_cup_page_values(self) -> None:
        world_cup_table = """
        <table>
          <tr><th>#</th><th>Player</th><th>Market value</th><th>Last update</th></tr>
          <tr><td>1</td><td>Neymar Left Winger</td><td>€30.00m</td><td>Jun 1, 2026</td></tr>
        </table>
        """
        participants = """
        <a href="/brasilien/startseite/verein/3439">Brazil</a>
        """

        def fake_fetch(url: str, *, optional: bool = False, retries: int = 2) -> str:
            if "marktwerte" in url:
                return world_cup_table
            if "teilnehmer" in url:
                return participants
            self.assertTrue(optional)
            return ""

        with patch.object(sync_squads, "fetch", side_effect=fake_fetch):
            values = sync_squads.market_values(1, include_team_pages=True)

        self.assertEqual(values["neymar"]["market_value_eur"], 30_000_000)
        self.assertEqual(values["neymar"]["detailed_position"], "Left Winger")


if __name__ == "__main__":
    unittest.main()
