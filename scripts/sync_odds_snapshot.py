#!/usr/bin/env python3
"""Pull a one-time bookmaker odds snapshot into data/bookmaker_odds.csv."""

from __future__ import annotations

import argparse

from app.main import OddsSnapshotRequest, refresh_the_odds_api_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync The Odds API h2h snapshot.")
    parser.add_argument("--sport-key")
    parser.add_argument("--regions")
    parser.add_argument("--bookmakers")
    parser.add_argument("--optional", action="store_true", help="Exit 0 when THE_ODDS_API_KEY is missing.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = refresh_the_odds_api_snapshot(
        OddsSnapshotRequest(
            sport_key=args.sport_key,
            regions=args.regions,
            bookmakers=args.bookmakers,
        )
    )
    print(result["message"])
    if not result["ok"] and not args.optional:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
