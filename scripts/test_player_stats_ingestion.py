#!/usr/bin/env python3
"""Smoke-test manual player-stat ingestion and transparent role derivation."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingestion.player_stats_ingestion import (  # noqa: E402
    MANUAL_SAMPLE_PATH,
    ManualCsvPlayerStatsAdapter,
    build_form_signals,
    build_role_vectors,
    ingest_player_stats,
    write_derived_outputs,
    write_normalized_stats,
)


def main() -> None:
    result = ingest_player_stats(ManualCsvPlayerStatsAdapter(MANUAL_SAMPLE_PATH))
    assert result.season_stats and result.match_stats
    assert not result.issues
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        assert not write_normalized_stats(result, root / "season.csv", root / "matches.csv")
        signals = build_form_signals(result.match_stats, result.season_stats)
        vectors, issues = build_role_vectors(result.season_stats, signals)
        assert vectors and signals and not issues
        assert not write_derived_outputs(vectors, signals, root / "roles.csv", root / "form.csv")
        print(f"Player stats smoke test passed: season={len(result.season_stats)}, matches={len(result.match_stats)}, roles={len(vectors)}")


if __name__ == "__main__":
    main()
