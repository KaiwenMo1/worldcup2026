#!/usr/bin/env python3
"""Tune the World Cup Random Forest with Optuna."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import optuna
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import log_loss
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing tuning dependencies. Run:\n"
        "  source .venv/bin/activate\n"
        "  pip install optuna"
    ) from exc

from predict_worldcup import ROOT
from train_model import FEATURE_COLUMNS, MATCHES_PATH, build_training_frame, chronological_partitions, load_matches


OUTPUT_PATH = ROOT / "models" / "optuna_best_params.json"


def tune(matches_path: Path, output_path: Path, trials: int, seed: int) -> None:
    matches = load_matches(matches_path)
    frame = build_training_frame(matches)
    train_frame, _, test_frame = chronological_partitions(frame)
    x_train = train_frame[FEATURE_COLUMNS]
    y_train = train_frame["outcome"]
    w_train = train_frame["sample_weight"]
    x_test = test_frame[FEATURE_COLUMNS]
    y_test = test_frame["outcome"]

    def objective(trial: optuna.Trial) -> float:
        classifier = RandomForestClassifier(
            n_estimators=trial.suggest_int("n_estimators", 80, 260, step=20),
            min_samples_leaf=trial.suggest_int("min_samples_leaf", 1, 8),
            max_depth=trial.suggest_int("max_depth", 4, 24),
            max_features=trial.suggest_categorical("max_features", ["sqrt", "log2", None]),
            class_weight=trial.suggest_categorical("class_weight", ["balanced", "balanced_subsample"]),
            n_jobs=1,
            random_state=seed,
        )
        classifier.fit(x_train.to_numpy(), y_train, sample_weight=w_train.to_numpy())
        probabilities = classifier.predict_proba(x_test.to_numpy())
        return log_loss(y_test, probabilities, labels=classifier.classes_)

    study = optuna.create_study(direction="minimize", study_name="worldcup-random-forest")
    study.optimize(objective, n_trials=trials)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "best_value_log_loss": study.best_value,
                "best_params": study.best_params,
                "trials": trials,
                "seed": seed,
                "training_rows": len(frame),
                "validation_strategy": "chronological train/test",
            },
            handle,
            indent=2,
        )

    print(f"Best log loss: {study.best_value:.4f}")
    print(f"Best params: {study.best_params}")
    print(f"Saved tuning result to {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tune World Cup Random Forest hyperparameters with Optuna.")
    parser.add_argument("--matches", type=Path, default=MATCHES_PATH, help="Historical matches CSV path.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Where to save best params JSON.")
    parser.add_argument("--trials", type=int, default=30, help="Number of Optuna trials.")
    parser.add_argument("--seed", type=int, default=26, help="Random seed.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.trials < 1:
        raise SystemExit("--trials must be at least 1")
    tune(args.matches, args.output, args.trials, args.seed)


if __name__ == "__main__":
    main()
