from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.prediction_arena.prediction_runner import run_prediction_arena
from app.prediction_arena.public_card_renderer import (
    build_public_card_from_records,
    publish_public_prediction_card,
    render_public_card_markdown,
)
from app.prediction_arena.public_ledger import load_predictions
from app.prediction_arena.schemas import PredictionStatus


FORECAST = {
    "expected_score": {"team_a": 1.42, "team_b": 1.08},
    "probabilities": {"team_a_win": 44.0, "draw": 29.0, "team_b_win": 27.0},
    "scorelines": [
        {"team_a_score": 1, "team_b_score": 1, "probability": 13.0},
        {"team_a_score": 1, "team_b_score": 0, "probability": 12.5},
        {"team_a_score": 2, "team_b_score": 1, "probability": 9.5},
    ],
}
BRIEF = {
    "top_matchup_edges": [
        {
            "matchup_type": "winger_vs_fullback",
            "team_a_player": "France LW",
            "team_b_player": "Brazil RB",
            "favored_team": "France",
            "edge_score": 0.67,
            "reason": "France can repeatedly isolate Brazil's right back.",
        }
    ],
    "tactical_summary": "France has the clearer transition route, but Brazil can slow the game.",
}


def forecast_provider(team_a: str, team_b: str):
    return FORECAST


def brief_provider(team_a: str, team_b: str, match_id: str, forecast):
    return BRIEF


class PredictionRunnerTests(unittest.TestCase):
    def test_locked_published_run_is_versioned_and_persists_prediction_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pre_match = root / "ledgers" / "pre_match.csv"
            models = root / "ledgers" / "models.csv"
            cards = root / "cards"
            card_ledger = root / "ledgers" / "cards.csv"

            first = run_prediction_arena(
                "M001",
                "France",
                "Brazil",
                "knockout",
                lock=True,
                publish_card=True,
                forecast_provider=forecast_provider,
                tactical_brief_provider=brief_provider,
                pre_match_path=pre_match,
                model_path=models,
                cards_dir=cards,
                card_ledger_path=card_ledger,
            )

            self.assertEqual(first.version, 1)
            self.assertEqual(len(first.prediction_records), 4)
            self.assertEqual(len(first.model_records), 1)
            self.assertTrue(all(record.status == PredictionStatus.LOCKED for record in first.prediction_records))
            self.assertTrue(all(record.status == PredictionStatus.LOCKED for record in first.model_records))
            self.assertEqual(len(load_predictions(pre_match)), 4)
            self.assertEqual(len(load_predictions(models)), 1)
            self.assertEqual(len(first.game_state_paths), 4)
            self.assertTrue(
                all(
                    event["is_observed"] is False and event["allowed_to_cascade"] is False
                    for path in first.game_state_paths
                    for event in path["simulated_events"]
                )
            )
            self.assertTrue(
                any(item.startswith("Conditional branch:") for item in first.final_forecast.what_to_watch)
            )
            card_path = Path(first.public_card_path)
            self.assertEqual(card_path, cards / "M001.md")
            markdown = card_path.read_text(encoding="utf-8")
            self.assertIn("**90 minutes:** France", markdown)
            self.assertIn("**Qualification:** France advance", markdown)
            self.assertIn("**Kevin Agent:**", markdown)
            self.assertIn("**Expert Agent:**", markdown)
            self.assertIn("**Upset path:**", markdown)
            self.assertIn("not betting advice", markdown)

            second = run_prediction_arena(
                "M001",
                "France",
                "Brazil",
                "knockout",
                lock=True,
                forecast_provider=forecast_provider,
                tactical_brief_provider=brief_provider,
                pre_match_path=pre_match,
                model_path=models,
            )

            self.assertEqual(second.version, 2)
            self.assertEqual(len(load_predictions(pre_match)), 8)
            self.assertEqual(len(load_predictions(models)), 2)
            self.assertTrue(all(record.version == 1 for record in load_predictions(pre_match)[:4]))
            self.assertTrue(all(record.status == PredictionStatus.LOCKED for record in load_predictions(pre_match)))

    def test_latest_saved_version_can_be_published_without_rerunning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pre_match = root / "pre_match.csv"
            models = root / "models.csv"
            cards = root / "cards"
            card_ledger = root / "cards.csv"
            run_prediction_arena(
                "M002",
                "France",
                "Brazil",
                "group",
                forecast_provider=forecast_provider,
                tactical_brief_provider=brief_provider,
                pre_match_path=pre_match,
                model_path=models,
            )
            card = build_public_card_from_records("M002", ledger_path=pre_match)
            path = publish_public_prediction_card(card, cards_dir=cards, ledger_path=card_ledger)
            markdown = render_public_card_markdown(card)

            self.assertEqual(path, cards / "M002.md")
            self.assertNotIn("Qualification:", markdown)
            self.assertIn("## Fragile Assumptions", markdown)
            self.assertIn("## What To Watch", markdown)

    def test_missing_optional_providers_fall_back_without_model_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def unavailable(*args):
                raise RuntimeError("not available")

            with patch(
                "app.prediction_arena.prediction_runner.run_configured_model_arena",
                return_value=([], []),
            ):
                result = run_prediction_arena(
                    "M003",
                    "France",
                    "Brazil",
                    "group",
                    forecast_provider=unavailable,
                    tactical_brief_provider=unavailable,
                    pre_match_path=root / "pre_match.csv",
                    model_path=root / "models.csv",
                )

            self.assertIsNone(result.base_forecast)
            self.assertIsNone(result.tactical_brief)
            self.assertEqual(len(result.prediction_records), 4)
            self.assertEqual(result.model_records, [])
            self.assertEqual(len(result.fallback_notes), 2)
            self.assertIsNone(result.final_forecast.final_prediction.qualification)


if __name__ == "__main__":
    unittest.main()
