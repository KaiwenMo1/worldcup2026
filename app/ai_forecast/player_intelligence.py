"""Compare tournament players by position and derive transparent match deductions."""

from __future__ import annotations

import csv
import math
import unicodedata
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLAYER_STATS_PATH = ROOT / "data" / "player_match_stats.csv"
INJURY_SIGNALS_PATH = ROOT / "data" / "derived" / "injury_risk_signals.csv"


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _number(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key) or default)
    except (TypeError, ValueError):
        return default


def _key(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char)
    ).casefold().strip()


def _position(row: dict[str, str]) -> str:
    raw = f"{row.get('position', '')} {row.get('detailed_position', '')}".casefold()
    if "goalkeeper" in raw or row.get("position") == "GK":
        return "GK"
    if row.get("position") == "DF" or any(token in raw for token in ("back", "defender")):
        return "DF"
    if row.get("position") == "MF" or "midfield" in raw:
        return "MF"
    return "FW"


def _impact(row: dict[str, str]) -> float:
    position = _position(row)
    if position == "GK":
        return (
            _number(row, "save_pct") * 0.55
            + (50 + 25 * _number(row, "post_shot_xg_prevented_per90")) * 0.25
            + _number(row, "keeper_sweeper_actions_per90") * 5
            + _number(row, "keeper_claims_per90") * 3
        )
    attack = (
        _number(row, "xg_per90") * 30
        + _number(row, "xa_per90") * 22
        + _number(row, "shots_on_target_per90") * 5
        + _number(row, "key_passes_per90") * 4
        + _number(row, "progressive_carries_per90") * 1.8
    )
    control = (
        _number(row, "pass_completion_pct") * 0.28
        + _number(row, "progressive_passes_per90") * 2.5
        + _number(row, "pressure_success_pct") * 0.18
    )
    defense = (
        _number(row, "tackles_interceptions_per90") * 5
        + _number(row, "aerial_win_pct") * 0.22
        + _number(row, "ball_recoveries_per90") * 2.2
    )
    weights = {
        "FW": (0.62, 0.25, 0.13),
        "MF": (0.32, 0.45, 0.23),
        "DF": (0.12, 0.32, 0.56),
    }[position]
    return attack * weights[0] + control * weights[1] + defense * weights[2]


def _percentile(value: float, pool: list[float]) -> int:
    if not pool:
        return 50
    return round(100 * sum(item <= value for item in pool) / len(pool))


def _goal_window(row: dict[str, str]) -> str:
    windows = [
        ("0-15", _number(row, "goals_0_15_share")),
        ("16-30", _number(row, "goals_16_30_share")),
        ("31-45", _number(row, "goals_31_45_share")),
        ("46-60", _number(row, "goals_46_60_share")),
        ("61-75", _number(row, "goals_61_75_share")),
        ("76-90", _number(row, "goals_76_90_share")),
    ]
    return max(windows, key=lambda item: item[1])[0]


def _stamina(row: dict[str, str]) -> float:
    appearances = max(_number(row, "appearances"), 1)
    start_rate = _number(row, "starts") / appearances
    minutes_per_appearance = _number(row, "season_minutes") / appearances
    late_share = _number(row, "goals_76_90_share") + _number(row, "goals_61_75_share")
    return round(max(0, min(100, 55 * start_rate + 0.35 * minutes_per_appearance + 20 * late_share)), 1)


def _availability() -> dict[tuple[str, str], dict[str, str]]:
    return {
        (_key(row.get("team", "")), _key(row.get("player", ""))): row
        for row in _rows(INJURY_SIGNALS_PATH)
    }


def _quality(source: str) -> str:
    return "observed" if source and "estimated" not in source and "projection" not in source else "estimated_fallback"


