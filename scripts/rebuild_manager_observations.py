#!/usr/bin/env python3
"""Rebuild manager observation and formation-trend outputs."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.manager_observation_ingestion import rebuild_manager_observation_outputs


def main() -> None:
    observations, formation_signals = rebuild_manager_observation_outputs()
    print(f"Manager observations: {observations}")
    print(f"Formation prediction signals: {formation_signals}")


if __name__ == "__main__":
    main()
