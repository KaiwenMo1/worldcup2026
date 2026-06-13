#!/usr/bin/env python3
"""Train and serve a shot-level expected-goals model."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from predict_worldcup import ROOT


SHOT_EVENTS_PATH = ROOT / "data" / "shot_events.csv"
XG_MODEL_PATH = ROOT / "models" / "xg_shot_model.joblib"
XG_TEAM_ZONES_PATH = ROOT / "data" / "xg_team_zones.csv"

NUMERIC_FEATURES = ["shot_x", "shot_y", "distance_m", "angle_degrees", "minute"]
CATEGORICAL_FEATURES = ["body_part", "assist_type", "defender_pressure", "game_state", "shot_type"]
FEATURE_COLUMNS = [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES]
SHOT_COLUMNS = [
    "event_id",
    "match_id",
    "competition",
    "season",
    "match_date",
    "team",
    "opponent",
    "player",
    "minute",
    "shot_x",
    "shot_y",
    "distance_m",
    "angle_degrees",
    "body_part",
    "assist_type",
    "defender_pressure",
    "game_state",
    "shot_type",
    "is_goal",
    "source",
]


def shot_geometry(shot_x: float, shot_y: float) -> tuple[float, float]:
    goal_x = 120.0
    goal_center_y = 40.0
    left_post_y = 36.0
    right_post_y = 44.0
    dx = max(0.01, goal_x - shot_x)
    distance = math.hypot(dx, shot_y - goal_center_y)
    left = math.hypot(dx, shot_y - left_post_y)
    right = math.hypot(dx, shot_y - right_post_y)
    cosine = max(-1.0, min(1.0, ((left * left) + (right * right) - 64.0) / max(2 * left * right, 1e-9)))
    angle = math.degrees(math.acos(cosine))
    return distance, angle


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    shot_x = float(row.get("shot_x") or row.get("x") or 0)
    shot_y = float(row.get("shot_y") or row.get("y") or 40)
    distance = row.get("distance_m")
    angle = row.get("angle_degrees")
    if distance in (None, "") or angle in (None, ""):
        distance, angle = shot_geometry(shot_x, shot_y)
    return {
        "event_id": row.get("event_id") or row.get("id") or "",
        "match_id": row.get("match_id") or "",
        "competition": row.get("competition") or row.get("competition_name") or "",
        "season": row.get("season") or row.get("season_name") or "",
        "match_date": row.get("match_date") or "",
        "team": row.get("team") or "",
        "opponent": row.get("opponent") or "",
        "player": row.get("player") or "",
        "minute": float(row.get("minute") or 0),
        "shot_x": shot_x,
        "shot_y": shot_y,
        "distance_m": float(distance),
        "angle_degrees": float(angle),
        "body_part": row.get("body_part") or row.get("shot_body_part_name") or "Right Foot",
        "assist_type": row.get("assist_type") or row.get("play_pattern_name") or "Open Play",
        "defender_pressure": row.get("defender_pressure") or ("High" if str(row.get("under_pressure", "")).lower() in {"true", "1"} else "Low"),
        "game_state": row.get("game_state") or "Drawing",
        "shot_type": row.get("shot_type") or row.get("shot_type_name") or "Open Play",
        "is_goal": int(row.get("is_goal") or str(row.get("shot_outcome_name", "")).lower() == "goal"),
        "source": row.get("source") or "imported",
    }


def bootstrap_shots() -> list[dict[str, Any]]:
    teams = [
        ("France", "Kylian Mbappe"),
        ("Brazil", "Vinicius Junior"),
        ("Argentina", "Lionel Messi"),
        ("England", "Harry Kane"),
        ("Spain", "Lamine Yamal"),
        ("Portugal", "Cristiano Ronaldo"),
        ("Germany", "Florian Wirtz"),
        ("Netherlands", "Cody Gakpo"),
    ]
    templates = [
        (116, 40, "Right Foot", "Cutback", "Low", "Drawing", "Open Play", 1),
        (112, 37, "Left Foot", "Through Ball", "Medium", "Trailing", "Open Play", 1),
        (110, 44, "Right Foot", "Cross", "High", "Drawing", "Open Play", 0),
        (108, 40, "Right Foot", "Through Ball", "Medium", "Drawing", "Open Play", 1),
        (105, 34, "Head", "Cross", "High", "Leading", "Open Play", 0),
        (100, 50, "Left Foot", "Dribble", "Medium", "Drawing", "Open Play", 0),
        (95, 40, "Right Foot", "Layoff", "Low", "Trailing", "Open Play", 0),
        (118, 41, "Right Foot", "Rebound", "Medium", "Drawing", "Open Play", 1),
        (108, 31, "Head", "Corner", "High", "Trailing", "Set Piece", 0),
        (90, 25, "Right Foot", "Open Play", "Low", "Leading", "Open Play", 0),
        (113, 48, "Left Foot", "Through Ball", "Medium", "Drawing", "Open Play", 1),
        (104, 42, "Other", "Loose Ball", "High", "Trailing", "Open Play", 0),
        (111, 40, "Right Foot", "Penalty Area Pass", "Low", "Leading", "Open Play", 1),
    ]
    rows = []
    event_id = 1
    for team_index, (team, player) in enumerate(teams):
        opponent = teams[(team_index + 3) % len(teams)][0]
        for template_index, template in enumerate(templates):
            x, y, body, assist, pressure, state, shot_type, base_goal = template
            distance, angle = shot_geometry(x, y)
            is_goal = int(base_goal and (template_index + team_index) % 5 != 0)
            rows.append(
                {
                    "event_id": f"bootstrap-{event_id}",
                    "match_id": f"bootstrap-{team_index}",
                    "competition": "starter sample",
                    "season": "2026",
                    "match_date": "2026-06-04",
                    "team": team,
                    "opponent": opponent,
                    "player": player,
                    "minute": 8 + ((template_index * 7 + team_index) % 86),
                    "shot_x": x,
                    "shot_y": y,
                    "distance_m": round(distance, 3),
                    "angle_degrees": round(angle, 3),
                    "body_part": body,
                    "assist_type": assist,
                    "defender_pressure": pressure,
                    "game_state": state,
                    "shot_type": shot_type,
                    "is_goal": is_goal,
                    "source": "starter_sample",
                }
            )
            event_id += 1
    return rows


def write_rows(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_shots(path: Path) -> pd.DataFrame:
    if not path.exists():
        write_rows(path, bootstrap_shots(), SHOT_COLUMNS)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [normalize_row(row) for row in csv.DictReader(handle)]
    sources = {row["source"] for row in rows}
    if len(rows) < 40 or sources == {"starter_sample"}:
        rows = bootstrap_shots()
        write_rows(path, rows, SHOT_COLUMNS)
    return pd.DataFrame(rows)


def build_pipeline(seed: int) -> Pipeline:
    preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", "passthrough", NUMERIC_FEATURES),
            ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
        ]
    )
    model = GradientBoostingClassifier(
        n_estimators=140,
        learning_rate=0.045,
        max_depth=2,
        random_state=seed,
    )
    return Pipeline([("features", preprocessor), ("model", model)])


def geometry_baseline_xg(row: dict[str, Any]) -> float:
    score = -2.1
    score += 0.035 * float(row["angle_degrees"])
    score -= 0.08 * float(row["distance_m"])
    if row["body_part"] == "Head":
        score -= 0.35
    elif row["body_part"] == "Other":
        score -= 0.20
    if row["defender_pressure"] == "High":
        score -= 0.35
    elif row["defender_pressure"] == "Low":
        score += 0.18
    if row["assist_type"] in {"Cutback", "Through Ball", "Penalty Area Pass"}:
        score += 0.32
    elif row["assist_type"] in {"Corner", "Cross"} and row["body_part"] != "Head":
        score -= 0.12
    if row["shot_type"] == "Set Piece":
        score -= 0.20
    return 1 / (1 + math.exp(-score))


def blended_xg(raw_model_xg: float, row: dict[str, Any]) -> float:
    return max(0.005, min(0.95, (0.68 * raw_model_xg) + (0.32 * geometry_baseline_xg(row))))


def zone_label(row: pd.Series) -> tuple[str, str]:
    if row.shot_x >= 110:
        x_zone = "six-yard / tap-in"
    elif row.shot_x >= 102:
        x_zone = "central box"
    elif row.shot_x >= 88:
        x_zone = "edge of box"
    else:
        x_zone = "long range"
    if row.shot_y < 31:
        y_zone = "left channel"
    elif row.shot_y > 49:
        y_zone = "right channel"
    else:
        y_zone = "central"
    return x_zone, y_zone


def build_zone_table(frame: pd.DataFrame) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[pd.Series]] = defaultdict(list)
    for _, row in frame.iterrows():
        x_zone, y_zone = zone_label(row)
        grouped[(row.team, x_zone, y_zone)].append(row)
    rows = []
    for (team, x_zone, y_zone), shots in grouped.items():
        shots_count = len(shots)
        goals = sum(int(row.is_goal) for row in shots)
        predicted = sum(float(row.predicted_xg) for row in shots)
        rows.append(
            {
                "team": team,
                "x_zone": x_zone,
                "y_zone": y_zone,
                "shots": shots_count,
                "actual_goals": goals,
                "predicted_goals": round(predicted, 3),
                "avg_xg": round(predicted / shots_count, 3),
                "goal_rate": round(goals / shots_count, 3),
                "xg_minus_goals": round(predicted - goals, 3),
            }
        )
    return sorted(rows, key=lambda row: (row["team"], -row["avg_xg"], -row["shots"]))


def train_xg(shots_path: Path, model_path: Path, zones_path: Path, seed: int) -> dict[str, Any]:
    frame = load_shots(shots_path)
    x_train, x_test, y_train, y_test = train_test_split(
        frame[FEATURE_COLUMNS],
        frame["is_goal"].astype(int),
        test_size=0.25,
        random_state=seed,
        stratify=frame["is_goal"].astype(int),
    )
    pipeline = build_pipeline(seed)
    pipeline.fit(x_train, y_train)
    probabilities = pipeline.predict_proba(x_test)[:, 1]
    metrics = {
        "rows": int(len(frame)),
        "test_rows": int(len(x_test)),
        "brier_score": round(brier_score_loss(y_test, probabilities), 4),
        "log_loss": round(log_loss(y_test, probabilities, labels=[0, 1]), 4),
        "roc_auc": round(roc_auc_score(y_test, probabilities), 4) if len(set(y_test)) > 1 else None,
    }
    frame = frame.copy()
    raw_probabilities = pipeline.predict_proba(frame[FEATURE_COLUMNS])[:, 1]
    normalized_rows = frame.to_dict("records")
    frame["predicted_xg"] = [
        blended_xg(float(probability), row)
        for probability, row in zip(raw_probabilities, normalized_rows)
    ]
    zone_rows = build_zone_table(frame)
    write_rows(zones_path, zone_rows, list(zone_rows[0]) if zone_rows else [])
    bundle = {
        "pipeline": pipeline,
        "feature_columns": FEATURE_COLUMNS,
        "numeric_features": NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "metrics": metrics,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_source": sorted(set(frame["source"])),
        "note": "Shot-level xG gradient model. Replace starter_sample rows with provider event data for production accuracy.",
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, model_path)
    return bundle


def load_xg_model(path: Path = XG_MODEL_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return joblib.load(path)


def predict_shot_xg(bundle: dict[str, Any], shot: dict[str, Any]) -> float:
    row = normalize_row(shot)
    frame = pd.DataFrame([{column: row[column] for column in FEATURE_COLUMNS}])
    raw_model_xg = float(bundle["pipeline"].predict_proba(frame)[0][1])
    return blended_xg(raw_model_xg, row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a shot-level xG gradient model.")
    parser.add_argument("--shots", type=Path, default=SHOT_EVENTS_PATH)
    parser.add_argument("--model", type=Path, default=XG_MODEL_PATH)
    parser.add_argument("--zones", type=Path, default=XG_TEAM_ZONES_PATH)
    parser.add_argument("--seed", type=int, default=26)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bundle = train_xg(args.shots, args.model, args.zones, args.seed)
    print(f"xG rows: {bundle['metrics']['rows']}")
    print(f"xG Brier: {bundle['metrics']['brier_score']}")
    print(f"xG ROC AUC: {bundle['metrics']['roc_auc']}")
    print(f"Saved {args.model}")
    print(f"Saved {args.zones}")


if __name__ == "__main__":
    main()
