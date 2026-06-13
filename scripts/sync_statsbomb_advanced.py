#!/usr/bin/env python3
"""Build advanced team context from StatsBomb-style event data.

The script can pull StatsBomb Open Data directly or read already-downloaded
event JSON files. It writes production-shaped context tables used by the match
forecast: shots/xG, tactical profiles, set pieces, freeze-frame context, and
goalkeeper profiles.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from predict_worldcup import ROOT
from xg_model import SHOT_COLUMNS, SHOT_EVENTS_PATH, normalize_row, shot_geometry


BASE_URL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
TACTICAL_PROFILES_PATH = ROOT / "data" / "tactical_profiles.csv"
SET_PIECE_PROFILES_PATH = ROOT / "data" / "set_piece_profiles.csv"
FREEZE_FRAME_SIGNALS_PATH = ROOT / "data" / "freeze_frame_signals.csv"
GOALKEEPER_PROFILES_PATH = ROOT / "data" / "goalkeeper_profiles.csv"


def object_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return str(value or "")


def get_json(path: str) -> Any:
    response = requests.get(f"{BASE_URL}/{path.lstrip('/')}", timeout=45)
    response.raise_for_status()
    return response.json()


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows([{column: row.get(column, "") for column in columns} for row in rows])


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def percentile_scores(values: dict[str, float], low: float = 55.0, high: float = 96.0) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda item: item[1])
    if len(ordered) == 1:
        return {ordered[0][0]: (low + high) / 2}
    output = {}
    for rank, (team, _) in enumerate(ordered):
        output[team] = low + ((high - low) * rank / (len(ordered) - 1))
    return output


def match_teams(match: dict[str, Any]) -> tuple[str, str]:
    return object_name(match.get("home_team")), object_name(match.get("away_team"))


def opponent_for(team: str, match: dict[str, Any]) -> str:
    home, away = match_teams(match)
    return away if team == home else home


def shot_xg(shot: dict[str, Any], fallback_row: dict[str, Any]) -> float:
    value = shot.get("statsbomb_xg")
    if value not in {"", None}:
        return float(value)
    distance = float(fallback_row["distance_m"])
    angle = float(fallback_row["angle_degrees"])
    score = -2.15 - (distance * 0.075) + (angle * 0.035)
    if fallback_row["body_part"] == "Head":
        score -= 0.30
    if fallback_row["defender_pressure"] == "High":
        score -= 0.32
    return 1 / (1 + math.exp(-score))


def freeze_frame_metrics(shot: dict[str, Any]) -> dict[str, float]:
    frame = shot.get("freeze_frame") or []
    defenders = 0
    teammates = 0
    close_defenders = 0
    keeper_distance = 0.0
    keeper_seen = 0
    for item in frame:
        location = item.get("location") or []
        if len(location) < 2:
            continue
        x, y = float(location[0]), float(location[1])
        in_box = x >= 102 and 18 <= y <= 62
        if item.get("teammate"):
            teammates += int(in_box)
        else:
            defenders += int(in_box)
            distance_to_lane = abs(y - 40)
            close_defenders += int(x >= 102 and distance_to_lane <= 8)
        if item.get("keeper"):
            keeper_distance += math.hypot(120 - x, 40 - y)
            keeper_seen += 1
    return {
        "defenders_in_box": float(defenders),
        "teammates_in_box": float(teammates),
        "close_defenders": float(close_defenders),
        "keeper_distance": keeper_distance / keeper_seen if keeper_seen else 7.5,
    }


def extract_shot(event: dict[str, Any], match: dict[str, Any]) -> dict[str, Any] | None:
    if object_name(event.get("type")) != "Shot":
        return None
    location = event.get("location") or []
    if len(location) < 2:
        return None
    shot = event.get("shot") or {}
    x, y = float(location[0]), float(location[1])
    distance, angle = shot_geometry(x, y)
    row = normalize_row(
        {
            "event_id": event.get("id"),
            "match_id": match.get("match_id"),
            "competition": match.get("competition_name", "StatsBomb Open Data"),
            "season": str(match.get("season_name") or ""),
            "match_date": match.get("match_date", ""),
            "team": object_name(event.get("team")),
            "opponent": opponent_for(object_name(event.get("team")), match),
            "player": object_name(event.get("player")),
            "minute": event.get("minute", 0),
            "shot_x": x,
            "shot_y": y,
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
    row["shot_outcome"] = object_name(shot.get("outcome"))
    row["statsbomb_xg"] = shot_xg(shot, row)
    row.update(freeze_frame_metrics(shot))
    return row


def event_location(event: dict[str, Any]) -> tuple[float, float] | None:
    location = event.get("location") or []
    if len(location) < 2:
        return None
    return float(location[0]), float(location[1])


def update_team_events(features: dict[str, dict[str, float]], event: dict[str, Any]) -> None:
    team = object_name(event.get("team"))
    if not team:
        return
    kind = object_name(event.get("type"))
    feature = features[team]
    feature["events"] += 1
    if kind == "Pass":
        feature["passes"] += 1
        if not event.get("pass", {}).get("outcome"):
            feature["passes_complete"] += 1
        loc = event_location(event)
        if loc:
            feature["pass_x"] += loc[0]
            feature["pass_y_distance"] += abs(loc[1] - 40)
    elif kind == "Carry":
        feature["carries"] += 1
        loc = event_location(event)
        if loc:
            feature["carry_x"] += loc[0]
            feature["carry_y_distance"] += abs(loc[1] - 40)
    elif kind == "Pressure":
        feature["pressures"] += 1
    elif kind in {"Duel", "Interception", "Block", "Clearance", "Ball Recovery"}:
        feature["defensive_events"] += 1
    elif kind == "Foul Committed":
        feature["fouls"] += 1


def update_shot_aggregates(
    shots_by_team: dict[str, dict[str, float]],
    conceded_by_team: dict[str, dict[str, float]],
    event_shot: dict[str, Any],
    match: dict[str, Any],
) -> None:
    team = event_shot["team"]
    opponent = opponent_for(team, match)
    xg = float(event_shot["statsbomb_xg"])
    is_goal = int(event_shot["is_goal"])
    body = event_shot["body_part"]
    assist = event_shot["assist_type"]
    shot_type = event_shot["shot_type"]
    attacking = shots_by_team[team]
    defending = conceded_by_team[opponent]
    attacking["shots"] += 1
    attacking["xg"] += xg
    attacking["goals"] += is_goal
    attacking["box_density"] += float(event_shot["teammates_in_box"])
    attacking["lane_quality"] += xg / (1 + float(event_shot["close_defenders"]))
    attacking["defenders_seen"] += float(event_shot["defenders_in_box"])
    if body == "Head":
        attacking["headed_shots"] += 1
        attacking["headed_xg"] += xg
    if assist in {"From Corner", "Corner"} or shot_type == "Corner":
        attacking["corner_shots"] += 1
        attacking["corner_xg"] += xg
    if assist in {"From Free Kick", "Free Kick"} or shot_type == "Free Kick":
        attacking["free_kick_shots"] += 1
        attacking["free_kick_xg"] += xg
    if "Set" in shot_type or assist in {"From Corner", "From Free Kick", "Corner", "Free Kick"}:
        attacking["set_piece_shots"] += 1
        attacking["set_piece_xg"] += xg

    defending["shots"] += 1
    defending["xg"] += xg
    defending["goals"] += is_goal
    if event_shot.get("shot_outcome") in {"Saved", "Saved To Post"}:
        defending["saves"] += 1
    if is_goal == 0 and event_shot["shot_x"] >= 102:
        defending["box_saves_or_misses"] += 1
    defending["keeper_distance"] += float(event_shot["keeper_distance"])
    defending["defenders_in_box"] += float(event_shot["defenders_in_box"])


def formation_rows(events: list[dict[str, Any]]) -> dict[str, str]:
    output = {}
    for event in events:
        if object_name(event.get("type")) != "Starting XI":
            continue
        team = object_name(event.get("team"))
        formation = str(event.get("tactics", {}).get("formation", ""))
        if team and formation:
            output[team] = "-".join(formation)
    return output


def build_rows(
    matches: list[dict[str, Any]],
    events_by_match: dict[int, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    updated_at = datetime.now(timezone.utc).isoformat()
    team_events: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    shots_by_team: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    conceded_by_team: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    formations: dict[str, str] = {}
    shot_rows = []

    for match in matches:
        events = events_by_match[int(match["match_id"])]
        formations.update(formation_rows(events))
        for event in events:
            update_team_events(team_events, event)
            shot = extract_shot(event, match)
            if shot:
                shot_rows.append({column: shot[column] for column in SHOT_COLUMNS})
                update_shot_aggregates(shots_by_team, conceded_by_team, shot, match)

    pressing_scores = percentile_scores({team: values["pressures"] / max(values["events"], 1) for team, values in team_events.items()})
    build_up_scores = percentile_scores(
        {
            team: (values["passes_complete"] / max(values["passes"], 1)) + (values["carries"] / max(values["events"], 1))
            for team, values in team_events.items()
        }
    )
    transition_scores = percentile_scores({team: values["pass_x"] / max(values["passes"], 1) for team, values in team_events.items()})
    defensive_scores = percentile_scores({team: values["defensive_events"] / max(values["events"], 1) for team, values in team_events.items()})
    width_scores = percentile_scores(
        {
            team: (values["pass_y_distance"] + values["carry_y_distance"]) / max(values["passes"] + values["carries"], 1)
            for team, values in team_events.items()
        }
    )

    tactical_rows = []
    for team, values in team_events.items():
        tactical_rows.append(
            {
                "team": team,
                "formation": formations.get(team, ""),
                "pressing": round(pressing_scores.get(team, 70.0), 2),
                "build_up": round(build_up_scores.get(team, 70.0), 2),
                "transition": round(transition_scores.get(team, 70.0), 2),
                "defensive_line": round(defensive_scores.get(team, 70.0), 2),
                "width": round(width_scores.get(team, 70.0), 2),
                "source": "statsbomb_open_data",
                "updated_at": updated_at,
            }
        )

    set_piece_rows = []
    freeze_rows = []
    goalkeeper_rows = []
    for team, values in shots_by_team.items():
        shots = max(values["shots"], 1.0)
        conceded = conceded_by_team.get(team, {})
        conceded_shots = max(conceded.get("shots", 0.0), 1.0)
        set_piece_rows.append(
            {
                "team": team,
                "corner_xg": round(values["corner_xg"] / max(values["corner_shots"], 1.0), 4),
                "free_kick_xg": round(values["free_kick_xg"] / max(values["free_kick_shots"], 1.0), 4),
                "aerial_threat": round(clamp(55 + (values["headed_xg"] / max(values["headed_shots"], 1.0)) * 150, 45, 96), 2),
                "delivery_quality": round(clamp(55 + (values["set_piece_xg"] / max(values["set_piece_shots"], 1.0)) * 140, 45, 96), 2),
                "set_piece_concede_risk": round(clamp(conceded.get("xg", 0.0) / conceded_shots * 130, 0, 55), 2),
                "source": "statsbomb_open_data",
                "updated_at": updated_at,
            }
        )
        freeze_rows.append(
            {
                "team": team,
                "box_density_attack": round(clamp(45 + values["box_density"] / shots * 14, 0, 100), 2),
                "shot_lane_quality": round(clamp(45 + values["lane_quality"] / shots * 145, 0, 100), 2),
                "defensive_compactness": round(clamp(55 + conceded.get("defenders_in_box", 0.0) / conceded_shots * 7, 35, 96), 2),
                "keeper_positioning": round(clamp(92 - conceded.get("keeper_distance", 7.5) / conceded_shots * 5, 35, 96), 2),
                "source": "statsbomb_open_data",
                "updated_at": updated_at,
            }
        )
        goals_against = conceded.get("goals", 0.0)
        xg_conceded = conceded.get("xg", 0.0)
        saves = conceded.get("saves", 0.0) + conceded.get("box_saves_or_misses", 0.0)
        goalkeeper_rows.append(
            {
                "team": team,
                "keeper": "",
                "save_pct": round(clamp(saves / conceded_shots, 0.25, 0.92), 4),
                "post_shot_xg_prevented_per90": round((xg_conceded - goals_against) / max(len(matches), 1), 4),
                "claim_rate": "",
                "sweeper_rate": "",
                "source": "statsbomb_open_data",
                "updated_at": updated_at,
            }
        )
    return shot_rows, tactical_rows, set_piece_rows, freeze_rows, goalkeeper_rows


def load_open_data_matches(competition_id: int, season_id: int, max_matches: int | None) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    matches = get_json(f"matches/{competition_id}/{season_id}.json")[: max_matches or None]
    events_by_match = {int(match["match_id"]): get_json(f"events/{match['match_id']}.json") for match in matches}
    return matches, events_by_match


def load_local_events(events_dir: Path, matches_path: Path | None = None, max_matches: int | None = None) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    paths = sorted(events_dir.glob("*.json"))[: max_matches or None]
    matches_by_id = {}
    if matches_path and matches_path.exists():
        loaded = read_json(matches_path)
        if isinstance(loaded, list):
            matches_by_id = {int(match["match_id"]): match for match in loaded if "match_id" in match}
    matches = []
    events_by_match = {}
    for path in paths:
        match_id = int(path.stem)
        match = matches_by_id.get(match_id, {"match_id": match_id, "match_date": "", "home_team": "", "away_team": ""})
        matches.append(match)
        events_by_match[match_id] = read_json(path)
    if not matches:
        raise SystemExit(f"No event JSON files found in {events_dir}")
    return matches, events_by_match


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync full advanced context from StatsBomb-style event data.")
    parser.add_argument("--competition-id", type=int, default=43, help="StatsBomb Open Data competition_id. Default: FIFA World Cup.")
    parser.add_argument("--season-id", type=int, default=106, help="StatsBomb Open Data season_id. Default: 2022.")
    parser.add_argument("--max-matches", type=int, help="Limit matches for a quick pull.")
    parser.add_argument("--events-dir", type=Path, help="Read local StatsBomb event JSON files instead of downloading.")
    parser.add_argument("--matches-json", type=Path, help="Optional local matches JSON for local event files.")
    parser.add_argument("--shots-output", type=Path, default=SHOT_EVENTS_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.events_dir:
        matches, events_by_match = load_local_events(args.events_dir, args.matches_json, args.max_matches)
    else:
        matches, events_by_match = load_open_data_matches(args.competition_id, args.season_id, args.max_matches)

    shot_rows, tactical_rows, set_piece_rows, freeze_rows, goalkeeper_rows = build_rows(matches, events_by_match)
    write_csv(args.shots_output, shot_rows, SHOT_COLUMNS)
    write_csv(TACTICAL_PROFILES_PATH, tactical_rows, ["team", "formation", "pressing", "build_up", "transition", "defensive_line", "width", "source", "updated_at"])
    write_csv(SET_PIECE_PROFILES_PATH, set_piece_rows, ["team", "corner_xg", "free_kick_xg", "aerial_threat", "delivery_quality", "set_piece_concede_risk", "source", "updated_at"])
    write_csv(FREEZE_FRAME_SIGNALS_PATH, freeze_rows, ["team", "box_density_attack", "shot_lane_quality", "defensive_compactness", "keeper_positioning", "source", "updated_at"])
    write_csv(GOALKEEPER_PROFILES_PATH, goalkeeper_rows, ["team", "keeper", "save_pct", "post_shot_xg_prevented_per90", "claim_rate", "sweeper_rate", "source", "updated_at"])
    print(f"StatsBomb shots: {len(shot_rows)}")
    print(f"Tactical teams: {len(tactical_rows)}")
    print(f"Set-piece teams: {len(set_piece_rows)}")
    print(f"Freeze-frame teams: {len(freeze_rows)}")
    print(f"Goalkeeper teams: {len(goalkeeper_rows)}")


if __name__ == "__main__":
    main()
