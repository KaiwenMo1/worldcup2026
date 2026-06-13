#!/usr/bin/env python3
"""Train weather effect priors from match-level weather history.

Input rows can be supplied directly in data/weather_match_history.csv. If rows
have latitude/longitude and kickoff time but no weather variables, pass
--fetch-open-meteo to fill hourly weather from Open-Meteo's archive API.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from predict_worldcup import ROOT


WEATHER_HISTORY_PATH = ROOT / "data" / "weather_match_history.csv"
WEATHER_EFFECTS_PATH = ROOT / "data" / "weather_effects.csv"
HISTORICAL_MATCHES_PATH = ROOT / "data" / "historical_matches.csv"

WEATHER_COLUMNS = [
    "match_id",
    "date",
    "kickoff_local",
    "venue",
    "latitude",
    "longitude",
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "weather",
    "total_goals",
    "source",
    "updated_at",
]

EFFECT_COLUMNS = [
    "weather",
    "goal_multiplier",
    "pressing_penalty",
    "set_piece_bonus",
    "keeper_handling_penalty",
    "sample_matches",
    "source",
    "updated_at",
]

STARTER_EFFECTS = [
    {"weather": "normal", "goal_multiplier": 1.0, "pressing_penalty": 0.0, "set_piece_bonus": 0.0, "keeper_handling_penalty": 0.0},
    {"weather": "heat", "goal_multiplier": 0.93, "pressing_penalty": 0.055, "set_piece_bonus": 0.0, "keeper_handling_penalty": 0.0},
    {"weather": "rain", "goal_multiplier": 0.90, "pressing_penalty": 0.025, "set_piece_bonus": 0.045, "keeper_handling_penalty": 0.035},
    {"weather": "cold", "goal_multiplier": 0.96, "pressing_penalty": 0.015, "set_piece_bonus": 0.025, "keeper_handling_penalty": 0.012},
    {"weather": "altitude", "goal_multiplier": 0.92, "pressing_penalty": 0.04, "set_piece_bonus": 0.01, "keeper_handling_penalty": 0.0},
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows([{column: row.get(column, "") for column in columns} for row in rows])


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {"", None}:
            return default
        return float(value)
    except ValueError:
        return default


def classify_weather(row: dict[str, Any]) -> str:
    if row.get("weather"):
        return str(row["weather"])
    temperature = to_float(row.get("temperature_2m"), 18.0)
    precipitation = to_float(row.get("precipitation"), 0.0)
    wind = to_float(row.get("wind_speed_10m"), 0.0)
    if precipitation >= 0.8 or wind >= 30:
        return "rain"
    if temperature >= 30:
        return "heat"
    if temperature <= 3:
        return "cold"
    return "normal"


def hourly_archive(row: dict[str, str]) -> dict[str, Any]:
    latitude = to_float(row.get("latitude"))
    longitude = to_float(row.get("longitude"))
    kickoff = row.get("kickoff_local") or row.get("date")
    if not latitude or not longitude or not kickoff:
        return {}
    parsed = datetime.fromisoformat(kickoff[:19])
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
        "start_date": parsed.date().isoformat(),
        "end_date": parsed.date().isoformat(),
        "timezone": "auto",
    }
    response = requests.get("https://archive-api.open-meteo.com/v1/archive", params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()
    hourly = payload.get("hourly", {})
    times = hourly.get("time") or []
    if not times:
        return {}
    target = parsed.replace(tzinfo=None)
    index = min(range(len(times)), key=lambda idx: abs((datetime.fromisoformat(times[idx]) - target).total_seconds()))
    return {
        "temperature_2m": hourly.get("temperature_2m", [None])[index],
        "relative_humidity_2m": hourly.get("relative_humidity_2m", [None])[index],
        "precipitation": hourly.get("precipitation", [None])[index],
        "wind_speed_10m": hourly.get("wind_speed_10m", [None])[index],
    }


def fetch_missing_weather(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    output = []
    updated_at = datetime.now(timezone.utc).isoformat()
    for row in rows:
        enriched = dict(row)
        if not enriched.get("temperature_2m") and enriched.get("latitude") and enriched.get("longitude"):
            try:
                enriched.update(hourly_archive(enriched))
                enriched["source"] = "open-meteo-archive"
                enriched["updated_at"] = updated_at
            except requests.RequestException as exc:
                enriched["source"] = f"open-meteo-failed: {exc}"
        enriched["weather"] = classify_weather(enriched)
        output.append(enriched)
    return output


def fallback_history_from_scores() -> list[dict[str, Any]]:
    rows = []
    for index, match in enumerate(read_csv(HISTORICAL_MATCHES_PATH), start=1):
        total_goals = to_float(match.get("team_a_score")) + to_float(match.get("team_b_score"))
        rows.append(
            {
                "match_id": f"historical-{index}",
                "date": match.get("date", ""),
                "kickoff_local": "",
                "venue": "",
                "latitude": "",
                "longitude": "",
                "temperature_2m": "",
                "relative_humidity_2m": "",
                "precipitation": "",
                "wind_speed_10m": "",
                "weather": "normal",
                "total_goals": total_goals,
                "source": "historical_matches_no_weather",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return rows


def train_effects(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updated_at = datetime.now(timezone.utc).isoformat()
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        total_goals = to_float(row.get("total_goals"), -1)
        if total_goals < 0:
            continue
        grouped[classify_weather(row)].append(total_goals)
    normal_avg = sum(grouped.get("normal", [])) / max(len(grouped.get("normal", [])), 1)
    if normal_avg <= 0:
        normal_avg = sum(sum(values) for values in grouped.values()) / max(sum(len(values) for values in grouped.values()), 1)
    output = []
    for starter in STARTER_EFFECTS:
        weather = starter["weather"]
        values = grouped.get(weather, [])
        if len(values) >= 20 and normal_avg > 0:
            observed_avg = sum(values) / len(values)
            multiplier = max(0.78, min(1.16, observed_avg / normal_avg))
            source = "historical-weather-match-panel"
        else:
            multiplier = starter["goal_multiplier"]
            source = "starter-prior-insufficient-weather-history"
        output.append(
            {
                "weather": weather,
                "goal_multiplier": round(multiplier, 4),
                "pressing_penalty": starter["pressing_penalty"],
                "set_piece_bonus": starter["set_piece_bonus"],
                "keeper_handling_penalty": starter["keeper_handling_penalty"],
                "sample_matches": len(values),
                "source": source,
                "updated_at": updated_at,
            }
        )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train weather effects from match-weather history.")
    parser.add_argument("--input", type=Path, default=WEATHER_HISTORY_PATH)
    parser.add_argument("--output", type=Path, default=WEATHER_EFFECTS_PATH)
    parser.add_argument("--fetch-open-meteo", action="store_true", help="Fill missing hourly weather using Open-Meteo archive.")
    parser.add_argument("--fallback-normal-history", action="store_true", help="Use historical match scores as normal-weather fallback when no input exists.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows: list[dict[str, Any]] = read_csv(args.input)
    if rows and args.fetch_open_meteo:
        rows = fetch_missing_weather(rows)
        write_csv(args.input, rows, WEATHER_COLUMNS)
    if not rows and args.fallback_normal_history:
        rows = fallback_history_from_scores()
        write_csv(args.input, rows, WEATHER_COLUMNS)
    effects = train_effects(rows)
    write_csv(args.output, effects, EFFECT_COLUMNS)
    print(f"Weather history rows: {len(rows)}")
    print(f"Saved weather effects to {args.output}")


if __name__ == "__main__":
    main()
