#!/usr/bin/env python3
"""Normalize observed manager-match exports into the tactical history contract."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from predict_worldcup import ROOT
from sync_managers import read_csv


MANAGERS_PATH = ROOT / "data" / "managers.csv"
OUTPUT_PATH = ROOT / "data" / "manager_match_history.csv"
FIELDS = [
    "match_id",
    "date",
    "manager_id",
    "team",
    "opponent",
    "competition",
    "goals_for",
    "goals_against",
    "opponent_strength",
    "formation",
    "ppda",
    "defensive_line_height",
    "build_up_directness",
    "possession_share",
    "transition_attacks",
    "set_piece_xg",
    "first_sub_minute",
    "substitution_count",
    "leading_minutes",
    "trailing_minutes",
    "source",
]
ALIASES = {
    "match_id": ("match_id", "fixture_id", "game_id"),
    "date": ("date", "match_date", "kickoff_date"),
    "team": ("team", "team_name"),
    "opponent": ("opponent", "opponent_name"),
    "goals_for": ("goals_for", "team_score"),
    "goals_against": ("goals_against", "opponent_score"),
    "formation": ("formation", "starting_formation"),
    "possession_share": ("possession_share", "possession", "possession_pct"),
    "substitution_count": ("substitution_count", "subs_used"),
}


def first(row: dict[str, str], names: tuple[str, ...]) -> str:
    return next((row[name] for name in names if row.get(name) not in {None, ""}), "")


def manager_lookup(managers: list[dict[str, str]]) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    by_id = {row["manager_id"]: row["manager_id"] for row in managers if row.get("manager_id")}
    by_team_name = {
        (row.get("team", "").casefold(), row.get("manager_name", "").casefold()): row["manager_id"]
        for row in managers
        if row.get("manager_id") and row.get("manager_name")
    }
    return by_id, by_team_name


def normalize_rows(
    rows: list[dict[str, str]],
    managers: list[dict[str, str]],
    provider: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Normalize rows and reject ambiguous historical manager attribution."""
    by_id, by_team_name = manager_lookup(managers)
    output = []
    rejected = []
    for index, row in enumerate(rows, start=2):
        manager_id = row.get("manager_id", "").strip()
        if manager_id and manager_id not in by_id:
            rejected.append(f"row {index}: unknown manager_id {manager_id!r}")
            continue
        if not manager_id:
            manager_id = by_team_name.get(
                (first(row, ALIASES["team"]).casefold(), row.get("manager_name", "").casefold()),
                "",
            )
        if not manager_id:
            rejected.append(f"row {index}: explicit manager_id or exact team + manager_name is required")
            continue

        item = {field: "" for field in FIELDS}
        for field in FIELDS:
            value = first(row, ALIASES.get(field, (field,)))
            if value not in {"", None}:
                item[field] = value
        item["manager_id"] = manager_id
        item["source"] = row.get("source") or provider
        if not item["date"] or not item["team"] or not item["opponent"]:
            rejected.append(f"row {index}: date, team, and opponent are required")
            continue
        output.append(item)
    return output, rejected


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize observed manager-match data.")
    parser.add_argument("--provider-csv", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    rows, rejected = normalize_rows(read_csv(args.provider_csv), read_csv(MANAGERS_PATH), args.provider)
    write_csv(args.output, rows)
    print(f"Saved {args.output} ({len(rows)} observed manager-match rows; {len(rejected)} rejected)")
    for reason in rejected[:10]:
        print(f"Rejected {reason}")


if __name__ == "__main__":
    main()
