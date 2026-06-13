#!/usr/bin/env python3
"""Build normal-time player stats and team aggregates for forecast adjustments.

The default output is an estimated starter profile from current squad data. If a
licensed/stat-provider CSV is available, pass it with --provider-stats and any
matching numeric columns will override the estimates.
"""

from __future__ import annotations

import argparse
import csv
import math
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from predict_worldcup import ROOT


SQUADS_PATH = ROOT / "data" / "worldcup_squads.csv"
PENALTY_KICKS_PATH = ROOT / "data" / "penalty_kicks.csv"
PLAYER_MATCH_STATS_PATH = ROOT / "data" / "player_match_stats.csv"
PLAYER_MATCH_TEAM_FEATURES_PATH = ROOT / "data" / "player_match_team_features.csv"

PLAYER_MATCH_STATS_COLUMNS = [
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
    "goals_per90",
    "assists_per90",
    "xg_per90",
    "xa_per90",
    "shots_per90",
    "shots_on_target_per90",
    "touches_att_pen_area_per90",
    "key_passes_per90",
    "passes_attempted_per90",
    "pass_completion_pct",
    "progressive_passes_per90",
    "progressive_carries_per90",
    "successful_dribbles_per90",
    "dribble_success_pct",
    "crosses_per90",
    "cross_completion_pct",
    "through_balls_per90",
    "set_piece_xa_per90",
    "pressures_per90",
    "pressure_success_pct",
    "tackles_interceptions_per90",
    "tackle_success_pct",
    "blocks_clearances_per90",
    "aerial_win_pct",
    "ball_recoveries_per90",
    "fouls_committed_per90",
    "cards_per90",
    "offsides_per90",
    "goals_0_15_share",
    "goals_16_30_share",
    "goals_31_45_share",
    "goals_46_60_share",
    "goals_61_75_share",
    "goals_76_90_share",
    "saves_per90",
    "save_pct",
    "post_shot_xg_prevented_per90",
    "keeper_claims_per90",
    "keeper_sweeper_actions_per90",
    "keeper_dives_per90",
    "keeper_long_pass_completion_pct",
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
]

PLAYER_MATCH_TEAM_FEATURE_COLUMNS = [
    "team",
    "player_shooting_score",
    "player_chance_creation_score",
    "player_passing_score",
    "player_progression_score",
    "player_pressing_score",
    "player_defensive_activity_score",
    "player_goalkeeping_score",
    "player_keeper_sweeping_score",
    "player_keeper_diving_score",
    "player_set_piece_delivery_score",
    "player_early_goal_score",
    "player_late_goal_score",
    "player_discipline_score",
    "player_minutes_score",
]

