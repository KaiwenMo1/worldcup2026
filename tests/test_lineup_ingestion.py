from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.ingestion.lineup_ingestion import (
    CsvLineupAdapter,
    build_lineup_delta_signals,
    ingest_lineups,
    write_actual_lineups,
    write_lineup_delta_signals,
)


class LineupIngestionTests(unittest.TestCase):
    def test_confirmed_starters_create_transparent_delta(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "lineups.csv"
            source.write_text(
                "match_id,team,formation,player_id,player,starter,confirmed,source,source_confidence,updated_at\n"
                "M1,France,4-2-3-1,france_kylian_mbappe,Kylian Mbappe,1,1,test,0.9,2026-06-12T12:00:00Z\n",
                encoding="utf-8",
            )
            projected = root / "projected.csv"
            projected.write_text(
                "match_id,team,formation,player_id,player,starter_probability\n"
                ",France,4-3-3,france_kylian_mbappe,Kylian Mbappe,0.9\n"
                ",France,4-3-3,france_mike_maignan,Mike Maignan,0.9\n",
                encoding="utf-8",
            )
            vectors = root / "vectors.csv"
            vectors.write_text(
                "player_id,position,role_fit_score,pressing_score,creation_score,set_piece_score,defending_score\n"
                "france_kylian_mbappe,LW,90,40,85,50,20\n"
                "france_mike_maignan,GK,80,20,30,20,90\n",
                encoding="utf-8",
            )
            result = ingest_lineups(CsvLineupAdapter(source))
            signals, issues = build_lineup_delta_signals(
                result.records,
                projected_path=projected,
                role_vectors_path=vectors,
            )
            self.assertEqual(len(result.records), 1)
            self.assertEqual(len(signals), 1)
            self.assertTrue(signals[0].formation_changed)
            self.assertEqual(signals[0].missing_projected_starters, ["Mike Maignan"])
            self.assertEqual(issues, [])
            self.assertEqual(write_actual_lineups(result.records, root / "actual.csv"), [])
            self.assertEqual(write_lineup_delta_signals(signals, root / "deltas.csv"), [])

    def test_unconfirmed_rows_do_not_become_actual_lineups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "lineups.csv"
            source.write_text(
                "match_id,team,player,starter,confirmed\n"
                "M1,France,Kylian Mbappe,1,0\n",
                encoding="utf-8",
            )
            result = ingest_lineups(CsvLineupAdapter(source))
            self.assertEqual(result.records, [])
            self.assertTrue(result.issues)


if __name__ == "__main__":
    unittest.main()
