#!/usr/bin/env python3
"""Build advanced forecast context tables from the current local data.

These files are intentionally provider-shaped. They work today from squad,
player, xG, and odds estimates, and later can be replaced by API snapshots with
the same columns.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from predict_worldcup import ROOT


SQUADS_PATH = ROOT / "data" / "worldcup_squads.csv"
PLAYER_TEAM_FEATURES_PATH = ROOT / "data" / "player_match_team_features.csv"
TEAM_ADVANCED_FEATURES_PATH = ROOT / "data" / "team_advanced_features.csv"
BOOKMAKER_ODDS_PATH = ROOT / "data" / "bookmaker_odds.csv"
XG_TEAM_ZONES_PATH = ROOT / "data" / "xg_team_zones.csv"
LIVE_STATE_PATH = ROOT / "data" / "live_state.json"
LINEUP_OBSERVATIONS_PATH = ROOT / "data" / "lineup_observations.csv"

AVAILABILITY_PATH = ROOT / "data" / "player_availability.csv"
CONFIRMED_LINEUPS_PATH = ROOT / "data" / "confirmed_lineups.csv"
MARKET_SIGNALS_PATH = ROOT / "data" / "market_signals.csv"
TACTICAL_PROFILES_PATH = ROOT / "data" / "tactical_profiles.csv"
SET_PIECE_PROFILES_PATH = ROOT / "data" / "set_piece_profiles.csv"
GOALKEEPER_PROFILES_PATH = ROOT / "data" / "goalkeeper_profiles.csv"
REFEREE_PROFILES_PATH = ROOT / "data" / "referee_profiles.csv"
WEATHER_EFFECTS_PATH = ROOT / "data" / "weather_effects.csv"
LIVE_TEAM_STATE_PATH = ROOT / "data" / "live_team_state.csv"
FREEZE_FRAME_SIGNALS_PATH = ROOT / "data" / "freeze_frame_signals.csv"

PROJECTION_SOURCES = {
    "squad-projection",
    "projected-xi",
    "market-value/caps positional projection",
    "derived-player-team-profile",
    "starter-prior",
    "historical-weather-prior",
    "xg-team-zones-derived",
    "live_state.json",
}


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


def source_is_provider(row: dict[str, Any]) -> bool:
    source = str(row.get("source") or "").strip()
    return bool(source) and source not in PROJECTION_SOURCES


def provider_rows(path: Path) -> list[dict[str, str]]:
    return [row for row in read_csv(path) if source_is_provider(row)]


def provider_rows_by_key(path: Path, key: str) -> dict[str, dict[str, str]]:
    rows = {}
    for row in provider_rows(path):
        value = row.get(key)
        if value:
            rows[value] = row
    return rows


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {"", None}:
            return default
        return float(str(value).replace("+", ""))
    except ValueError:
        return default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def decimal_odds(row: dict[str, str]) -> float | None:
    decimal = to_float(row.get("decimal_odds"))
    if decimal > 1:
        return decimal
    american = to_float(row.get("american_odds"))
    if american == 0:
        return None
    if american > 0:
        return 1 + american / 100
    return 1 + 100 / abs(american)


def selection_key(selection: str, team_a: str, team_b: str) -> str | None:
    text = (selection or "").strip().lower()
    if text in {"draw", "tie", "x"}:
        return "draw"
    if text in {team_a.strip().lower(), "team_a", "home", "1"}:
        return "team_a"
    if text in {team_b.strip().lower(), "team_b", "away", "2"}:
        return "team_b"
    return None


def player_impact(row: dict[str, str]) -> float:
    value = to_float(row.get("market_value_eur"))
    value_score = math.log1p(value) / math.log1p(220_000_000)
    caps_score = min(to_float(row.get("caps")) / 90, 1.0)
    goals_score = min(to_float(row.get("international_goals")) / 35, 1.0)
    starter = 1.25 if row.get("projected_starter") == "1" else 0.78
    position = row.get("position", "")
    keeper = 0.10 if position == "GK" and row.get("projected_starter") == "1" else 0.0
    return round(starter * (35 + 42 * value_score + 16 * caps_score + 7 * goals_score + keeper), 2)


def group_by_team(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get("team"):
            grouped[row["team"]].append(row)
    return grouped


def load_feature_map(path: Path) -> dict[str, dict[str, float]]:
    output = {}
    for row in read_csv(path):
        team = row.get("team")
        if not team:
            continue
        output[team] = {key: to_float(value) for key, value in row.items() if key != "team"}
    return output


def team_average(rows: list[dict[str, str]], column: str, starters_only: bool = False) -> float:
    selected = [row for row in rows if not starters_only or row.get("projected_starter") == "1"]
    values = [to_float(row.get(column)) for row in selected if row.get(column) not in {"", None}]
    return sum(values) / len(values) if values else 0.0


def formation_for_team(rows: list[dict[str, str]]) -> str:
    counts = Counter(row.get("projected_formation", "") for row in rows if row.get("projected_formation"))
    return counts.most_common(1)[0][0] if counts else "4-3-3"


def build_availability(squads: list[dict[str, str]], updated_at: str) -> list[dict[str, Any]]:
    rows = []
    impact_by_player = {
        (player["team"], player["player"]): player_impact(player)
        for player in squads
    }
    for player in squads:
        availability = to_float(player.get("availability"), 1.0)
        status = player.get("availability_status") or ("available" if availability >= 0.95 else "limited")
        rows.append(
            {
                "match_id": "",
                "team": player["team"],
                "player": player["player"],
                "player_id": "",
                "status": status,
                "category": "squad-status",
                "start_date": "",
                "end_date": "",
                "availability": round(availability, 3),
                "minutes_limit": round(90 * availability),
                "impact_score": player_impact(player),
                "source": "squad-projection",
                "updated_at": updated_at,
            }
        )
    for row in provider_rows(AVAILABILITY_PATH):
        team = row.get("team", "")
        player = row.get("player", "")
        status = row.get("status") or "unavailable"
        availability = to_float(row.get("availability"), 0.0 if status in {"out", "injured", "suspended", "unavailable"} else 1.0)
        minutes_limit = row.get("minutes_limit")
        if minutes_limit in {"", None}:
            minutes_limit = round(90 * clamp(availability, 0, 1))
        rows.append(
            {
                "match_id": row.get("match_id", ""),
                "team": team,
                "player": player,
                "player_id": row.get("player_id", ""),
                "status": status,
                "category": row.get("category", "provider-status"),
                "start_date": row.get("start_date", ""),
                "end_date": row.get("end_date", ""),
                "availability": round(clamp(availability, 0, 1), 3),
                "minutes_limit": minutes_limit,
                "impact_score": to_float(row.get("impact_score"), impact_by_player.get((team, player), 55.0)),
                "source": row.get("source") or "provider",
                "updated_at": row.get("updated_at") or row.get("fetched_at") or updated_at,
            }
        )
    return rows


def build_confirmed_lineups(squads: list[dict[str, str]], updated_at: str) -> list[dict[str, Any]]:
    rows = []
    for player in squads:
        starter = int(player.get("projected_starter") == "1")
        confidence = to_float(player.get("lineup_confidence"))
        observed = to_float(player.get("observed_start_rate"))
        if not confidence:
            confidence = 55 + (30 * observed) if observed else 62 if starter else 48
        rows.append(
            {
                "match_id": "",
                "team": player["team"],
                "player": player["player"],
                "starter": starter,
                "position": player.get("position", ""),
                "role": player.get("detailed_position", ""),
                "formation": player.get("projected_formation") or "",
                "confidence": round(confidence, 1),
                "confirmed": 0,
                "source": player.get("projection_method") or "projected-xi",
                "updated_at": updated_at,
            }
        )
    observations = read_csv(LINEUP_OBSERVATIONS_PATH)
    observed_by_team: dict[str, list[dict[str, str]]] = defaultdict(list)
    latest_date_by_team: dict[str, str] = {}
    for row in observations:
        team = row.get("team", "")
        match_date = row.get("match_date", "")
        if not team:
            continue
        latest_date_by_team[team] = max(latest_date_by_team.get(team, ""), match_date)
    for row in observations:
        team = row.get("team", "")
        if team and row.get("match_date", "") == latest_date_by_team.get(team):
            observed_by_team[team].append(row)
    for team, observed_rows in observed_by_team.items():
        formation = next((row.get("formation", "") for row in observed_rows if row.get("formation")), "")
        for row in observed_rows:
            rows.append(
                {
                    "match_id": row.get("match_id", ""),
                    "team": team,
                    "player": row.get("player", ""),
                    "starter": 1,
                    "position": row.get("position", ""),
                    "role": row.get("formation_field", ""),
                    "formation": formation,
                    "confidence": 82.0,
                    "confirmed": 0,
                    "source": f"{row.get('source') or 'provider'}-observed-recent",
                    "updated_at": row.get("fetched_at") or updated_at,
                }
            )
    for row in provider_rows(CONFIRMED_LINEUPS_PATH):
        rows.append(
            {
                "match_id": row.get("match_id", ""),
                "team": row.get("team", ""),
                "player": row.get("player", ""),
                "starter": int(to_float(row.get("starter"), 1.0)),
                "position": row.get("position", ""),
                "role": row.get("role", ""),
                "formation": row.get("formation", ""),
                "confidence": to_float(row.get("confidence"), 92.0),
                "confirmed": int(to_float(row.get("confirmed"), 1.0)),
                "source": row.get("source") or "provider",
                "updated_at": row.get("updated_at") or updated_at,
            }
        )
    return rows


def build_market_signals(updated_at: str) -> list[dict[str, Any]]:
    rows = []
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in read_csv(BOOKMAKER_ODDS_PATH):
        decimal = decimal_odds(row)
        if not decimal:
            continue
        team_a = row.get("team_a", "")
        team_b = row.get("team_b", "")
        key = selection_key(row.get("selection", ""), team_a, team_b)
        if not team_a or not team_b or key is None:
            continue
        grouped[(row.get("event", f"{team_a} vs {team_b}"), team_a, team_b, row.get("bookmaker", "market"))].append(
            {
                "selection_key": key,
                "implied": 1 / decimal,
                "notes": row.get("notes", ""),
            }
        )

    for (event, team_a, team_b, bookmaker), prices in grouped.items():
        overround = sum(price["implied"] for price in prices) or 1.0
        probabilities = {"team_a": 0.0, "draw": 0.0, "team_b": 0.0}
        for price in prices:
            probabilities[price["selection_key"]] += price["implied"] / overround
        notes = " | ".join(sorted({price["notes"] for price in prices if price["notes"]}))
        rows.append(
            {
                "event": event,
                "team_a": team_a,
                "team_b": team_b,
                "market_probability_a": round(probabilities["team_a"], 4),
                "market_probability_draw": round(probabilities["draw"], 4),
                "market_probability_b": round(probabilities["team_b"], 4),
                "opening_probability_a": "",
                "opening_probability_b": "",
                "line_movement_a": 0.0,
                "line_movement_b": 0.0,
                "bookmaker": bookmaker,
                "source": "bookmaker_odds.csv",
                "notes": notes,
                "updated_at": updated_at,
            }
        )
    return rows


def build_tactical_profiles(
    squads_by_team: dict[str, list[dict[str, str]]],
    player_features: dict[str, dict[str, float]],
    team_features: dict[str, dict[str, float]],
    updated_at: str,
) -> list[dict[str, Any]]:
    provider = provider_rows_by_key(TACTICAL_PROFILES_PATH, "team")
    rows = []
    for team, players in squads_by_team.items():
        if team in provider:
            rows.append(provider[team])
            continue
        player = player_features.get(team, {})
        team_feature = team_features.get(team, {})
        wide_players = sum(
            1
            for row in players
            if any(word in (row.get("detailed_position", "").lower()) for word in ("wing", "left", "right", "full-back"))
        )
        rows.append(
            {
                "team": team,
                "formation": formation_for_team(players),
                "pressing": round(player.get("player_pressing_score", team_feature.get("pressing_intensity", 72.0)), 2),
                "build_up": round((player.get("player_passing_score", 70.0) + player.get("player_progression_score", 70.0)) / 2, 2),
                "transition": round(team_feature.get("transition_speed", player.get("player_progression_score", 70.0)), 2),
                "defensive_line": round(clamp((team_feature.get("pressing_intensity", 72.0) * 0.65) + (player.get("player_defensive_activity_score", 70.0) * 0.35), 40, 96), 2),
                "width": round(clamp(52 + wide_players * 2.2 + player.get("player_set_piece_delivery_score", 70.0) * 0.18, 45, 95), 2),
                "source": "derived-player-team-profile",
                "updated_at": updated_at,
            }
        )
    return rows


def build_set_piece_profiles(
    squads_by_team: dict[str, list[dict[str, str]]],
    player_features: dict[str, dict[str, float]],
    team_features: dict[str, dict[str, float]],
    updated_at: str,
) -> list[dict[str, Any]]:
    provider = provider_rows_by_key(SET_PIECE_PROFILES_PATH, "team")
    rows = []
    for team, players in squads_by_team.items():
        if team in provider:
            rows.append(provider[team])
            continue
        player = player_features.get(team, {})
        team_feature = team_features.get(team, {})
        aerial = clamp(50 + (team_average(players, "market_value_eur", True) / 4_000_000), 45, 95)
        delivery = player.get("player_set_piece_delivery_score", 70.0)
        attack = team_feature.get("set_piece_attack", delivery)
        defense = team_feature.get("set_piece_defense", player.get("player_defensive_activity_score", 70.0))
        rows.append(
            {
                "team": team,
                "corner_xg": round(0.02 + attack / 1700 + aerial / 2400, 4),
                "free_kick_xg": round(0.015 + delivery / 2100, 4),
                "aerial_threat": round(aerial, 2),
                "delivery_quality": round(delivery, 2),
                "set_piece_concede_risk": round(clamp(100 - defense, 0, 55), 2),
                "source": "derived-player-team-profile",
                "updated_at": updated_at,
            }
        )
    return rows


def build_goalkeeper_profiles(
    squads_by_team: dict[str, list[dict[str, str]]],
    player_features: dict[str, dict[str, float]],
    updated_at: str,
) -> list[dict[str, Any]]:
    provider = provider_rows_by_key(GOALKEEPER_PROFILES_PATH, "team")
    rows = []
    for team, players in squads_by_team.items():
        if team in provider:
            rows.append(provider[team])
            continue
        feature = player_features.get(team, {})
        keeper_rows = [row for row in players if row.get("position") == "GK"]
        starter_keeper = next((row for row in keeper_rows if row.get("projected_starter") == "1"), keeper_rows[0] if keeper_rows else {})
        rows.append(
            {
                "team": team,
                "keeper": starter_keeper.get("player", ""),
                "save_pct": round(clamp(feature.get("player_goalkeeping_score", 70.0) / 100, 0.45, 0.88), 4),
                "post_shot_xg_prevented_per90": round((feature.get("player_goalkeeping_score", 70.0) - 70) / 80, 4),
                "claim_rate": round(clamp(feature.get("player_keeper_sweeping_score", 70.0) / 150, 0.20, 0.75), 4),
                "sweeper_rate": round(clamp(feature.get("player_keeper_sweeping_score", 70.0) / 120, 0.25, 0.95), 4),
                "source": "derived-player-team-profile",
                "updated_at": updated_at,
            }
        )
    return rows


def build_referee_profiles(updated_at: str) -> list[dict[str, Any]]:
    rows = provider_rows(REFEREE_PROFILES_PATH)
    if rows:
        return rows
    return [
        {
            "referee": "Average referee",
            "cards_per_match": 4.2,
            "penalties_per_match": 0.28,
            "fouls_per_match": 24.0,
            "var_intervention_rate": 0.18,
            "home_bias": 0.0,
            "source": "starter-prior",
            "updated_at": updated_at,
        },
        {
            "referee": "Strict referee",
            "cards_per_match": 6.0,
            "penalties_per_match": 0.36,
            "fouls_per_match": 29.0,
            "var_intervention_rate": 0.24,
            "home_bias": 0.0,
            "source": "starter-prior",
            "updated_at": updated_at,
        },
        {
            "referee": "Lenient referee",
            "cards_per_match": 2.7,
            "penalties_per_match": 0.18,
            "fouls_per_match": 19.0,
            "var_intervention_rate": 0.12,
            "home_bias": 0.0,
            "source": "starter-prior",
            "updated_at": updated_at,
        },
    ]


def build_weather_effects(updated_at: str) -> list[dict[str, Any]]:
    rows = provider_rows(WEATHER_EFFECTS_PATH)
    if rows:
        return rows
    return [
        {"weather": "normal", "goal_multiplier": 1.0, "pressing_penalty": 0.0, "set_piece_bonus": 0.0, "keeper_handling_penalty": 0.0, "source": "starter-prior", "updated_at": updated_at},
        {"weather": "heat", "goal_multiplier": 0.93, "pressing_penalty": 0.055, "set_piece_bonus": 0.0, "keeper_handling_penalty": 0.0, "source": "historical-weather-prior", "updated_at": updated_at},
        {"weather": "rain", "goal_multiplier": 0.90, "pressing_penalty": 0.025, "set_piece_bonus": 0.045, "keeper_handling_penalty": 0.035, "source": "historical-weather-prior", "updated_at": updated_at},
        {"weather": "cold", "goal_multiplier": 0.96, "pressing_penalty": 0.015, "set_piece_bonus": 0.025, "keeper_handling_penalty": 0.012, "source": "historical-weather-prior", "updated_at": updated_at},
        {"weather": "altitude", "goal_multiplier": 0.92, "pressing_penalty": 0.04, "set_piece_bonus": 0.01, "keeper_handling_penalty": 0.0, "source": "historical-weather-prior", "updated_at": updated_at},
    ]


def build_live_team_state(squads_by_team: dict[str, list[dict[str, str]]], updated_at: str) -> list[dict[str, Any]]:
    completed = []
    if LIVE_STATE_PATH.exists():
        try:
            payload = json.loads(LIVE_STATE_PATH.read_text(encoding="utf-8"))
            completed = payload.get("completed_matches", [])
        except json.JSONDecodeError:
            completed = []

    goals_for: Counter[str] = Counter()
    goals_against: Counter[str] = Counter()
    matches: Counter[str] = Counter()
    for match in completed:
        team_a = match.get("team_a")
        team_b = match.get("team_b")
        if not team_a or not team_b:
            continue
        score_a = int(match.get("team_a_score", 0))
        score_b = int(match.get("team_b_score", 0))
        goals_for[team_a] += score_a
        goals_against[team_a] += score_b
        goals_for[team_b] += score_b
        goals_against[team_b] += score_a
        matches[team_a] += 1
        matches[team_b] += 1

    rows = []
    for team in sorted(squads_by_team):
        games = matches[team]
        goal_delta = (goals_for[team] - goals_against[team]) / games if games else 0.0
        rows.append(
            {
                "team": team,
                "posterior_strength_delta": round(goal_delta * 2.5, 3),
                "live_xg_for": "",
                "live_xg_against": "",
                "injury_load": 0.0,
                "momentum": round(goal_delta, 3),
                "matches_played": int(games),
                "source": "live_state.json",
                "updated_at": updated_at,
            }
        )
    return rows


def build_freeze_frame_signals(updated_at: str) -> list[dict[str, Any]]:
    provider = provider_rows_by_key(FREEZE_FRAME_SIGNALS_PATH, "team")
    grouped: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in read_csv(XG_TEAM_ZONES_PATH):
        team = row.get("team")
        if not team:
            continue
        shots = to_float(row.get("shots"))
        avg_xg = to_float(row.get("avg_xg"))
        predicted = to_float(row.get("predicted_goals"))
        grouped[team]["shots"] += shots
        grouped[team]["predicted"] += predicted
        zone_text = f"{row.get('x_zone', '')} {row.get('y_zone', '')}".lower()
        if any(word in zone_text for word in ("six-yard", "central box", "tap-in")):
            grouped[team]["box_shots"] += shots
            grouped[team]["lane_quality"] += shots * avg_xg
        if "central" in zone_text:
            grouped[team]["central_shots"] += shots

    rows = []
    for team, values in grouped.items():
        if team in provider:
            rows.append(provider[team])
            continue
        shots = max(values["shots"], 1.0)
        box_density = values["box_shots"] / shots
        lane_quality = values["lane_quality"] / max(values["box_shots"], 1.0)
        central = values["central_shots"] / shots
        rows.append(
            {
                "team": team,
                "box_density_attack": round(clamp(45 + box_density * 55, 0, 100), 2),
                "shot_lane_quality": round(clamp(45 + lane_quality * 130, 0, 100), 2),
                "defensive_compactness": round(clamp(78 - central * 18, 35, 96), 2),
                "keeper_positioning": round(clamp(70 + (0.12 - (values["predicted"] / shots)) * 80, 35, 96), 2),
                "source": "xg-team-zones-derived",
                "updated_at": updated_at,
            }
        )
    return rows


def main() -> None:
    updated_at = datetime.now(timezone.utc).isoformat()
    squads = read_csv(SQUADS_PATH)
    squads_by_team = group_by_team(squads)
    player_features = load_feature_map(PLAYER_TEAM_FEATURES_PATH)
    team_features = load_feature_map(TEAM_ADVANCED_FEATURES_PATH)

    write_csv(
        AVAILABILITY_PATH,
        build_availability(squads, updated_at),
        ["match_id", "team", "player", "player_id", "status", "category", "start_date", "end_date", "availability", "minutes_limit", "impact_score", "source", "updated_at"],
    )
    write_csv(
        CONFIRMED_LINEUPS_PATH,
        build_confirmed_lineups(squads, updated_at),
        ["match_id", "team", "player", "starter", "position", "role", "formation", "confidence", "confirmed", "source", "updated_at"],
    )
    write_csv(
        MARKET_SIGNALS_PATH,
        build_market_signals(updated_at),
        ["event", "team_a", "team_b", "market_probability_a", "market_probability_draw", "market_probability_b", "opening_probability_a", "opening_probability_b", "line_movement_a", "line_movement_b", "bookmaker", "source", "notes", "updated_at"],
    )
    write_csv(
        TACTICAL_PROFILES_PATH,
        build_tactical_profiles(squads_by_team, player_features, team_features, updated_at),
        ["team", "formation", "pressing", "build_up", "transition", "defensive_line", "width", "source", "updated_at"],
    )
    write_csv(
        SET_PIECE_PROFILES_PATH,
        build_set_piece_profiles(squads_by_team, player_features, team_features, updated_at),
        ["team", "corner_xg", "free_kick_xg", "aerial_threat", "delivery_quality", "set_piece_concede_risk", "source", "updated_at"],
    )
    write_csv(
        GOALKEEPER_PROFILES_PATH,
        build_goalkeeper_profiles(squads_by_team, player_features, updated_at),
        ["team", "keeper", "save_pct", "post_shot_xg_prevented_per90", "claim_rate", "sweeper_rate", "source", "updated_at"],
    )
    write_csv(
        REFEREE_PROFILES_PATH,
        build_referee_profiles(updated_at),
        ["referee", "cards_per_match", "penalties_per_match", "fouls_per_match", "var_intervention_rate", "home_bias", "source", "updated_at"],
    )
    write_csv(
        WEATHER_EFFECTS_PATH,
        build_weather_effects(updated_at),
        ["weather", "goal_multiplier", "pressing_penalty", "set_piece_bonus", "keeper_handling_penalty", "source", "updated_at"],
    )
    write_csv(
        LIVE_TEAM_STATE_PATH,
        build_live_team_state(squads_by_team, updated_at),
        ["team", "posterior_strength_delta", "live_xg_for", "live_xg_against", "injury_load", "momentum", "matches_played", "source", "updated_at"],
    )
    write_csv(
        FREEZE_FRAME_SIGNALS_PATH,
        build_freeze_frame_signals(updated_at),
        ["team", "box_density_attack", "shot_lane_quality", "defensive_compactness", "keeper_positioning", "source", "updated_at"],
    )

    print("Advanced context tables written to data/.")


if __name__ == "__main__":
    main()