NUMERIC_COLUMNS = set(PLAYER_MATCH_STATS_COLUMNS) - {
    "team",
    "player",
    "position",
    "detailed_position",
    "club",
    "preferred_foot",
    "tactical_role",
    "formation_role",
    "tactic_profile",
    "penalty_preferred_placement",
    "keeper_penalty_dive_preference",
    "source",
    "updated_at",
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return "".join(char for char in text.lower() if char.isalnum())


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
        writer.writerows(rows)


def percentile_scores(values: dict[str, float], low: float = 55.0, high: float = 96.0) -> dict[str, float]:
    ordered = sorted(values.items(), key=lambda item: item[1])
    if len(ordered) <= 1:
        return {team: 70.0 for team in values}
    output = {}
    for rank, (team, _) in enumerate(ordered):
        output[team] = low + ((high - low) * rank / (len(ordered) - 1))
    return output


def player_quality(player: dict[str, Any]) -> float:
    market = float(player.get("market_value_eur") or 0)
    value_score = math.log1p(market) / math.log1p(220_000_000)
    caps_score = min(float(player.get("caps") or 0) / 85, 1.0)
    goal_denominator = 36 if player.get("position") == "FW" else 22 if player.get("position") == "MF" else 12
    goals_score = min(float(player.get("international_goals") or 0) / goal_denominator, 1.0)
    return clamp((0.62 * value_score) + (0.24 * caps_score) + (0.14 * goals_score), 0.05, 1.0)


def role_flags(player: dict[str, Any]) -> dict[str, float]:
    text = f"{player.get('position', '')} {player.get('detailed_position', '')}".lower()
    return {
        "wide": float(any(word in text for word in ("wing", "right-back", "left-back", "right midfield", "left midfield"))),
        "striker": float(any(word in text for word in ("forward", "striker", "centre-forward"))),
        "creator": float(any(word in text for word in ("attacking midfield", "central midfield", "winger", "second striker"))),
        "holder": float(any(word in text for word in ("defensive midfield", "centre-back", "back"))),
    }


LEFT_FOOTED_PLAYERS = {
    "Lionel Messi",
    "Mohamed Salah",
    "Bukayo Saka",
    "Lamine Yamal",
    "Phil Foden",
    "Antoine Griezmann",
    "Raphinha",
    "Angel Di Maria",
    "Leroy Sane",
    "Federico Dimarco",
    "Theo Hernandez",
    "Lucas Digne",
    "David Alaba",
    "Andrew Robertson",
    "Oleksandr Zinchenko",
}


def infer_preferred_foot(player: dict[str, Any], role: dict[str, float]) -> str:
    name_key = normalize_name(player.get("player", ""))
    if any(normalize_name(name) == name_key for name in LEFT_FOOTED_PLAYERS):
        return "Left"
    detailed = str(player.get("detailed_position", "")).lower()
    if "left" in detailed and role["wide"]:
        return "Left"
    return "Right"


def tactical_labels(player: dict[str, Any], role: dict[str, float]) -> tuple[str, str, str]:
    position = player.get("position", "")
    detailed = str(player.get("detailed_position") or position)
    if position == "GK":
        return "Goalkeeper", "Sweeper keeper", "Build-up keeper"
    if "Centre-Back" in detailed:
        return "Centre-back", "Ball-playing defender", "Rest-defense anchor"
    if "Back" in detailed:
        return "Fullback", "Overlapping wide defender", "Width + recovery runner"
    if "Defensive Midfield" in detailed:
        return "No. 6", "Holding midfielder", "Press resistance + ball winning"
    if "Attacking Midfield" in detailed:
        return "No. 10", "Central creator", "Between-lines chance creation"
    if "Winger" in detailed:
        return "Winger", "Wide creator", "1v1 carry + crossing threat"
    if "Forward" in detailed or "Striker" in detailed:
        return "No. 9", "Penalty-box finisher", "Depth runs + shot volume"
    if position == "MF":
        return "No. 8", "Box-to-box midfielder", "Progression + counter-press"
    return position or "Player", "Hybrid role", "Balanced phase contribution"


def penalty_profiles() -> dict[tuple[str, str], dict[str, Any]]:
    profiles: defaultdict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {
        "placements": {"Left": 0, "Center": 0, "Right": 0},
        "outcomes": {"Goal": 0, "Saved": 0, "Missed": 0},
        "keeper_dives": {"Left": 0, "Center": 0, "Right": 0},
        "keeper_outcomes": {"Goal": 0, "Saved": 0, "Missed": 0},
        "kicker_foot": "",
        "keeper_foot": "",
    })
    for row in read_csv(PENALTY_KICKS_PATH):
        team = row.get("team", "")
        kicker = row.get("kicker", "")
        keeper_team = row.get("goalkeeper_team", "")
        keeper = row.get("goalkeeper", "")
        placement = row.get("shot_placement", "")
        dive = row.get("keeper_dive", "")
        outcome = row.get("outcome", "")
        if team and kicker:
            profile = profiles[(normalize_name(team), normalize_name(kicker))]
            profile["kicker_foot"] = row.get("kicker_foot") or profile["kicker_foot"]
            if placement in profile["placements"]:
                profile["placements"][placement] += 1
            if outcome in profile["outcomes"]:
                profile["outcomes"][outcome] += 1
        if keeper_team and keeper:
            profile = profiles[(normalize_name(keeper_team), normalize_name(keeper))]
            profile["keeper_foot"] = row.get("keeper_foot") or profile["keeper_foot"]
            if dive in profile["keeper_dives"]:
                profile["keeper_dives"][dive] += 1
            if outcome in profile["keeper_outcomes"]:
                profile["keeper_outcomes"][outcome] += 1
    return profiles


