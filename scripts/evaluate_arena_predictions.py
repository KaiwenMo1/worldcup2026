#!/usr/bin/env python3
"""Print the Prediction Arena entertainment-only virtual leaderboard."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.prediction_arena.virtual_scoreboard import evaluate_arena_predictions  # noqa: E402


def main() -> None:
    print(json.dumps(evaluate_arena_predictions(), indent=2))


if __name__ == "__main__":
    main()