def _profile(row: dict[str, str], pools: dict[str, list[float]], availability: dict[tuple[str, str], dict[str, str]]) -> dict[str, Any]:
    impact = _impact(row)
    position = _position(row)
    availability_row = availability.get((_key(row.get("team", "")), _key(row.get("player", ""))), {})
    available = _number(availability_row, "availability_probability", _number(row, "availability", 1.0))
    expected_minutes = round(
        _number(availability_row, "expected_minutes", min(90, _number(row, "season_minutes") / max(_number(row, "appearances"), 1)))
    )
    return {
        "player": row.get("player"),
        "team": row.get("team"),
        "position": position,
        "detailed_position": row.get("detailed_position"),
        "club": row.get("club"),
        "preferred_foot": row.get("preferred_foot") or "Unknown",
        "projected_starter": row.get("projected_starter") in {"1", "true", "True"},
        "impact_score": round(impact, 2),
        "position_percentile": _percentile(impact, pools[position]),
        "xg_per90": round(_number(row, "xg_per90"), 3),
        "xa_per90": round(_number(row, "xa_per90"), 3),
        "pass_completion_pct": round(_number(row, "pass_completion_pct"), 1),
        "pressure_success_pct": round(_number(row, "pressure_success_pct"), 1),
        "tackle_success_pct": round(_number(row, "tackle_success_pct"), 1),
        "aerial_win_pct": round(_number(row, "aerial_win_pct"), 1),
        "stamina_score": _stamina(row),
        "likely_scoring_window": _goal_window(row),
        "availability_probability": round(available, 3),
        "expected_minutes": expected_minutes,
        "availability_status": availability_row.get("status") or "available",
        "availability_risk": round(1 - available, 3),
        "data_quality": _quality(row.get("source", "")),
        "source": row.get("source"),
    }


def _scorer_watch(players: list[dict[str, Any]], expected_goals: float) -> list[dict[str, Any]]:
    candidates = [player for player in players if player["position"] != "GK" and player["projected_starter"]]
    weights = [
        max(0.01, player["xg_per90"] * max(player["expected_minutes"], 20) / 90 * player["availability_probability"])
        for player in candidates
    ]
    total = sum(weights) or 1.0
    output = []
    for player, weight in zip(candidates, weights):
        player_lambda = expected_goals * weight / total
        output.append(
            {
                **player,
                "expected_goals_share": round(player_lambda, 3),
                "score_probability": round(100 * (1 - math.exp(-player_lambda)), 1),
                "reason": (
                    f"{player['position_percentile']}th-position-percentile impact, "
                    f"{player['xg_per90']:.2f} xG/90, expected around {player['expected_minutes']} minutes."
                ),
            }
        )
    return sorted(output, key=lambda item: item["score_probability"], reverse=True)[:5]


def build_player_matchup_intelligence(
    team_a: str,
    team_b: str,
    expected_goals_a: float = 1.2,
    expected_goals_b: float = 1.2,
) -> dict[str, Any]:
    rows = _rows(PLAYER_STATS_PATH)
    pools: defaultdict[str, list[float]] = defaultdict(list)
    for row in rows:
        pools[_position(row)].append(_impact(row))
    availability = _availability()
    profiles = [_profile(row, pools, availability) for row in rows if row.get("team") in {team_a, team_b}]
    by_team = {
        team: sorted(
            [player for player in profiles if player["team"] == team],
            key=lambda player: (not player["projected_starter"], -player["impact_score"]),
        )
        for team in (team_a, team_b)
    }
    advantages = []
    for position in ("GK", "DF", "MF", "FW"):
        first = [player for player in by_team[team_a] if player["position"] == position and player["projected_starter"]]
        second = [player for player in by_team[team_b] if player["position"] == position and player["projected_starter"]]
        first_score = mean(player["impact_score"] for player in first) if first else 0
        second_score = mean(player["impact_score"] for player in second) if second else 0
        advantages.append(
            {
                "position": position,
                "favored_team": team_a if first_score > second_score else team_b if second_score > first_score else None,
                "edge": round(abs(first_score - second_score), 2),
                "team_a_score": round(first_score, 2),
                "team_b_score": round(second_score, 2),
                "team_a_leader": first[0]["player"] if first else None,
                "team_b_leader": second[0]["player"] if second else None,
            }
        )
    quality_counts = defaultdict(int)
    for player in profiles:
        quality_counts[player["data_quality"]] += 1
    return {
        "teams": {team_a: by_team[team_a][:15], team_b: by_team[team_b][:15]},
        "position_advantages": advantages,
        "scorer_watch": {
            team_a: _scorer_watch(by_team[team_a], expected_goals_a),
            team_b: _scorer_watch(by_team[team_b], expected_goals_b),
        },
        "availability_risks": sorted(
            [player for player in profiles if player["availability_risk"] > 0.08],
            key=lambda player: player["availability_risk"] * player["impact_score"],
            reverse=True,
        )[:8],
        "data_quality": dict(quality_counts),
        "metric_note": "Position percentiles compare the player's transparent impact score with all tournament players in the same broad position.",
        "risk_note": "Availability risk is based on current reports, not a claim that a player is historically injury-prone.",
    }
