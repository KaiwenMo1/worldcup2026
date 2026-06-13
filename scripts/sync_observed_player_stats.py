#!/usr/bin/env python3
"""Normalize observed seasonal player statistics into the project provider contract."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from predict_worldcup import ROOT
from sync_player_match_stats import (
    PLAYER_MATCH_STATS_COLUMNS,
    PLAYER_MATCH_TEAM_FEATURE_COLUMNS,
    build_player_match_outputs,
    read_csv,
    write_csv,
)


SQUADS_PATH = ROOT / "data" / "worldcup_squads.csv"
OUTPUT_PATH = ROOT / "data" / "observed_player_stats.csv"
PLAYER_STATS_PATH = ROOT / "data" / "player_match_stats.csv"
TEAM_STATS_PATH = ROOT / "data" / "player_match_team_features.csv"

OUTPUT_FIELDS = [
    "provider",
    "provider_player_id",
    "team",
    "player",
    "club",
    "season",
    "competition",
    "minutes",
    "appearances",
    "starts",
    *[
        field
        for field in PLAYER_MATCH_STATS_COLUMNS
        if field
        not in {
            "team",
            "player",
            "position",
            "detailed_position",
            "club",
            "preferred_foot",
            "weak_foot_usage_pct",
            "tactical_role",
            "formation_role",
            "tactic_profile",
            "projected_starter",
            "availability",
            "season_minutes",
            "appearances",
            "starts",
            "penalty_taken_count",
            "penalty_goal_pct",
            "penalty_preferred_placement",
            "penalty_left_pct",
            "penalty_center_pct",
            "penalty_right_pct",
            "penalty_saved_pct",
            "penalty_miss_pct",
            "keeper_penalty_faced",
            "keeper_penalty_save_pct",
            "keeper_penalty_dive_preference",
            "keeper_penalty_dive_left_pct",
            "keeper_penalty_dive_center_pct",
            "keeper_penalty_dive_right_pct",
            "source",
            "updated_at",
        }
    ],
    "source",
    "updated_at",
]
ALIASES = {
    "minutes": ("minutes", "season_minutes", "minutes_played"),
    "appearances": ("appearances", "apps"),
    "starts": ("starts", "lineups"),
    "pass_completion_pct": ("pass_completion_pct", "pass_accuracy", "passes_accuracy"),
    "tackles_interceptions_per90": ("tackles_interceptions_per90", "tackles_plus_interceptions_per90"),
    "post_shot_xg_prevented_per90": ("post_shot_xg_prevented_per90", "psxg_prevented_per90"),
}


def first(row: dict[str, str], names: tuple[str, ...] | list[str]) -> str:
    return next((row[name] for name in names if row.get(name) not in {None, ""}), "")


def normalize_rows(rows: list[dict[str, str]], provider: str) -> list[dict[str, Any]]:
    output = []
    updated_at = datetime.now(timezone.utc).isoformat()
    for row in rows:
        if not row.get("team") or not row.get("player"):
            continue
        item: dict[str, Any] = {field: "" for field in OUTPUT_FIELDS}
        item.update(
            {
                "provider": provider,
                "provider_player_id": row.get("provider_player_id") or row.get("player_id") or "",
                "team": row["team"],
                "player": row["player"],
                "club": row.get("club", ""),
                "season": row.get("season", ""),
                "competition": row.get("competition", ""),
                "source": row.get("source") or provider,
                "updated_at": row.get("updated_at") or updated_at,
            }
        )
        for field in OUTPUT_FIELDS:
            aliases = ALIASES.get(field, (field,))
            value = first(row, aliases)
            if value not in {"", None}:
                item[field] = value
        output.append(item)
    return output


def write_observed(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize and optionally apply observed player statistics.")
    parser.add_argument("--provider-csv", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--apply", action="store_true", help="Rebuild player/team features using observed rows as overrides.")
    args = parser.parse_args()
    observed = normalize_rows(read_csv(args.provider_csv), args.provider)
    write_observed(OUTPUT_PATH, observed)
    print(f"Saved {OUTPUT_PATH} ({len(observed)} observed player rows)")
    if args.apply:
        fetched_at = datetime.now(timezone.utc).isoformat()
        player_rows, team_rows = build_player_match_outputs(read_csv(SQUADS_PATH), fetched_at, OUTPUT_PATH)
        write_csv(PLAYER_STATS_PATH, player_rows, PLAYER_MATCH_STATS_COLUMNS)
        write_csv(TEAM_STATS_PATH, team_rows, PLAYER_MATCH_TEAM_FEATURE_COLUMNS)
        print(f"Applied observed overrides to {PLAYER_STATS_PATH} and {TEAM_STATS_PATH}")


if __name__ == "__main__":
    main()
