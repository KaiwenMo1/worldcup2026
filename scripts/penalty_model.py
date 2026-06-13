#!/usr/bin/env python3
"""Train and serve penalty shootout placement and outcome models."""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, log_loss
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from predict_worldcup import ROOT


PENALTY_KICKS_PATH = ROOT / "data" / "penalty_kicks.csv"
PENALTY_MODEL_PATH = ROOT / "models" / "penalty_shootout_model.joblib"

PLACEMENTS = ["Left", "Center", "Right"]
OUTCOMES = ["Goal", "Saved", "Missed"]
NUMERIC_FEATURES = [
    "kick_order",
    "pressure_score",
    "previous_kicker_left_pct",
    "previous_kicker_center_pct",
    "previous_kicker_right_pct",
    "keeper_dive_left_pct",
    "keeper_dive_center_pct",
    "keeper_dive_right_pct",
]
CATEGORICAL_FEATURES = ["kicker_foot", "kicker_position", "score_state", "knockout_round"]
FEATURE_COLUMNS = [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES]
KICK_COLUMNS = [
    "kick_id",
    "tournament",
    "season",
    "match",
    "kick_order",
    "team",
    "kicker",
    "kicker_position",
    "kicker_foot",
    "goalkeeper",
    "goalkeeper_team",
    "keeper_foot",
    "shot_placement",
    "keeper_dive",
    "outcome",
    "pressure_score",
    "score_state",
    "knockout_round",
    "source",
]


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", normalized.lower())


def bootstrap_kicks() -> list[dict[str, Any]]:
    kickers = [
        ("France", "Kylian Mbappe", "FW", "Right"),
        ("Argentina", "Lionel Messi", "FW", "Left"),
        ("England", "Harry Kane", "FW", "Right"),
        ("Portugal", "Cristiano Ronaldo", "FW", "Right"),
        ("Brazil", "Neymar", "FW", "Right"),
        ("Spain", "Pedri", "MF", "Right"),
        ("Germany", "Ilkay Gundogan", "MF", "Right"),
        ("Netherlands", "Memphis Depay", "FW", "Right"),
    ]
    keepers = [
        ("Argentina", "Emiliano Martinez", "Right"),
        ("France", "Mike Maignan", "Right"),
        ("England", "Jordan Pickford", "Left"),
        ("Brazil", "Alisson", "Right"),
    ]
    placement_cycle = ["Left", "Right", "Left", "Center", "Right", "Left", "Right", "Center"]
    dive_cycle = ["Right", "Left", "Left", "Center", "Right", "Right", "Left", "Center"]
    rows = []
    kick_id = 1
    for round_index, round_name in enumerate(["Round of 16", "Quarterfinal", "Semifinal", "Final"]):
        for index, (team, kicker, position, foot) in enumerate(kickers):
            keeper_team, keeper, keeper_foot = keepers[(index + round_index) % len(keepers)]
            if keeper_team == team:
                keeper_team, keeper, keeper_foot = keepers[(index + round_index + 1) % len(keepers)]
            placement = placement_cycle[(index + round_index) % len(placement_cycle)]
            dive = dive_cycle[(index * 2 + round_index) % len(dive_cycle)]
            outcome = "Goal"
            if placement == dive and (index + round_index) % 3 == 0:
                outcome = "Saved"
            if placement == "Center" and (index + round_index) % 5 == 0:
                outcome = "Missed"
            rows.append(
                {
                    "kick_id": f"bootstrap-{kick_id}",
                    "tournament": ["World Cup", "Euro", "Copa America", "AFCON"][round_index],
                    "season": str(2014 + (round_index * 4)),
                    "match": f"{team} vs {keeper_team}",
                    "kick_order": 1 + (index % 5),
                    "team": team,
                    "kicker": kicker,
                    "kicker_position": position,
                    "kicker_foot": foot,
                    "goalkeeper": keeper,
                    "goalkeeper_team": keeper_team,
                    "keeper_foot": keeper_foot,
                    "shot_placement": placement,
                    "keeper_dive": dive,
                    "outcome": outcome,
                    "pressure_score": 55 + ((index * 7 + round_index * 9) % 45),
                    "score_state": ["Leading", "Drawing", "Trailing"][(index + round_index) % 3],
                    "knockout_round": round_name,
                    "source": "starter_sample",
                }
            )
            kick_id += 1
    return rows


