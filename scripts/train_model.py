#!/usr/bin/env python3
"""Train the leakage-safe World Cup result and exact-score ensemble."""

from __future__ import annotations

import argparse
import math
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

try:
    import joblib
    import numpy as np
    import pandas as pd
    import penaltyblog as pb
    from penaltyblog.models.loss import dixon_coles_loss_function
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, log_loss, mean_absolute_error
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
PROBABILITY_SHRINKAGE = 0.0
OUTCOME_CLASSES = ["team_a_win", "draw", "team_b_win"]
ELO_FEATURE_COLUMNS = ["elo_diff", "neutral", "tournament_weight"]
FEATURE_COLUMNS = [
    "elo_diff",
    "recent_points_diff",
    "recent_goal_diff",
    "recent_goals_for_diff",
    "recent_goals_against_diff",
    "recent_clean_sheet_diff",
    "recent_win_rate_diff",
    "recent_draw_rate_diff",
    "recent_points_volatility_diff",
    "recent_goal_diff_volatility_diff",
    "rest_days_diff",
    "experience_diff",
    "neutral",
    "tournament_weight",
]
EXCLUDED_CURRENT_FEATURES = [
    "FIFA rank",
    "current squad rating",
    "current attack/midfield/defense ratings",
    "current fitness and chemistry",
    "current manager and tactical ratings",
]


def load_matches(path: Path) -> pd.DataFrame:
    matches = pd.read_csv(path, parse_dates=["date"])
    required = {"date", "team_a", "team_b", "team_a_score", "team_b_score", "neutral", "tournament"}
    missing = required - set(matches.columns)
    if missing:
        raise SystemExit(f"{path} is missing columns: {', '.join(sorted(missing))}")

    before = len(matches)
    matches["team_a_score"] = pd.to_numeric(matches["team_a_score"], errors="coerce")
    matches["team_b_score"] = pd.to_numeric(matches["team_b_score"], errors="coerce")
    matches = matches.dropna(subset=["date", "team_a", "team_b", "team_a_score", "team_b_score"])
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
            "win_rate": 0.33,
            "draw_rate": 0.27,
            "points_volatility": 1.0,
            "goal_diff_volatility": 1.0,
        }

    points = np.asarray([item["points"] for item in history], dtype=float)
    goal_diffs = np.asarray([item["goal_diff"] for item in history], dtype=float)
    size = len(history)
    return {
        "points": float(points.mean()),
        "goal_diff": float(goal_diffs.mean()),
        "goals_for": sum(item["goals_for"] for item in history) / size,
        "goals_against": sum(item["goals_against"] for item in history) / size,
        "clean_sheet": sum(item["clean_sheet"] for item in history) / size,
        "win_rate": sum(item["win"] for item in history) / size,
        "draw_rate": sum(item["draw"] for item in history) / size,
        "points_volatility": float(points.std()),
        "goal_diff_volatility": float(goal_diffs.std()),
    }


def expected_result(score_diff: float) -> float:
    return 1 / (1 + math.pow(10, -score_diff / 400))


def update_elo(elo: defaultdict[str, float], team_a: str, team_b: str, score_a: int, score_b: int, k: float) -> None:
    actual_a = 1.0 if score_a > score_b else 0.5 if score_a == score_b else 0.0
    expected_a = expected_result(elo[team_a] - elo[team_b])
    movement = k * (actual_a - expected_a)
    elo[team_a] += movement
    elo[team_b] -= movement


def neutral_value(value: Any) -> int:
    return int(str(value).lower() in {"1", "true", "yes"})


def capped_rest_days(match_date: pd.Timestamp, previous_date: pd.Timestamp | None) -> float:
    if previous_date is None:
        return 30.0
    return float(max(2, min(120, (match_date - previous_date).days)))


def history_item(goals_for: int, goals_against: int) -> dict[str, float]:
    return {
        "points": points_for(goals_for, goals_against),
        "goal_diff": goals_for - goals_against,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "clean_sheet": int(goals_against == 0),
        "win": int(goals_for > goals_against),
        "draw": int(goals_for == goals_against),
    }


