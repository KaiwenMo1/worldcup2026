#!/usr/bin/env python3
"""Train a Random Forest match-result model for the World Cup simulator."""

from __future__ import annotations

import argparse
import math
from collections import defaultdict, deque
from pathlib import Path

try:
    import joblib
    import pandas as pd
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.metrics import accuracy_score, log_loss, mean_absolute_error
    from sklearn.model_selection import train_test_split
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing ML dependencies. Run:\n"
        "  python3 -m venv .venv\n"
        "  source .venv/bin/activate\n"
        "  pip install -r requirements.txt"
    ) from exc

try:
    import mlflow
    import mlflow.sklearn
except ModuleNotFoundError:
    mlflow = None

from predict_worldcup import ROOT, Team, load_teams


MATCHES_PATH = ROOT / "data" / "historical_matches.csv"
MODEL_PATH = ROOT / "models" / "worldcup_random_forest.joblib"

CONFEDERATION_STRENGTH = {
    "CONMEBOL": 0.10,
    "UEFA": 0.08,
    "CAF": 0.00,
    "CONCACAF": -0.02,
    "AFC": -0.05,
    "OFC": -0.12,
}

TOURNAMENT_WEIGHT = {
    "FIFA World Cup": 1.45,
    "FIFA World Cup qualification": 1.15,
    "UEFA Euro": 1.25,
    "UEFA Euro qualification": 1.08,
    "UEFA Nations League": 1.05,
    "Copa America": 1.22,
    "Africa Cup of Nations": 1.18,
    "AFC Asian Cup": 1.18,
    "CONCACAF Gold Cup": 1.12,
    "Friendly": 0.82,
}

RECENCY_HALF_LIFE_YEARS = 3.5
PROBABILITY_SHRINKAGE = 0.08

FEATURE_COLUMNS = [
    "rank_diff",
    "squad_diff",
    "attack_defense_edge",
    "midfield_diff",
    "keeper_diff",
    "bench_diff",
    "form_feature_diff",
    "fitness_diff",
    "chemistry_diff",
    "manager_diff",
    "set_piece_edge",
    "penalty_diff",
    "discipline_diff",
    "tactical_diff",
    "injury_resilience_diff",
    "pressing_diff",
    "transition_diff",
    "big_match_diff",
    "elo_diff",
    "recent_points_diff",
    "recent_goal_diff",
    "recent_goals_for_diff",
    "recent_goals_against_diff",
    "recent_clean_sheet_diff",
    "host_edge",
    "neutral",
    "same_confederation",
    "confederation_strength_diff",
    "tournament_weight",
]


def fallback_team(name: str) -> Team:
    return Team(name=name, confederation="UNKNOWN", rank=90, host=False, world_cup_pedigree=1)


def load_matches(path: Path) -> pd.DataFrame:
    matches = pd.read_csv(path, parse_dates=["date"])
    required = {"date", "team_a", "team_b", "team_a_score", "team_b_score", "neutral", "tournament"}
    missing = required - set(matches.columns)
    if missing:
        raise SystemExit(f"{path} is missing columns: {', '.join(sorted(missing))}")

    before = len(matches)
    matches = matches.dropna(subset=["date", "team_a", "team_b", "team_a_score", "team_b_score"])
    matches["team_a_score"] = pd.to_numeric(matches["team_a_score"], errors="coerce")
    matches["team_b_score"] = pd.to_numeric(matches["team_b_score"], errors="coerce")
    matches = matches.dropna(subset=["team_a_score", "team_b_score"])
    matches["team_a_score"] = matches["team_a_score"].astype(int)
    matches["team_b_score"] = matches["team_b_score"].astype(int)
    dropped = before - len(matches)
    if dropped:
        print(f"Skipped {dropped} rows without usable final scores.")
    return matches.sort_values("date").reset_index(drop=True)


def points_for(goals_for: int, goals_against: int) -> int:
    if goals_for > goals_against:
        return 3
    if goals_for == goals_against:
        return 1
    return 0


def recent_snapshot(history: deque[dict[str, float]]) -> dict[str, float]:
    if not history:
        return {
            "points": 1.15,
            "goal_diff": 0.0,
            "goals_for": 1.25,
            "goals_against": 1.25,
            "clean_sheet": 0.25,
        }

    size = len(history)
    return {
        "points": sum(item["points"] for item in history) / size,
        "goal_diff": sum(item["goal_diff"] for item in history) / size,
        "goals_for": sum(item["goals_for"] for item in history) / size,
        "goals_against": sum(item["goals_against"] for item in history) / size,
        "clean_sheet": sum(item["clean_sheet"] for item in history) / size,
    }