def write_rows(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "kick_id": row.get("kick_id") or row.get("id") or "",
        "tournament": row.get("tournament") or row.get("competition") or "",
        "season": row.get("season") or "",
        "match": row.get("match") or "",
        "kick_order": int(float(row.get("kick_order") or row.get("order") or 1)),
        "team": row.get("team") or "",
        "kicker": row.get("kicker") or row.get("player") or "",
        "kicker_position": row.get("kicker_position") or row.get("position") or "FW",
        "kicker_foot": row.get("kicker_foot") or row.get("foot") or "Right",
        "goalkeeper": row.get("goalkeeper") or row.get("keeper") or row.get("goalie") or "",
        "goalkeeper_team": row.get("goalkeeper_team") or "",
        "keeper_foot": row.get("keeper_foot") or "Right",
        "shot_placement": row.get("shot_placement") or row.get("kick_direction") or "Right",
        "keeper_dive": row.get("keeper_dive") or row.get("goalie_action") or "Left",
        "outcome": row.get("outcome") or "Goal",
        "pressure_score": float(row.get("pressure_score") or 70),
        "score_state": row.get("score_state") or row.get("scoreline_state") or "Drawing",
        "knockout_round": row.get("knockout_round") or "Knockout",
        "source": row.get("source") or "imported",
    }


def load_kicks(path: Path) -> pd.DataFrame:
    if not path.exists():
        write_rows(path, bootstrap_kicks(), KICK_COLUMNS)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [normalize_row(row) for row in csv.DictReader(handle)]
    sources = {row["source"] for row in rows}
    if len(rows) < 24 or sources == {"starter_sample"}:
        rows = bootstrap_kicks()
        write_rows(path, rows, KICK_COLUMNS)
    frame = pd.DataFrame(rows)
    return add_tendency_features(frame)


def add_tendency_features(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    player_history: dict[str, Counter[str]] = defaultdict(Counter)
    keeper_history: dict[str, Counter[str]] = defaultdict(Counter)
    enriched = []
    for _, row in frame.iterrows():
        player_counts = player_history[row.kicker]
        keeper_counts = keeper_history[row.goalkeeper]
        player_total = sum(player_counts.values()) + 3
        keeper_total = sum(keeper_counts.values()) + 3
        enriched.append(
            {
                "previous_kicker_left_pct": (player_counts["Left"] + 1) / player_total,
                "previous_kicker_center_pct": (player_counts["Center"] + 1) / player_total,
                "previous_kicker_right_pct": (player_counts["Right"] + 1) / player_total,
                "keeper_dive_left_pct": (keeper_counts["Left"] + 1) / keeper_total,
                "keeper_dive_center_pct": (keeper_counts["Center"] + 1) / keeper_total,
                "keeper_dive_right_pct": (keeper_counts["Right"] + 1) / keeper_total,
            }
        )
        player_history[row.kicker][row.shot_placement] += 1
        keeper_history[row.goalkeeper][row.keeper_dive] += 1
    for column in enriched[0]:
        frame[column] = [row[column] for row in enriched]
    return frame


def build_pipeline(seed: int) -> Pipeline:
    preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", "passthrough", NUMERIC_FEATURES),
            ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
        ]
    )
    model = HistGradientBoostingClassifier(
        learning_rate=0.08,
        max_leaf_nodes=16,
        l2_regularization=0.08,
        random_state=seed,
    )
    return Pipeline([("features", preprocessor), ("model", model)])


def tendency_percentages(frame: pd.DataFrame, name: str, column: str, value_column: str, values: list[str]) -> dict[str, float]:
    target = normalize_name(name)
    subset = frame[frame[column].map(lambda value: normalize_name(str(value))) == target]
    counts = Counter(subset[value_column]) if not subset.empty else Counter(frame[value_column])
    total = sum(counts.values()) + len(values)
    return {value: (counts[value] + 1) / total for value in values}