def build_training_frame(matches: pd.DataFrame, teams: dict[str, Team] | None = None) -> pd.DataFrame:
    """Build features using only information available before each match."""
    del teams  # Kept as an optional compatibility argument for older scripts.
    elo: defaultdict[str, float] = defaultdict(lambda: 1500.0)
    history: defaultdict[str, deque[dict[str, float]]] = defaultdict(lambda: deque(maxlen=10))
    match_counts: defaultdict[str, int] = defaultdict(int)
    last_match: dict[str, pd.Timestamp] = {}
    rows: list[dict[str, Any]] = []
    latest_date = matches["date"].max()

    for record in matches.itertuples(index=False):
        a_recent = recent_snapshot(history[record.team_a])
        b_recent = recent_snapshot(history[record.team_b])
        neutral = neutral_value(record.neutral)
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
                "date": record.date,
                "team_a": record.team_a,
                "team_b": record.team_b,
                "tournament": record.tournament,
                "elo_diff": elo[record.team_a] - elo[record.team_b],
                "recent_points_diff": a_recent["points"] - b_recent["points"],
                "recent_goal_diff": a_recent["goal_diff"] - b_recent["goal_diff"],
                "recent_goals_for_diff": a_recent["goals_for"] - b_recent["goals_for"],
                "recent_goals_against_diff": a_recent["goals_against"] - b_recent["goals_against"],
                "recent_clean_sheet_diff": a_recent["clean_sheet"] - b_recent["clean_sheet"],
                "recent_win_rate_diff": a_recent["win_rate"] - b_recent["win_rate"],
                "recent_draw_rate_diff": a_recent["draw_rate"] - b_recent["draw_rate"],
                "recent_points_volatility_diff": a_recent["points_volatility"] - b_recent["points_volatility"],
                "recent_goal_diff_volatility_diff": a_recent["goal_diff_volatility"] - b_recent["goal_diff_volatility"],
                "rest_days_diff": capped_rest_days(record.date, last_match.get(record.team_a))
                - capped_rest_days(record.date, last_match.get(record.team_b)),
                "experience_diff": math.log1p(match_counts[record.team_a]) - math.log1p(match_counts[record.team_b]),
                "neutral": neutral,
                "tournament_weight": tournament_weight,
                "outcome": outcome,
                "team_a_goals": int(record.team_a_score),
                "team_b_goals": int(record.team_b_score),
                "recency_weight": recency_weight,
                "sample_weight": sample_weight,
            }
        )

        history[record.team_a].append(history_item(record.team_a_score, record.team_b_score))
        history[record.team_b].append(history_item(record.team_b_score, record.team_a_score))
        match_counts[record.team_a] += 1
        match_counts[record.team_b] += 1
        last_match[record.team_a] = record.date
        last_match[record.team_b] = record.date
        update_elo(elo, record.team_a, record.team_b, record.team_a_score, record.team_b_score, 28 * tournament_weight)

    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def chronological_partitions(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train_end = max(1, int(len(frame) * 0.60)) - 1
    calibration_end = max(train_end + 1, int(len(frame) * 0.80)) - 1
    train_through = frame.iloc[train_end]["date"]
    calibration_through = frame.iloc[calibration_end]["date"]
    return (
        frame[frame["date"] <= train_through].copy(),
        frame[(frame["date"] > train_through) & (frame["date"] <= calibration_through)].copy(),
        frame[frame["date"] > calibration_through].copy(),
    )


def fit_random_forest(frame: pd.DataFrame, seed: int) -> RandomForestClassifier:
    classifier = RandomForestClassifier(
        n_estimators=180,
        min_samples_leaf=4,
        max_features="sqrt",
        class_weight="balanced_subsample",
        n_jobs=1,
        random_state=seed,
    )
    classifier.fit(frame[FEATURE_COLUMNS].to_numpy(), frame["outcome"], sample_weight=frame["sample_weight"].to_numpy())
    return classifier


def fit_goal_models(frame: pd.DataFrame, seed: int) -> tuple[RandomForestRegressor, RandomForestRegressor]:
    models = []
    for offset, target in enumerate(("team_a_goals", "team_b_goals"), start=1):
        model = RandomForestRegressor(
            n_estimators=160,
            min_samples_leaf=4,
            max_features="sqrt",
            n_jobs=1,
            random_state=seed + offset,
        )
        model.fit(frame[FEATURE_COLUMNS].to_numpy(), frame[target], sample_weight=frame["sample_weight"].to_numpy())
        models.append(model)
    return models[0], models[1]


def fit_elo_model(frame: pd.DataFrame, seed: int) -> LogisticRegression:
    model = LogisticRegression(C=0.8, max_iter=1000, random_state=seed)
    model.fit(frame[ELO_FEATURE_COLUMNS].to_numpy(), frame["outcome"], sample_weight=frame["sample_weight"].to_numpy())
    return model


def _writable_c_array(values: Any, dtype: Any) -> np.ndarray:
    """Return owned writable C-contiguous memory for penaltyblog's compiled loss functions."""
    array = np.array(values, dtype=dtype, order="C", copy=True)
    array.setflags(write=True)
    return array


class WritableDixonColesGoalModel(pb.models.DixonColesGoalModel):
    """Dixon-Coles model hardened for pandas/numpy read-only array behavior."""

    def _loss_function(self, params: np.ndarray) -> float:
        params = _writable_c_array(params, np.double)

        attack = _writable_c_array(params[: self.n_teams], np.double)
        defence = _writable_c_array(params[self.n_teams : 2 * self.n_teams], np.double)
        hfa = float(params[-2])
        rho = float(params[-1])

        loss = dixon_coles_loss_function(
            _writable_c_array(self.goals_home, np.int_),
            _writable_c_array(self.goals_away, np.int_),
            _writable_c_array(self.weights, np.double),
            _writable_c_array(self.home_idx, np.int_),
            _writable_c_array(self.away_idx, np.int_),
            _writable_c_array(self.neutral_venue, np.int_),
            attack,
            defence,
            hfa,
            rho,
        )

        if np.isnan(loss) or np.isinf(loss):
            return 1e10

        return float(loss)


def fit_dixon_coles(frame: pd.DataFrame) -> Any:
    model = WritableDixonColesGoalModel(
        _writable_c_array(frame["team_a_goals"], np.int_),
        _writable_c_array(frame["team_b_goals"], np.int_),
        _writable_c_array(frame["team_a"], str),
        _writable_c_array(frame["team_b"], str),
        weights=_writable_c_array(frame["sample_weight"], np.double),
        neutral_venue=_writable_c_array(frame["neutral"], np.int_),
    )

    model._params = _writable_c_array(model._params, np.double)

    # Disable penaltyblog's gradient path; the custom loss function above is the important part.
    model.fit(use_gradient=False)

    return model


def aligned_probabilities(model: Any, values: np.ndarray) -> np.ndarray:
    raw = model.predict_proba(values)
    aligned = np.zeros((len(values), len(OUTCOME_CLASSES)), dtype=float)
    for source_idx, label in enumerate(model.classes_):
        aligned[:, OUTCOME_CLASSES.index(label)] = raw[:, source_idx]
    return aligned


def dixon_coles_probabilities(model: Any, frame: pd.DataFrame, fallback: np.ndarray) -> tuple[np.ndarray, float]:
    rows = []
    covered = 0
    for fallback_row, record in zip(fallback, frame.itertuples(index=False)):
        try:
            grid = model.predict(
                record.team_a,
                record.team_b,
                max_goals=10,
                neutral_venue=bool(record.neutral),
            )
            home, draw, away = grid.home_draw_away
            rows.append([float(home), float(draw), float(away)])
            covered += 1
        except (ValueError, KeyError):
            rows.append(fallback_row.tolist())
    return np.asarray(rows, dtype=float), covered / max(len(frame), 1)


def component_predictions(
    frame: pd.DataFrame,
    classifier: RandomForestClassifier,
    elo_model: LogisticRegression,
    dixon_coles_model: Any,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    rf = aligned_probabilities(classifier, frame[FEATURE_COLUMNS].to_numpy())
    elo = aligned_probabilities(elo_model, frame[ELO_FEATURE_COLUMNS].to_numpy())
    dixon_coles, coverage = dixon_coles_probabilities(dixon_coles_model, frame, elo)
    return rf, dixon_coles, elo, coverage


def fit_ensemble(
    frame: pd.DataFrame,
    classifier: RandomForestClassifier,
    elo_model: LogisticRegression,
    dixon_coles_model: Any,
    seed: int,
) -> tuple[LogisticRegression, float]:
    rf, dixon_coles, elo, coverage = component_predictions(frame, classifier, elo_model, dixon_coles_model)
    stacker = LogisticRegression(C=0.7, max_iter=1000, random_state=seed)
    stacker.fit(np.hstack([rf, dixon_coles, elo]), frame["outcome"], sample_weight=frame["sample_weight"].to_numpy())
    return stacker, coverage


def ensemble_probabilities(stacker: LogisticRegression, rf: np.ndarray, dixon_coles: np.ndarray, elo: np.ndarray) -> np.ndarray:
    return aligned_probabilities(stacker, np.hstack([rf, dixon_coles, elo]))


def multiclass_metrics(labels: pd.Series, probabilities: np.ndarray) -> dict[str, float]:
    truth = np.asarray([OUTCOME_CLASSES.index(label) for label in labels], dtype=int)
    one_hot = np.eye(len(OUTCOME_CLASSES))[truth]
    predicted = np.argmax(probabilities, axis=1)
    return {
        "accuracy": float(accuracy_score(truth, predicted)),
        "log_loss": float(log_loss(truth, probabilities, labels=list(range(len(OUTCOME_CLASSES))))),
        "brier_score": float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1))),
        "ranked_probability_score": float(
            np.mean(np.sum((np.cumsum(probabilities, axis=1)[:, :-1] - np.cumsum(one_hot, axis=1)[:, :-1]) ** 2, axis=1))
        ),
    }