def expected_result(score_diff: float) -> float:
    return 1 / (1 + math.pow(10, -score_diff / 400))


def update_elo(elo: defaultdict[str, float], team_a: str, team_b: str, score_a: int, score_b: int, k: float) -> None:
    actual_a = 1.0 if score_a > score_b else 0.5 if score_a == score_b else 0.0
    expected_a = expected_result(elo[team_a] - elo[team_b])
    movement = k * (actual_a - expected_a)
    elo[team_a] += movement
    elo[team_b] -= movement


def team_context(team: Team) -> dict[str, float]:
    return {
        "rank": float(team.rank),
        "squad": team.squad_rating,
        "attack": team.attack,
        "midfield": team.midfield,
        "defense": team.defense,
        "goalkeeper": team.goalkeeper,
        "bench": team.bench,
        "recent_form": team.recent_form,
        "fitness": team.fitness,
        "chemistry": team.chemistry,
        "manager": team.manager,
        "set_piece_attack": team.set_piece_attack,
        "set_piece_defense": team.set_piece_defense,
        "penalty_strength": team.penalty_strength,
        "discipline": team.discipline,
        "tactical_flexibility": team.tactical_flexibility,
        "injury_resilience": team.injury_resilience,
        "pressing_intensity": team.pressing_intensity,
        "transition_speed": team.transition_speed,
        "big_match_composure": team.big_match_composure,
        "confed": CONFEDERATION_STRENGTH.get(team.confederation, 0.0),
    }


def build_training_frame(matches: pd.DataFrame, teams: dict[str, Team]) -> pd.DataFrame:
    elo: defaultdict[str, float] = defaultdict(lambda: 1500.0)
    history: defaultdict[str, deque[dict[str, float]]] = defaultdict(lambda: deque(maxlen=10))
    rows: list[dict[str, float | int | str]] = []
    latest_date = matches["date"].max()

    for record in matches.itertuples(index=False):
        team_a = teams.get(record.team_a, fallback_team(record.team_a))
        team_b = teams.get(record.team_b, fallback_team(record.team_b))
        a = team_context(team_a)
        b = team_context(team_b)
        a_recent = recent_snapshot(history[record.team_a])
        b_recent = recent_snapshot(history[record.team_b])
        neutral = int(str(record.neutral).lower() in {"1", "true", "yes"})
        tournament_weight = TOURNAMENT_WEIGHT.get(record.tournament, 1.0)
        match_age_years = max(0.0, (latest_date - record.date).days / 365.25)
        recency_weight = math.pow(0.5, match_age_years / RECENCY_HALF_LIFE_YEARS)
        sample_weight = tournament_weight * (0.35 + (0.65 * recency_weight))

        outcome = "draw"
        if record.team_a_score > record.team_b_score:
            outcome = "team_a_win"
        elif record.team_b_score > record.team_a_score:
            outcome = "team_b_win"

        rows.append(
            {
                "rank_diff": b["rank"] - a["rank"],
                "squad_diff": a["squad"] - b["squad"],
                "attack_defense_edge": (a["attack"] - b["defense"]) - (b["attack"] - a["defense"]),
                "midfield_diff": a["midfield"] - b["midfield"],
                "keeper_diff": a["goalkeeper"] - b["goalkeeper"],
                "bench_diff": a["bench"] - b["bench"],
                "form_feature_diff": a["recent_form"] - b["recent_form"],
                "fitness_diff": a["fitness"] - b["fitness"],
                "chemistry_diff": a["chemistry"] - b["chemistry"],
                "manager_diff": a["manager"] - b["manager"],
                "set_piece_edge": (a["set_piece_attack"] - b["set_piece_defense"])
                - (b["set_piece_attack"] - a["set_piece_defense"]),
                "penalty_diff": a["penalty_strength"] - b["penalty_strength"],
                "discipline_diff": a["discipline"] - b["discipline"],
                "tactical_diff": a["tactical_flexibility"] - b["tactical_flexibility"],
                "injury_resilience_diff": a["injury_resilience"] - b["injury_resilience"],
                "pressing_diff": a["pressing_intensity"] - b["pressing_intensity"],
                "transition_diff": a["transition_speed"] - b["transition_speed"],
                "big_match_diff": a["big_match_composure"] - b["big_match_composure"],
                "elo_diff": elo[record.team_a] - elo[record.team_b],
                "recent_points_diff": a_recent["points"] - b_recent["points"],
                "recent_goal_diff": a_recent["goal_diff"] - b_recent["goal_diff"],
                "recent_goals_for_diff": a_recent["goals_for"] - b_recent["goals_for"],
                "recent_goals_against_diff": a_recent["goals_against"] - b_recent["goals_against"],
                "recent_clean_sheet_diff": a_recent["clean_sheet"] - b_recent["clean_sheet"],
                "host_edge": 0 if neutral else (1 if team_a.host else -1 if team_b.host else 0),
                "neutral": neutral,
                "same_confederation": int(team_a.confederation == team_b.confederation),
                "confederation_strength_diff": a["confed"] - b["confed"],
                "tournament_weight": tournament_weight,
                "outcome": outcome,
                "team_a_goals": int(record.team_a_score),
                "team_b_goals": int(record.team_b_score),
                "match_age_years": match_age_years,
                "recency_weight": recency_weight,
                "sample_weight": sample_weight,
            }
        )

        history[record.team_a].append(
            {
                "points": points_for(record.team_a_score, record.team_b_score),
                "goal_diff": record.team_a_score - record.team_b_score,
                "goals_for": record.team_a_score,
                "goals_against": record.team_b_score,
                "clean_sheet": int(record.team_b_score == 0),
            }
        )
        history[record.team_b].append(
            {
                "points": points_for(record.team_b_score, record.team_a_score),
                "goal_diff": record.team_b_score - record.team_a_score,
                "goals_for": record.team_b_score,
                "goals_against": record.team_a_score,
                "clean_sheet": int(record.team_a_score == 0),
            }
        )
        update_elo(elo, record.team_a, record.team_b, record.team_a_score, record.team_b_score, 28 * tournament_weight)

    return pd.DataFrame(rows)


