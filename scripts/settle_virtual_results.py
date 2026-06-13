#!/usr/bin/env python3
"""Settle saved Prediction Arena calls using entertainment-only virtual points."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.prediction_arena.virtual_scoreboard import settle_match_predictions  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--actual-score", required=True, help="Regular-time score, for example 2-1.")
    parser.add_argument("--regular-time-result", required=True, help="Team name or Draw.")
    parser.add_argument("--qualification-result", help="Team qualification result when applicable.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = settle_match_predictions(
        args.match_id,
        actual_score=args.actual_score,
        actual_regular_time_result=args.regular_time_result,
        actual_qualification_result=args.qualification_result,
    )
    print(json.dumps([result.model_dump(mode="json") for result in results], indent=2))


if __name__ == "__main__":
    main()