def calibration_bins(labels: pd.Series, probabilities: np.ndarray, bins: int = 10) -> list[dict[str, float | int]]:
    truth = np.eye(len(OUTCOME_CLASSES))[[OUTCOME_CLASSES.index(label) for label in labels]].reshape(-1)
    flattened = probabilities.reshape(-1)
    results = []
    for lower in np.linspace(0, 1, bins, endpoint=False):
        upper = lower + (1 / bins)
        mask = (flattened >= lower) & (flattened < upper if upper < 1 else flattened <= upper)
        if not mask.any():
            continue
        results.append(
            {
                "predicted": round(float(flattened[mask].mean()), 4),
                "observed": round(float(truth[mask].mean()), 4),
                "count": int(mask.sum()),
            }
        )
    return results


def period_payload(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "rows": len(frame),
        "from": frame["date"].min().date().isoformat(),
        "through": frame["date"].max().date().isoformat(),
    }


def test_prediction_rows(
    test_frame: pd.DataFrame,
    ensemble_probs: np.ndarray,
    predicted_goals_a: np.ndarray,
    predicted_goals_b: np.ndarray,
) -> list[dict[str, Any]]:
    rows = []
    for record, probabilities, goals_a, goals_b in zip(
        test_frame.itertuples(index=False),
        ensemble_probs,
        predicted_goals_a,
        predicted_goals_b,
    ):
        predicted_idx = int(np.argmax(probabilities))
        rows.append(
            {
                "date": record.date.date().isoformat(),
                "year": int(record.date.year),
                "tournament": record.tournament,
                "team_a": record.team_a,
                "team_b": record.team_b,
                "actual_outcome": record.outcome,
                "predicted_outcome": OUTCOME_CLASSES[predicted_idx],
                "actual_score": f"{int(record.team_a_goals)}-{int(record.team_b_goals)}",
                "predicted_score": f"{max(0, float(goals_a)):.2f}-{max(0, float(goals_b)):.2f}",
                "team_a_win": round(float(probabilities[0]), 5),
                "draw": round(float(probabilities[1]), 5),
                "team_b_win": round(float(probabilities[2]), 5),
                "correct": bool(OUTCOME_CLASSES[predicted_idx] == record.outcome),
            }
        )
    return rows


