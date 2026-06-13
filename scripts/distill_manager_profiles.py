#!/usr/bin/env python3
"""Distill observed manager-match rows into transparent manager features."""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from predict_worldcup import ROOT


MANAGERS_PATH = ROOT / "data" / "managers.csv"
HISTORY_PATH = ROOT / "data" / "manager_match_history.csv"
OUTPUT_PATH = ROOT / "data" / "manager_features.csv"
FIELDS = [
    "manager_id",
    "manager_name",
    "team",
    "sample_size",
    "weighted_points_per_match",
    "opponent_adjusted_points",
    "weighted_goal_difference",
    "preferred_formation",
    "formation_share",
    "pressing_score",
    "defensive_line_score",
    "build_up_directness_score",
    "possession_score",
    "transition_score",
    "set_piece_score",
    "substitution_aggression_score",
    "evidence_confidence",
    "data_quality",
    "source",
    "last_observed",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def points(row: dict[str, str]) -> float:
    goals_for = number(row, "goals_for")
    goals_against = number(row, "goals_against")
    return 3.0 if goals_for > goals_against else 1.0 if goals_for == goals_against else 0.0


def weighted_average(rows: list[dict[str, str]], key: str, default: float = 0.0) -> float:
    total = 0.0
    weight_total = 0.0
    for index, row in enumerate(sorted(rows, key=lambda item: item.get("date", ""), reverse=True)):
        weight = math.pow(0.94, index)
        total += number(row, key, default) * weight
        weight_total += weight
    return total / max(weight_total, 1e-9)


def distill_manager(manager: dict[str, str], rows: list[dict[str, str]]) -> dict[str, Any]:
    sample_size = len(rows)
    if not rows:
        return {
            "manager_id": manager["manager_id"],
            "manager_name": manager["manager_name"],
            "team": manager["team"],
            "sample_size": 0,
            "weighted_points_per_match": "",
            "opponent_adjusted_points": "",
            "weighted_goal_difference": "",
            "preferred_formation": manager.get("preferred_formations", "").split("|")[0],
            "formation_share": "",
            "pressing_score": "",
            "defensive_line_score": "",
            "build_up_directness_score": "",
            "possession_score": "",
            "transition_score": "",
            "set_piece_score": "",
            "substitution_aggression_score": "",
            "evidence_confidence": 0.0,
            "data_quality": "no_observed_history",
            "source": "",
            "last_observed": "",
        }

    ordered = sorted(rows, key=lambda item: item.get("date", ""), reverse=True)
    weights = [math.pow(0.94, index) for index in range(sample_size)]
    weight_total = sum(weights)
    ppg = sum(points(row) * weight for row, weight in zip(ordered, weights)) / weight_total
    adjusted = sum(
        (points(row) - 1.0) * (0.75 + number(row, "opponent_strength", 70) / 100) * weight
        for row, weight in zip(ordered, weights)
    ) / weight_total
    goal_difference = sum(
        (number(row, "goals_for") - number(row, "goals_against")) * weight
        for row, weight in zip(ordered, weights)
    ) / weight_total
    formations = Counter(row.get("formation", "") for row in rows if row.get("formation"))
    preferred, formation_count = formations.most_common(1)[0] if formations else ("", 0)
    confidence = min(0.95, sample_size / 30) * min(1.0, len({row.get("source") for row in rows if row.get("source")}) / 2 + 0.5)
    return {
        "manager_id": manager["manager_id"],
        "manager_name": manager["manager_name"],
        "team": manager["team"],
        "sample_size": sample_size,
        "weighted_points_per_match": round(ppg, 3),
        "opponent_adjusted_points": round(adjusted, 3),
        "weighted_goal_difference": round(goal_difference, 3),
        "preferred_formation": preferred,
        "formation_share": round(formation_count / sample_size, 3),
        "pressing_score": round(clamp(100 - weighted_average(rows, "ppda", 15) * 4), 2),
        "defensive_line_score": round(clamp(weighted_average(rows, "defensive_line_height", 50)), 2),
        "build_up_directness_score": round(clamp(weighted_average(rows, "build_up_directness", 50)), 2),
        "possession_score": round(clamp(weighted_average(rows, "possession_share", 0.5) * 100), 2),
        "transition_score": round(clamp(weighted_average(rows, "transition_attacks", 5) * 8), 2),
        "set_piece_score": round(clamp(weighted_average(rows, "set_piece_xg", 0.25) * 100), 2),
        "substitution_aggression_score": round(
            clamp((90 - weighted_average(rows, "first_sub_minute", 65)) * 2 + weighted_average(rows, "substitution_count", 3) * 8),
            2,
        ),
        "evidence_confidence": round(confidence, 3),
        "data_quality": "observed" if sample_size >= 10 else "limited_observed_sample",
        "source": "|".join(sorted({row.get("source", "") for row in rows if row.get("source")})),
        "last_observed": ordered[0].get("date", ""),
    }


def distill(managers: list[dict[str, str]], history: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_manager: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in history:
        if row.get("manager_id"):
            by_manager[row["manager_id"]].append(row)
    return [distill_manager(manager, by_manager[manager["manager_id"]]) for manager in managers]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Distill manager-match observations into transparent profiles.")
    parser.add_argument("--history", type=Path, default=HISTORY_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    rows = distill(read_csv(MANAGERS_PATH), read_csv(args.history))
    write_csv(args.output, rows)
    observed = sum(int(row["sample_size"]) > 0 for row in rows)
    print(f"Saved {args.output} ({observed}/{len(rows)} managers with observed match history) on {date.today().isoformat()}")


if __name__ == "__main__":
    main()