def train(matches_path: Path, model_path: Path, seed: int, track_mlflow: bool = False) -> None:
    teams = load_teams()
    matches = load_matches(matches_path)
    frame = build_training_frame(matches, teams)
    if len(frame) < 60:
        raise SystemExit("Need at least 60 matches for a useful starter Random Forest model.")

    x = frame[FEATURE_COLUMNS]
    y = frame["outcome"]
    weights = frame["sample_weight"]
    stratify = y if y.value_counts().min() >= 2 else None
    x_train, x_test, y_train, y_test, w_train, w_test = train_test_split(
        x,
        y,
        weights,
        test_size=0.22,
        random_state=seed,
        stratify=stratify,
    )

    classifier = RandomForestClassifier(
        n_estimators=120,
        min_samples_leaf=3,
        max_features="sqrt",
        class_weight="balanced",
        n_jobs=1,
        random_state=seed,
    )
    classifier_type = "recency_weighted_random_forest"
    classifier.fit(x_train.to_numpy(), y_train, sample_weight=w_train.to_numpy())

    goal_a_model = RandomForestRegressor(
        n_estimators=120,
        min_samples_leaf=3,
        max_features="sqrt",
        n_jobs=1,
        random_state=seed + 1,
    )
    goal_b_model = RandomForestRegressor(
        n_estimators=120,
        min_samples_leaf=3,
        max_features="sqrt",
        n_jobs=1,
        random_state=seed + 2,
    )
    goal_a_model.fit(x_train.to_numpy(), frame.loc[x_train.index, "team_a_goals"], sample_weight=w_train.to_numpy())
    goal_b_model.fit(x_train.to_numpy(), frame.loc[x_train.index, "team_b_goals"], sample_weight=w_train.to_numpy())

    x_test_values = x_test.to_numpy()
    probabilities = classifier.predict_proba(x_test_values)
    predicted = classifier.predict(x_test_values)
    feature_importance = {
        column: float(importance)
        for column, importance in zip(FEATURE_COLUMNS, classifier.feature_importances_)
    }
    feature_stats = {
        column: {
            "mean": float(frame[column].mean()),
            "std": float(frame[column].std(ddof=0) or 1.0),
        }
        for column in FEATURE_COLUMNS
    }
    metrics = {
        "holdout_accuracy": float(accuracy_score(y_test, predicted)),
        "holdout_log_loss": float(log_loss(y_test, probabilities, labels=classifier.classes_)),
        "goal_mae_team_a": float(mean_absolute_error(frame.loc[x_test.index, "team_a_goals"], goal_a_model.predict(x_test_values))),
        "goal_mae_team_b": float(mean_absolute_error(frame.loc[x_test.index, "team_b_goals"], goal_b_model.predict(x_test_values))),
    }
    weighted_priors = {
        label: float(weights[y == label].sum() / weights.sum())
        for label in classifier.classes_
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        model_payload := {
            "classifier": classifier,
            "classifier_type": classifier_type,
            "probability_prior": weighted_priors,
            "probability_shrinkage": PROBABILITY_SHRINKAGE,
            "goal_a_model": goal_a_model,
            "goal_b_model": goal_b_model,
            "feature_columns": FEATURE_COLUMNS,
            "feature_importance": feature_importance,
            "feature_stats": feature_stats,
            "classes": list(classifier.classes_),
            "training_rows": len(frame),
            "trained_through": matches["date"].max().date().isoformat(),
            "recency_half_life_years": RECENCY_HALF_LIFE_YEARS,
            "average_sample_weight": float(weights.mean()),
            "metrics": metrics,
            "team_state": asdict_state(matches, teams),
        },
        model_path,
    )

    if track_mlflow:
        log_mlflow_run(model_payload, metrics, seed, matches_path, model_path)

    print(f"Training rows: {len(frame)}")
    print(f"Classifier: {classifier_type}")
    print(f"Recency half-life: {RECENCY_HALF_LIFE_YEARS:.1f} years")
    print(f"Probability shrinkage: {PROBABILITY_SHRINKAGE:.2f}")
    print(f"Holdout accuracy: {metrics['holdout_accuracy']:.3f}")
    print(f"Holdout log loss: {metrics['holdout_log_loss']:.3f}")
    print(f"Goal MAE team A: {metrics['goal_mae_team_a']:.3f}")
    print(f"Goal MAE team B: {metrics['goal_mae_team_b']:.3f}")
    print(f"Saved model to {model_path}")