def build_model_report(
    train_frame: pd.DataFrame,
    calibration_frame: pd.DataFrame,
    test_frame: pd.DataFrame,
    component_metrics: dict[str, dict[str, float]],
    ensemble_probs: np.ndarray,
    goal_metrics: dict[str, float],
    dixon_coles_coverage: float,
    predicted_goals_a: np.ndarray,
    predicted_goals_b: np.ndarray,
) -> dict[str, Any]:
    return {
        "title": "Leakage-safe chronological model report",
        "validation_strategy": "chronological 60/20/20 train-calibrate-test",
        "periods": {
            "train": period_payload(train_frame),
            "calibration": period_payload(calibration_frame),
            "test": period_payload(test_frame),
        },
        "models": component_metrics,
        "goal_metrics": goal_metrics,
        "calibration": calibration_bins(test_frame["outcome"], ensemble_probs),
        "dixon_coles_test_coverage": round(dixon_coles_coverage, 4),
        "test_predictions": test_prediction_rows(test_frame, ensemble_probs, predicted_goals_a, predicted_goals_b),
        "historical_feature_contract": {
            "leakage_safe": True,
            "included": FEATURE_COLUMNS,
            "excluded_current_features": EXCLUDED_CURRENT_FEATURES,
            "note": "Only information available before each historical match is used for training and backtesting.",
        },
    }


