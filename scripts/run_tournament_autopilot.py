#!/usr/bin/env python3
"""Run one idempotent live tournament refresh/evaluation cycle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.tournament_autopilot import run_tournament_autopilot  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh durable results, lineups, Arena records, and evaluations.")
    parser.add_argument("--refresh-official", action="store_true", help="Fetch official FIFA calendar scores.")
    parser.add_argument("--refresh-provider", action="store_true", help="Fetch completed matches using BALLDONTLIE_API_KEY.")
    parser.add_argument("--run-arena", action="store_true", help="Run and publish Arena forecasts for nearby fixtures.")
    parser.add_argument("--no-feedback", action="store_true", help="Skip settlement, evaluation, and calibration.")
    parser.add_argument("--hours-ahead", type=int, default=36)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_tournament_autopilot(
        refresh_official=args.refresh_official,
        refresh_provider=args.refresh_provider,
        run_arena=args.run_arena,
        settle_and_evaluate=not args.no_feedback,
        hours_ahead=args.hours_ahead,
    )
    print(json.dumps(report.as_dict(), indent=2))


if __name__ == "__main__":
    main()