def train_penalties(kicks_path: Path, model_path: Path, seed: int) -> dict[str, Any]:
    frame = load_kicks(kicks_path)
    train, test = train_test_split(frame, test_size=0.25, random_state=seed, stratify=frame["shot_placement"])
    placement_model = build_pipeline(seed)
    outcome_model = build_pipeline(seed + 1)
    placement_model.fit(train[FEATURE_COLUMNS], train["shot_placement"])
    outcome_model.fit(train[FEATURE_COLUMNS], train["outcome"])
    placement_prob = placement_model.predict_proba(test[FEATURE_COLUMNS])
    outcome_prob = outcome_model.predict_proba(test[FEATURE_COLUMNS])
    metrics = {
        "rows": int(len(frame)),
        "test_rows": int(len(test)),
        "placement_accuracy": round(accuracy_score(test["shot_placement"], placement_model.predict(test[FEATURE_COLUMNS])), 4),
        "placement_log_loss": round(log_loss(test["shot_placement"], placement_prob, labels=list(placement_model.classes_)), 4),
        "outcome_accuracy": round(accuracy_score(test["outcome"], outcome_model.predict(test[FEATURE_COLUMNS])), 4),
        "outcome_log_loss": round(log_loss(test["outcome"], outcome_prob, labels=list(outcome_model.classes_)), 4),
    }
    bundle = {
        "placement_model": placement_model,
        "outcome_model": outcome_model,
        "feature_columns": FEATURE_COLUMNS,
        "metrics": metrics,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_source": sorted(set(frame["source"])),
        "history": frame.to_dict("records"),
        "note": "Penalty placement/outcome gradient models. Replace starter_sample rows with kick-level shootout data for production accuracy.",
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, model_path)
    return bundle


def load_penalty_model(path: Path = PENALTY_MODEL_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return joblib.load(path)


def probability_map(model: Pipeline, frame: pd.DataFrame, values: list[str]) -> dict[str, float]:
    raw = dict(zip(model.classes_, model.predict_proba(frame)[0]))
    return {value: float(raw.get(value, 0.0)) for value in values}


def matchup_features(
    bundle: dict[str, Any],
    kicker: str,
    goalkeeper: str,
    kicker_foot: str = "Right",
    kicker_position: str = "FW",
    pressure_score: float = 75.0,
    score_state: str = "Drawing",
    knockout_round: str = "Final",
    kick_order: int = 1,
) -> dict[str, Any]:
    history = pd.DataFrame(bundle["history"])
    player = tendency_percentages(history, kicker, "kicker", "shot_placement", PLACEMENTS)
    keeper = tendency_percentages(history, goalkeeper, "goalkeeper", "keeper_dive", PLACEMENTS)
    return {
        "kick_order": kick_order,
        "pressure_score": pressure_score,
        "previous_kicker_left_pct": player["Left"],
        "previous_kicker_center_pct": player["Center"],
        "previous_kicker_right_pct": player["Right"],
        "keeper_dive_left_pct": keeper["Left"],
        "keeper_dive_center_pct": keeper["Center"],
        "keeper_dive_right_pct": keeper["Right"],
        "kicker_foot": kicker_foot,
        "kicker_position": kicker_position,
        "score_state": score_state,
        "knockout_round": knockout_round,
    }


def predict_penalty_matchup(bundle: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    features = matchup_features(bundle, **request)
    frame = pd.DataFrame([{column: features[column] for column in FEATURE_COLUMNS}])
    placement = probability_map(bundle["placement_model"], frame, PLACEMENTS)
    outcome = probability_map(bundle["outcome_model"], frame, OUTCOMES)
    best_dive = max(placement.items(), key=lambda item: item[1])[0]
    return {
        "placement_probabilities": {key: round(value * 100, 1) for key, value in placement.items()},
        "outcome_probabilities": {key: round(value * 100, 1) for key, value in outcome.items()},
        "save_probability": round(outcome.get("Saved", 0.0) * 100, 1),
        "goal_probability": round(outcome.get("Goal", 0.0) * 100, 1),
        "miss_probability": round(outcome.get("Missed", 0.0) * 100, 1),
        "keeper_recommended_dive": best_dive,
        "features": {key: round(value, 3) if isinstance(value, float) else value for key, value in features.items()},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train penalty shootout placement and outcome models.")
    parser.add_argument("--kicks", type=Path, default=PENALTY_KICKS_PATH)
    parser.add_argument("--model", type=Path, default=PENALTY_MODEL_PATH)
    parser.add_argument("--seed", type=int, default=26)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bundle = train_penalties(args.kicks, args.model, args.seed)
    print(f"Penalty rows: {bundle['metrics']['rows']}")
    print(f"Placement accuracy: {bundle['metrics']['placement_accuracy']}")
    print(f"Outcome accuracy: {bundle['metrics']['outcome_accuracy']}")
    print(f"Saved {args.model}")


if __name__ == "__main__":
    main()