def train(matches_path: Path, model_path: Path, seed: int, track_mlflow: bool = False) -> None:
    teams = load_teams()
    matches = load_matches(matches_path)
    frame = build_training_frame(matches)
    if len(frame) < 300:
        raise SystemExit("Need at least 300 matches for chronological train/calibration/test periods.")

    train_frame, calibration_frame, test_frame = chronological_partitions(frame)
    backtest_rf = fit_random_forest(train_frame, seed)
    backtest_goal_a, backtest_goal_b = fit_goal_models(train_frame, seed)
    backtest_elo = fit_elo_model(train_frame, seed)
    backtest_dc = fit_dixon_coles(train_frame)
    stacker, calibration_coverage = fit_ensemble(calibration_frame, backtest_rf, backtest_elo, backtest_dc, seed)

    rf_probs, dc_probs, elo_probs, test_coverage = component_predictions(test_frame, backtest_rf, backtest_elo, backtest_dc)
    ensemble_probs = ensemble_probabilities(stacker, rf_probs, dc_probs, elo_probs)
    component_metrics = {
        "random_forest": multiclass_metrics(test_frame["outcome"], rf_probs),
        "dixon_coles": multiclass_metrics(test_frame["outcome"], dc_probs),
        "elo": multiclass_metrics(test_frame["outcome"], elo_probs),
        "ensemble": multiclass_metrics(test_frame["outcome"], ensemble_probs),
    }
    predicted_goal_a = backtest_goal_a.predict(test_frame[FEATURE_COLUMNS].to_numpy())
    predicted_goal_b = backtest_goal_b.predict(test_frame[FEATURE_COLUMNS].to_numpy())
    goal_metrics = {
        "mae_team_a": float(mean_absolute_error(test_frame["team_a_goals"], predicted_goal_a)),
        "mae_team_b": float(mean_absolute_error(test_frame["team_b_goals"], predicted_goal_b)),
    }
    report = build_model_report(
        train_frame,
        calibration_frame,
        test_frame,
        component_metrics,
        ensemble_probs,
        goal_metrics,
        test_coverage,
        predicted_goal_a,
        predicted_goal_b,
    )

    classifier = fit_random_forest(frame, seed)
    goal_a_model, goal_b_model = fit_goal_models(frame, seed)
    elo_model = fit_elo_model(frame, seed)
    dixon_coles_model = fit_dixon_coles(frame)
    feature_importance = {
        column: float(importance)
        for column, importance in zip(FEATURE_COLUMNS, classifier.feature_importances_)
    }
    feature_stats = {
        column: {"mean": float(frame[column].mean()), "std": float(frame[column].std(ddof=0) or 1.0)}
        for column in FEATURE_COLUMNS
    }
    weights = frame["sample_weight"]
    weighted_priors = {
        label: float(weights[frame["outcome"] == label].sum() / weights.sum())
        for label in OUTCOME_CLASSES
    }
    ensemble_metrics = component_metrics["ensemble"]
    metrics = {
        "holdout_accuracy": ensemble_metrics["accuracy"],
        "holdout_log_loss": ensemble_metrics["log_loss"],
        "holdout_brier_score": ensemble_metrics["brier_score"],
        "holdout_ranked_probability_score": ensemble_metrics["ranked_probability_score"],
        "goal_mae_team_a": goal_metrics["mae_team_a"],
        "goal_mae_team_b": goal_metrics["mae_team_b"],
    }
    model_payload = {
        "classifier": classifier,
        "classifier_type": "calibrated_rf_dixon_coles_elo_ensemble",
        "elo_model": elo_model,
        "elo_feature_columns": ELO_FEATURE_COLUMNS,
        "dixon_coles_model": dixon_coles_model,
        "ensemble_calibrator": stacker,
        "ensemble_components": ["random_forest", "dixon_coles", "elo"],
        "calibration_dixon_coles_coverage": calibration_coverage,
        "probability_prior": weighted_priors,
        "probability_shrinkage": PROBABILITY_SHRINKAGE,
        "goal_a_model": goal_a_model,
        "goal_b_model": goal_b_model,
        "feature_columns": FEATURE_COLUMNS,
        "feature_importance": feature_importance,
        "feature_stats": feature_stats,
        "classes": OUTCOME_CLASSES,
        "training_rows": len(frame),
        "trained_through": matches["date"].max().date().isoformat(),
        "recency_half_life_years": RECENCY_HALF_LIFE_YEARS,
        "average_sample_weight": float(weights.mean()),
        "validation_strategy": report["validation_strategy"],
        "leakage_safe_features": True,
        "metrics": metrics,
        "model_report": report,
        "team_state": asdict_state(matches, teams),
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model_payload, model_path)

    if track_mlflow:
        log_mlflow_run(model_payload, metrics, seed, matches_path, model_path)

    print(f"Training rows: {len(frame)}")
    print("Classifier: calibrated RF + Dixon-Coles + Elo ensemble")
    print(f"Chronological test period: {report['periods']['test']['from']} to {report['periods']['test']['through']}")
    print(f"Ensemble accuracy: {metrics['holdout_accuracy']:.3f}")
    print(f"Ensemble log loss: {metrics['holdout_log_loss']:.3f}")
    print(f"Ensemble Brier score: {metrics['holdout_brier_score']:.3f}")
    print(f"Dixon-Coles test coverage: {test_coverage:.1%}")
    print(f"Saved model to {model_path}")


