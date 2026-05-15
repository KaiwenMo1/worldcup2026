#!/usr/bin/env python3
"""Convert martj42/Kaggle international results.csv into this project's match format."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


MISSING_VALUES = {"", "na", "nan", "none", "null"}


def truthy(value: str) -> int:
    return int(str(value).strip().lower() in {"1", "true", "yes"})


def present(value: str | None) -> bool:
    return value is not None and str(value).strip().lower() not in MISSING_VALUES


def convert(input_path: Path, output_path: Path, since: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open(newline="", encoding="utf-8") as source, output_path.open("w", newline="", encoding="utf-8") as target:
        reader = csv.DictReader(source)
        writer = csv.DictWriter(
            target,
            fieldnames=["date", "team_a", "team_b", "team_a_score", "team_b_score", "neutral", "tournament"],
        )
        writer.writeheader()
        kept = 0
        skipped = 0
        for row in reader:
            if row["date"] < since:
                continue
            if not present(row.get("home_score")) or not present(row.get("away_score")):
                skipped += 1
                continue
            writer.writerow(
                {
                    "date": row["date"],
                    "team_a": row["home_team"],
                    "team_b": row["away_team"],
                    "team_a_score": row["home_score"],
                    "team_b_score": row["away_score"],
                    "neutral": truthy(row.get("neutral", "false")),
                    "tournament": row["tournament"],
                }
            )
            kept += 1
    print(f"Converted {kept} matches to {output_path}; skipped {skipped} rows without final scores.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert international results.csv into data/historical_matches.csv.")
    parser.add_argument("input", type=Path, help="Path to downloaded results.csv.")
    parser.add_argument("--output", type=Path, default=Path("data/historical_matches.csv"))
    parser.add_argument("--since", default="2018-01-01", help="Keep matches on or after this YYYY-MM-DD date.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    convert(args.input, args.output, args.since)


if __name__ == "__main__":
    main()