def pct(count: int, total: int) -> float:
    return round(100 * count / total, 1) if total else 0.0


def penalty_profile_fields(profile: dict[str, Any] | None, preferred_foot: str) -> dict[str, Any]:
    if not profile:
        return {
            "penalty_taken_count": 0,
            "penalty_goal_pct": 0.0,
            "penalty_preferred_placement": "Unknown",
            "penalty_left_pct": 0.0,
            "penalty_center_pct": 0.0,
            "penalty_right_pct": 0.0,
            "penalty_saved_pct": 0.0,
            "penalty_miss_pct": 0.0,
            "keeper_penalty_faced": 0,
            "keeper_penalty_save_pct": 0.0,
            "keeper_penalty_dive_preference": "Unknown",
            "keeper_penalty_dive_left_pct": 0.0,
            "keeper_penalty_dive_center_pct": 0.0,
            "keeper_penalty_dive_right_pct": 0.0,
            "preferred_foot": preferred_foot,
        }
    placements = profile["placements"]
    outcomes = profile["outcomes"]
    keeper_dives = profile["keeper_dives"]
    keeper_outcomes = profile["keeper_outcomes"]
    taken = sum(placements.values())
    faced = sum(keeper_dives.values())
    preferred_placement = max(placements.items(), key=lambda item: item[1])[0] if taken else "Unknown"
    dive_preference = max(keeper_dives.items(), key=lambda item: item[1])[0] if faced else "Unknown"
    return {
        "penalty_taken_count": taken,
        "penalty_goal_pct": pct(outcomes["Goal"], taken),
        "penalty_preferred_placement": preferred_placement,
        "penalty_left_pct": pct(placements["Left"], taken),
        "penalty_center_pct": pct(placements["Center"], taken),
        "penalty_right_pct": pct(placements["Right"], taken),
        "penalty_saved_pct": pct(outcomes["Saved"], taken),
        "penalty_miss_pct": pct(outcomes["Missed"], taken),
        "keeper_penalty_faced": faced,
        "keeper_penalty_save_pct": pct(keeper_outcomes["Saved"], faced),
        "keeper_penalty_dive_preference": dive_preference,
        "keeper_penalty_dive_left_pct": pct(keeper_dives["Left"], faced),
        "keeper_penalty_dive_center_pct": pct(keeper_dives["Center"], faced),
        "keeper_penalty_dive_right_pct": pct(keeper_dives["Right"], faced),
        "preferred_foot": profile.get("kicker_foot") or profile.get("keeper_foot") or preferred_foot,
    }


def starter_minutes(player: dict[str, Any], quality: float) -> tuple[int, int, int]:
    starter = int(player.get("projected_starter", 0))
    availability = float(player.get("availability", 1.0))
    base_minutes = 2150 if starter else 760
    minutes = int(clamp((base_minutes + (quality * 820)) * availability, 90, 3600))
    appearances = int(clamp(minutes / 73, 2, 60))
    starts = int(clamp(minutes / 92 if starter else minutes / 155, 0, 42))
    return minutes, appearances, starts


def scoring_window_profile(player: dict[str, Any], quality: float) -> dict[str, float]:
    position = player.get("position")
    starter = int(player.get("projected_starter", 0))
    if position == "GK":
        shares = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    elif starter:
        late = 0.20 + (0.08 * quality)
        early = 0.14 + (0.04 * quality)
        shares = [early, 0.15, 0.17, 0.16, 0.17, late]
    else:
        shares = [0.07, 0.09, 0.10, 0.16, 0.22, 0.36]
    total = sum(shares) or 1
    labels = ("0_15", "16_30", "31_45", "46_60", "61_75", "76_90")
    return {f"goals_{label}_share": round(share / total, 3) for label, share in zip(labels, shares)}