def log_mlflow_run(model_payload: dict[str, object], metrics: dict[str, float], seed: int, matches_path: Path, model_path: Path) -> None:
    if mlflow is None:
        print("MLflow requested but not installed. Run: pip install mlflow")
        return
    mlflow.set_experiment("worldcup-predictor")
    with mlflow.start_run(run_name=f"worldcup-ensemble-seed-{seed}"):
        mlflow.log_param("seed", seed)
        mlflow.log_param("classifier_type", model_payload.get("classifier_type"))
        mlflow.log_param("training_rows", model_payload.get("training_rows"))
        mlflow.log_param("trained_through", model_payload.get("trained_through"))
        mlflow.log_param("validation_strategy", model_payload.get("validation_strategy"))
        for name, value in metrics.items():
            mlflow.log_metric(name, value)
        mlflow.log_artifact(str(matches_path), artifact_path="data")
        mlflow.log_artifact(str(model_path), artifact_path="models")
        mlflow.sklearn.log_model(model_payload["classifier"], name="classifier")


def asdict_state(matches: pd.DataFrame, teams: dict[str, Team]) -> dict[str, dict[str, float]]:
    elo: defaultdict[str, float] = defaultdict(lambda: 1500.0)
    history: defaultdict[str, deque[dict[str, float]]] = defaultdict(lambda: deque(maxlen=10))
    match_counts: defaultdict[str, int] = defaultdict(int)

    for record in matches.itertuples(index=False):
        tournament_weight = TOURNAMENT_WEIGHT.get(record.tournament, 1.0)
        history[record.team_a].append(history_item(record.team_a_score, record.team_b_score))
        history[record.team_b].append(history_item(record.team_b_score, record.team_a_score))
        match_counts[record.team_a] += 1
        match_counts[record.team_b] += 1
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
            "recent_win_rate": recent["win_rate"],
            "recent_draw_rate": recent["draw_rate"],
            "recent_points_volatility": recent["points_volatility"],
            "recent_goal_diff_volatility": recent["goal_diff_volatility"],
            "experience_log": math.log1p(match_counts[name]),
        }
    return state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the World Cup RF + Dixon-Coles + Elo ensemble.")
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
