#!/usr/bin/env python3
"""Smoke test manager observation outputs."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.manager_observation_ingestion import (
    build_formation_prediction_signals,
    build_manager_match_observations,
)


def main() -> None:
    observations = build_manager_match_observations()
    signals = build_formation_prediction_signals(observations)
    print(f"observations={len(observations)} formation_signals={len(signals)}")
    for row in signals[:5]:
        print(
            row["team"],
            row["matches_observed"],
            row["last_confirmed_formation"] or "formation_pending",
            row["data_quality"],
        )


if __name__ == "__main__":
    main()