def log_mlflow_run(model_payload: dict[str, object], metrics: dict[str, float], seed: int, matches_path: Path, model_path: Path) -> None:
    if mlflow is None:
        print("MLflow requested but not installed. Run: pip install mlflow")
        return
    mlflow.set_experiment("worldcup-predictor")
    with mlflow.start_run(run_name=f"worldcup-rf-seed-{seed}"):
        mlflow.log_param("seed", seed)
        mlflow.log_param("classifier_type", model_payload.get("classifier_type"))
        mlflow.log_param("training_rows", model_payload.get("training_rows"))
        mlflow.log_param("trained_through", model_payload.get("trained_through"))
        mlflow.log_param("recency_half_life_years", model_payload.get("recency_half_life_years"))
        mlflow.log_param("probability_shrinkage", model_payload.get("probability_shrinkage"))
        for name, value in metrics.items():
            mlflow.log_metric(name, value)
        mlflow.log_artifact(str(matches_path), artifact_path="data")
        mlflow.log_artifact(str(model_path), artifact_path="models")
        mlflow.sklearn.log_model(model_payload["classifier"], name="classifier")


def asdict_state(matches: pd.DataFrame, teams: dict[str, Team]) -> dict[str, dict[str, float]]:
    elo: defaultdict[str, float] = defaultdict(lambda: 1500.0)
    history: defaultdict[str, deque[dict[str, float]]] = defaultdict(lambda: deque(maxlen=10))

    for record in matches.itertuples(index=False):
        tournament_weight = TOURNAMENT_WEIGHT.get(record.tournament, 1.0)
        history[record.team_a].append(
            {
                "points": points_for(record.team_a_score, record.team_b_score),
                "goal_diff": record.team_a_score - record.team_b_score,
                "goals_for": record.team_a_score,
                "goals_against": record.team_b_score,
                "clean_sheet": int(record.team_b_score == 0),
            }
        )
        history[record.team_b].append(
            {
                "points": points_for(record.team_b_score, record.team_a_score),
                "goal_diff": record.team_b_score - record.team_a_score,
                "goals_for": record.team_b_score,
                "goals_against": record.team_a_score,
                "clean_sheet": int(record.team_a_score == 0),
            }
        )
        update_elo(elo, record.team_a, record.team_b, record.team_a_score, record.team_b_score, 28 * tournament_weight)

    state = {}
    for name in teams:
        recent = recent_snapshot(history[name])
        state[name] = {
            "elo": elo[name],
            "recent_points": recent["points"],
            "recent_goal_diff": recent["goal_diff"],
            "recent_goals_for": recent["goals_for"],
            "recent_goals_against": recent["goals_against"],
            "recent_clean_sheet": recent["clean_sheet"],
        }
    return state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the World Cup Random Forest model.")
    parser.add_argument("--matches", type=Path, default=MATCHES_PATH, help="Historical matches CSV path.")
    parser.add_argument("--model", type=Path, default=MODEL_PATH, help="Output model path.")
    parser.add_argument("--seed", type=int, default=26, help="Random seed.")
    parser.add_argument("--mlflow", action="store_true", help="Log model params, metrics, and artifacts to MLflow.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    train(args.matches, args.model, args.seed, args.mlflow)


if __name__ == "__main__":
    main()
