#!/usr/bin/env python3
"""Pull shot events from StatsBomb Open Data into the local xG schema."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

import requests

from predict_worldcup import ROOT
from xg_model import SHOT_COLUMNS, SHOT_EVENTS_PATH, normalize_row, shot_geometry


BASE_URL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"


def get_json(path: str) -> Any:
    response = requests.get(f"{BASE_URL}/{path.lstrip('/')}", timeout=45)
    response.raise_for_status()
    return response.json()


def object_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return str(value or "")


def extract_shot(event: dict[str, Any], match: dict[str, Any]) -> dict[str, Any] | None:
    if object_name(event.get("type")) != "Shot":
        return None
    location = event.get("location") or []
    if len(location) < 2:
        return None
    shot = event.get("shot") or {}
    shot_x = float(location[0])
    shot_y = float(location[1])
    distance, angle = shot_geometry(shot_x, shot_y)
    return normalize_row(
        {
            "event_id": event.get("id"),
            "match_id": match.get("match_id"),
            "competition": match.get("competition_name", "StatsBomb Open Data"),
            "season": str(match.get("season_name") or match.get("season", "")),
            "match_date": match.get("match_date", ""),
            "team": object_name(event.get("team")),
            "opponent": "",
            "player": object_name(event.get("player")),
            "minute": event.get("minute", 0),
            "shot_x": shot_x,
            "shot_y": shot_y,
            "distance_m": distance,
            "angle_degrees": angle,
            "body_part": object_name(shot.get("body_part")) or "Right Foot",
            "assist_type": object_name(event.get("play_pattern")) or "Open Play",
            "defender_pressure": "High" if event.get("under_pressure") else "Low",
            "game_state": "Drawing",
            "shot_type": object_name(shot.get("type")) or "Open Play",
            "is_goal": int(object_name(shot.get("outcome")) == "Goal"),
            "source": "statsbomb_open_data",
        }
    )


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHOT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sync_statsbomb_shots(competition_id: int, season_id: int, output: Path, max_matches: int | None) -> int:
    matches = get_json(f"matches/{competition_id}/{season_id}.json")
    rows = []
    for match in matches[: max_matches or None]:
        events = get_json(f"events/{match['match_id']}.json")
        for event in events:
            row = extract_shot(event, match)
            if row:
                rows.append(row)
    if not rows:
        raise SystemExit("No shot events found for that StatsBomb competition/season.")
    write_rows(output, rows)
    return len(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync StatsBomb Open Data shots into data/shot_events.csv.")
    parser.add_argument("--competition-id", type=int, default=43, help="StatsBomb competition_id. Default: FIFA World Cup.")
    parser.add_argument("--season-id", type=int, default=106, help="StatsBomb season_id. Default: 2022.")
    parser.add_argument("--max-matches", type=int, help="Limit matches for a quick local pull.")
    parser.add_argument("--output", type=Path, default=SHOT_EVENTS_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = sync_statsbomb_shots(args.competition_id, args.season_id, args.output, args.max_matches)
    print(f"Saved {rows} StatsBomb shots to {args.output}")


if __name__ == "__main__":
    main()
