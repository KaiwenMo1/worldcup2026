#!/usr/bin/env python3
"""Run, version, optionally lock, and optionally publish one Prediction Arena match."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from app.prediction_arena.prediction_runner import run_prediction_arena  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--team-a", required=True)
    parser.add_argument("--team-b", required=True)
    parser.add_argument("--stage", required=True, choices=("group", "knockout"))
    parser.add_argument("--lock", action="store_true", help="Lock every persisted record in this new version.")
    parser.add_argument("--publish-card", action="store_true", help="Publish data/prediction_arena/cards/{match_id}.md.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_prediction_arena(
        args.match_id,
        args.team_a,
        args.team_b,
        args.stage,
        lock=args.lock,
        publish_card=args.publish_card,
    )
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
