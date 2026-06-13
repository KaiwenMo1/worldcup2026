#!/usr/bin/env python3
"""Run the full advanced-context refresh pipeline.

This orchestrates optional provider pulls and always rebuilds the forecast-time
advanced signal tables at the end.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from predict_worldcup import ROOT


def run_step(label: str, command: list[str], optional: bool = False) -> None:
    print(f"\n== {label} ==")
    completed = subprocess.run(command, cwd=ROOT, check=False)
    if completed.returncode and not optional:
        raise SystemExit(completed.returncode)
    if completed.returncode and optional:
        print(f"Skipped/failed optional step: {label}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh full advanced World Cup prediction context.")
    parser.add_argument("--lineups", action="store_true", help="Sync Sportmonks observed lineups and availability.")
    parser.add_argument("--odds", action="store_true", help="Sync The Odds API bookmaker snapshot.")
    parser.add_argument("--statsbomb", action="store_true", help="Sync StatsBomb Open Data event-derived context.")
    parser.add_argument("--statsbomb-competition-id", type=int, default=43)
    parser.add_argument("--statsbomb-season-id", type=int, default=106)
    parser.add_argument("--statsbomb-max-matches", type=int)
    parser.add_argument("--weather", action="store_true", help="Train weather effects from data/weather_match_history.csv.")
    parser.add_argument("--fetch-weather", action="store_true", help="Fill missing weather history rows from Open-Meteo archive.")
    parser.add_argument("--fallback-normal-weather-history", action="store_true", help="Create a normal-weather fallback panel from historical scores.")
    parser.add_argument("--train-xg", action="store_true", help="Retrain shot-level xG after event sync.")
    parser.add_argument("--optional-providers", action="store_true", help="Do not fail when provider credentials/data are missing.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    python = sys.executable

    if args.lineups:
        run_step("Sportmonks lineups/availability", [python, "scripts/sync_lineups.py", "--optional"], optional=args.optional_providers)

    if args.odds:
        run_step("The Odds API snapshot", [python, "scripts/sync_odds_snapshot.py", "--optional"], optional=args.optional_providers)

    if args.statsbomb:
        command = [
            python,
            "scripts/sync_statsbomb_advanced.py",
            "--competition-id",
            str(args.statsbomb_competition_id),
            "--season-id",
            str(args.statsbomb_season_id),
        ]
        if args.statsbomb_max_matches:
            command.extend(["--max-matches", str(args.statsbomb_max_matches)])
        run_step("StatsBomb event-derived context", command, optional=args.optional_providers)
        args.train_xg = True

    if args.train_xg:
        run_step("Shot-level xG training", [python, "scripts/xg_model.py"], optional=False)

    if args.weather:
        command = [python, "scripts/train_weather_effects.py"]
        if args.fetch_weather:
            command.append("--fetch-open-meteo")
        if args.fallback_normal_weather_history:
            command.append("--fallback-normal-history")
        run_step("Historical weather effects", command, optional=args.optional_providers)

    run_step("Advanced signal table build", [python, "scripts/build_advanced_context.py"], optional=False)
    print("\nFull advanced context refresh complete.")


if __name__ == "__main__":
    main()