def estimate_player_stats(player: dict[str, Any], updated_at: str, penalty_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    position = player.get("position", "")
    quality = player_quality(player)
    role = role_flags(player)
    preferred_foot = infer_preferred_foot(player, role)
    tactical_role, formation_role, tactic_profile = tactical_labels(player, role)
    penalty_fields = penalty_profile_fields(penalty_profile, preferred_foot)
    starter = int(player.get("projected_starter", 0))
    minutes, appearances, starts = starter_minutes(player, quality)
    age = float(player.get("age") or 27)
    age_curve = clamp(1 - abs(age - 27) * 0.018, 0.78, 1.04)
    starter_boost = 1.0 if starter else 0.84

    row = {
        "team": player["team"],
        "player": player["player"],
        "position": position,
        "detailed_position": player.get("detailed_position", ""),
        "club": player.get("club", ""),
        "preferred_foot": penalty_fields["preferred_foot"],
        "weak_foot_usage_pct": round((16 if penalty_fields["preferred_foot"] == "Right" else 19) + (role["wide"] * 5) + (quality * 12), 1),
        "tactical_role": tactical_role,
        "formation_role": formation_role,
        "tactic_profile": tactic_profile,
        "projected_starter": starter,
        "availability": round(float(player.get("availability", 1.0)), 3),
        "season_minutes": minutes,
        "appearances": appearances,
        "starts": starts,
        "source": "estimated_from_squad_profile",
        "updated_at": updated_at,
    }
    if position == "GK":
        row.update(
            {
                "goals_per90": 0.0,
                "assists_per90": 0.01,
                "xg_per90": 0.0,
                "xa_per90": 0.01,
                "shots_per90": 0.0,
                "shots_on_target_per90": 0.0,
                "touches_att_pen_area_per90": 0.02,
                "key_passes_per90": round(0.03 + (quality * 0.05), 2),
                "passes_attempted_per90": round(24 + (quality * 12), 2),
                "pass_completion_pct": round(64 + (quality * 15), 1),
                "progressive_passes_per90": round(2.8 + (quality * 3.2), 2),
                "progressive_carries_per90": round(0.04 + (quality * 0.16), 2),
                "successful_dribbles_per90": 0.0,
                "dribble_success_pct": 0.0,
                "crosses_per90": 0.0,
                "cross_completion_pct": 0.0,
                "through_balls_per90": 0.01,
                "set_piece_xa_per90": 0.0,
                "pressures_per90": round(1.4 + (quality * 1.4), 2),
                "pressure_success_pct": round(24 + (quality * 11), 1),
                "tackles_interceptions_per90": round(0.08 + (quality * 0.15), 2),
                "tackle_success_pct": round(40 + (quality * 18), 1),
                "blocks_clearances_per90": round(0.35 + (quality * 0.35), 2),
                "aerial_win_pct": round(46 + (quality * 14), 1),
                "ball_recoveries_per90": round(3.2 + (quality * 2.0), 2),
                "fouls_committed_per90": round(0.05 + (quality * 0.05), 2),
                "cards_per90": round(0.015 + ((1 - quality) * 0.02), 3),
                "offsides_per90": 0.0,
                "saves_per90": round(2.4 + ((1 - quality) * 0.9), 2),
                "save_pct": round(66 + (quality * 17), 1),
                "post_shot_xg_prevented_per90": round(-0.05 + (quality * 0.20), 3),
                "keeper_claims_per90": round(0.8 + (quality * 1.4), 2),
                "keeper_sweeper_actions_per90": round(0.35 + (quality * 1.5), 2),
                "keeper_dives_per90": round(2.2 + ((1 - quality) * 0.8), 2),
                "keeper_long_pass_completion_pct": round(37 + (quality * 21), 1),
            }
        )
    else:
        is_fw = position == "FW"
        is_mf = position == "MF"
        is_df = position == "DF"
        attack_role = (1.25 if is_fw else 0.82 if is_mf else 0.28) + (0.22 * role["wide"]) + (0.24 * role["creator"])
        defense_role = (1.18 if is_df else 0.95 if is_mf else 0.45) + (0.20 * role["holder"])
        row.update(
            {
                "goals_per90": round((0.04 + quality * 0.42 * attack_role) * starter_boost, 2),
                "assists_per90": round((0.04 + quality * 0.27 * (0.7 + role["creator"] + role["wide"] * 0.4)) * starter_boost, 2),
                "xg_per90": round((0.05 + quality * 0.38 * attack_role) * starter_boost, 2),
                "xa_per90": round((0.03 + quality * 0.25 * (0.75 + role["creator"] + role["wide"] * 0.45)) * starter_boost, 2),
                "shots_per90": round((0.35 + quality * 2.45 * attack_role) * starter_boost, 2),
                "shots_on_target_per90": round((0.13 + quality * 0.95 * attack_role) * starter_boost, 2),
                "touches_att_pen_area_per90": round((0.7 + quality * 5.6 * attack_role) * starter_boost, 2),
                "key_passes_per90": round((0.25 + quality * 1.8 * (0.55 + role["creator"] + role["wide"] * 0.5)) * starter_boost, 2),
                "passes_attempted_per90": round((28 if is_fw else 52 if is_mf else 48) + (quality * 22), 2),
                "pass_completion_pct": round((70 if is_fw else 79 if is_mf else 82) + (quality * 9), 1),
                "progressive_passes_per90": round((1.1 + quality * (2.2 if is_fw else 5.4 if is_mf else 4.3)) * starter_boost, 2),
                "progressive_carries_per90": round((0.7 + quality * (4.3 if is_fw else 3.4 if is_mf else 1.7) + role["wide"]) * starter_boost, 2),
                "successful_dribbles_per90": round((0.25 + quality * (2.2 if is_fw else 1.3 if is_mf else 0.55) + role["wide"] * 0.5) * age_curve, 2),
                "dribble_success_pct": round((45 if is_fw else 50 if is_mf else 54) + (quality * 17) + (role["wide"] * 3), 1),
                "crosses_per90": round((0.25 + quality * (0.9 if is_fw else 0.8 if is_mf else 0.55) + role["wide"] * 1.65) * starter_boost, 2),
                "cross_completion_pct": round((22 if is_fw else 25 if is_mf else 27) + (quality * 12) + (role["wide"] * 2), 1),
                "through_balls_per90": round((0.04 + quality * (0.24 if is_fw else 0.55 if is_mf else 0.18) + role["creator"] * 0.15) * starter_boost, 2),
                "set_piece_xa_per90": round((0.01 + quality * (0.06 if is_fw else 0.13 if is_mf else 0.04) + role["creator"] * 0.04) * starter_boost, 3),
                "pressures_per90": round((9.0 + quality * (7.0 if is_fw else 9.5 if is_mf else 5.0)) * age_curve, 2),
                "pressure_success_pct": round((23 if is_fw else 27 if is_mf else 30) + (quality * 17), 1),
                "tackles_interceptions_per90": round((0.65 + quality * 2.7 * defense_role) * age_curve, 2),
                "tackle_success_pct": round((45 if is_fw else 52 if is_mf else 58) + (quality * 17), 1),
                "blocks_clearances_per90": round((0.45 + quality * (1.3 if is_fw else 1.9 if is_mf else 4.6)) * starter_boost, 2),
                "aerial_win_pct": round((38 if is_fw else 46 if is_mf else 56) + (quality * 17), 1),
                "ball_recoveries_per90": round((3.2 + quality * (2.1 if is_fw else 5.2 if is_mf else 4.4)) * age_curve, 2),
                "fouls_committed_per90": round((0.65 if is_fw else 1.05 if is_mf else 0.95) + ((1 - quality) * 0.55), 2),
                "cards_per90": round((0.08 if is_fw else 0.13 if is_mf else 0.16) + ((1 - quality) * 0.07), 3),
                "offsides_per90": round((0.12 if is_fw else 0.03 if is_mf else 0.01) + (quality * (0.34 if is_fw else 0.04)), 2),
                "saves_per90": 0.0,
                "save_pct": 0.0,
                "post_shot_xg_prevented_per90": 0.0,
                "keeper_claims_per90": 0.0,
                "keeper_sweeper_actions_per90": 0.0,
                "keeper_dives_per90": 0.0,
                "keeper_long_pass_completion_pct": 0.0,
            }
        )
    row.update(scoring_window_profile(player, quality))
    row.update({key: value for key, value in penalty_fields.items() if key != "preferred_foot"})
    return {key: row.get(key, "") for key in PLAYER_MATCH_STATS_COLUMNS}


def provider_overrides(path: Path | None) -> dict[tuple[str, str], dict[str, str]]:
    if not path:
        return {}
    rows = read_csv(path)
    return {
        (normalize_name(row.get("team", "")), normalize_name(row.get("player", ""))): row
        for row in rows
        if row.get("team") and row.get("player")
    }


def apply_provider_override(row: dict[str, Any], override: dict[str, str] | None) -> dict[str, Any]:
    if not override:
        return row
    output = dict(row)
    for key, value in override.items():
        if key in NUMERIC_COLUMNS and value not in {"", None}:
            try:
                output[key] = round(float(value), 3)
            except ValueError:
                continue
        elif key in output and value not in {"", None}:
            output[key] = value
    output["source"] = override.get("source") or "provider_stats_csv"
    return output


def weighted_average(rows: list[dict[str, Any]], key: str, predicate: Any | None = None) -> float:
    total = 0.0
    weight_total = 0.0
    for row in rows:
        if predicate and not predicate(row):
            continue
        weight = (1.0 if int(row["projected_starter"]) else 0.38) * float(row["availability"]) * min(float(row["season_minutes"]) / 2200, 1.25)
        total += float(row[key]) * weight
        weight_total += weight
    return total / max(weight_total, 0.001)


def team_raw_features(player_rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in player_rows:
        grouped[row["team"]].append(row)

    raw = {}
    for team, rows in grouped.items():
        field_players = [row for row in rows if row["position"] != "GK"]
        keepers = [row for row in rows if row["position"] == "GK"]
        starter_keeper = sorted(keepers, key=lambda row: (int(row["projected_starter"]), float(row["season_minutes"])), reverse=True)
        keeper = starter_keeper[0] if starter_keeper else {}
        raw[team] = {
            "shooting": weighted_average(field_players, "xg_per90") * 1.7
            + weighted_average(field_players, "shots_on_target_per90") * 0.5
            + weighted_average(field_players, "touches_att_pen_area_per90") * 0.12,
            "chance_creation": weighted_average(field_players, "xa_per90") * 2.0
            + weighted_average(field_players, "key_passes_per90") * 0.5
            + weighted_average(field_players, "through_balls_per90") * 0.8,
            "passing": weighted_average(field_players, "pass_completion_pct") * 0.05
            + weighted_average(field_players, "passes_attempted_per90") * 0.035
            + weighted_average(field_players, "progressive_passes_per90") * 0.28,
            "progression": weighted_average(field_players, "progressive_carries_per90") * 0.44
            + weighted_average(field_players, "successful_dribbles_per90") * 0.62
            + weighted_average(field_players, "dribble_success_pct") * 0.015,
            "pressing": weighted_average(field_players, "pressures_per90") * 0.8
            + weighted_average(field_players, "pressure_success_pct") * 0.12,
            "defensive_activity": weighted_average(field_players, "tackles_interceptions_per90") * 1.15
            + weighted_average(field_players, "tackle_success_pct") * 0.035
            + weighted_average(field_players, "blocks_clearances_per90") * 0.5
            + weighted_average(field_players, "ball_recoveries_per90") * 0.35,
            "goalkeeping": float(keeper.get("save_pct", 68)) * 0.06 + float(keeper.get("post_shot_xg_prevented_per90", 0)) * 12,
            "keeper_sweeping": float(keeper.get("keeper_sweeper_actions_per90", 0)) + float(keeper.get("keeper_claims_per90", 0)) * 0.45,
            "keeper_diving": float(keeper.get("keeper_dives_per90", 0)) * 0.7 + float(keeper.get("saves_per90", 0)) * 0.45,
            "set_piece_delivery": weighted_average(field_players, "set_piece_xa_per90") * 10 + weighted_average(field_players, "crosses_per90") * 0.18,
            "early_goal": weighted_average(field_players, "goals_0_15_share"),
            "late_goal": weighted_average(field_players, "goals_76_90_share"),
            "discipline": -weighted_average(field_players, "cards_per90") * 3.5 - weighted_average(field_players, "fouls_committed_per90") * 0.4,
            "minutes": weighted_average(rows, "season_minutes"),
        }
    return raw


def team_feature_rows(player_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = team_raw_features(player_rows)
    score_maps = {
        "player_shooting_score": percentile_scores({team: values["shooting"] for team, values in raw.items()}),
        "player_chance_creation_score": percentile_scores({team: values["chance_creation"] for team, values in raw.items()}),
        "player_passing_score": percentile_scores({team: values["passing"] for team, values in raw.items()}),
        "player_progression_score": percentile_scores({team: values["progression"] for team, values in raw.items()}),
        "player_pressing_score": percentile_scores({team: values["pressing"] for team, values in raw.items()}),
        "player_defensive_activity_score": percentile_scores({team: values["defensive_activity"] for team, values in raw.items()}),
        "player_goalkeeping_score": percentile_scores({team: values["goalkeeping"] for team, values in raw.items()}),
        "player_keeper_sweeping_score": percentile_scores({team: values["keeper_sweeping"] for team, values in raw.items()}),
        "player_keeper_diving_score": percentile_scores({team: values["keeper_diving"] for team, values in raw.items()}),
        "player_set_piece_delivery_score": percentile_scores({team: values["set_piece_delivery"] for team, values in raw.items()}),
        "player_early_goal_score": percentile_scores({team: values["early_goal"] for team, values in raw.items()}),
        "player_late_goal_score": percentile_scores({team: values["late_goal"] for team, values in raw.items()}),
        "player_discipline_score": percentile_scores({team: values["discipline"] for team, values in raw.items()}),
        "player_minutes_score": percentile_scores({team: values["minutes"] for team, values in raw.items()}),
    }
    rows = []
    for team in sorted(raw):
        output = {"team": team}
        for column in PLAYER_MATCH_TEAM_FEATURE_COLUMNS:
            if column == "team":
                continue
            output[column] = round(score_maps[column][team], 2)
        rows.append(output)
    return rows


def build_player_match_outputs(players: list[dict[str, Any]], fetched_at: str, provider_stats: Path | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    overrides = provider_overrides(provider_stats)
    penalties = penalty_profiles()
    player_rows = []
    for player in players:
        profile = penalties.get((normalize_name(player["team"]), normalize_name(player["player"])))
        row = estimate_player_stats(player, fetched_at, profile)
        override = overrides.get((normalize_name(player["team"]), normalize_name(player["player"])))
        player_rows.append(apply_provider_override(row, override))
    return player_rows, team_feature_rows(player_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build normal-time player stats and team aggregate features.")
    parser.add_argument("--provider-stats", type=Path, default=None, help="Optional CSV of real seasonal stats keyed by team/player.")
    args = parser.parse_args()

    players = read_csv(SQUADS_PATH)
    if not players:
        raise SystemExit(f"No squad rows found at {SQUADS_PATH}. Run scripts/sync_squads.py first.")
    fetched_at = datetime.now(timezone.utc).isoformat()
    player_rows, team_rows = build_player_match_outputs(players, fetched_at, args.provider_stats)
    write_csv(PLAYER_MATCH_STATS_PATH, player_rows, PLAYER_MATCH_STATS_COLUMNS)
    write_csv(PLAYER_MATCH_TEAM_FEATURES_PATH, team_rows, PLAYER_MATCH_TEAM_FEATURE_COLUMNS)
    print(f"Saved {PLAYER_MATCH_STATS_PATH} ({len(player_rows)} players)")
    print(f"Saved {PLAYER_MATCH_TEAM_FEATURES_PATH} ({len(team_rows)} teams)")


if __name__ == "__main__":
    main()
