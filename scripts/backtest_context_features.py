#!/usr/bin/env python3
"""Gate manager/player forecast integration behind chronological backtest gains."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/worldcup-matplotlib")

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import log_loss

from predict_worldcup import ROOT
from train_model import (
    FEATURE_COLUMNS,
    OUTCOME_CLASSES,
    build_training_frame,
    chronological_partitions,
    load_matches,
    multiclass_metrics,
)


CONTEXT_PATH = ROOT / "data" / "historical_context_features.csv"
OUTPUT_PATH = ROOT / "data" / "context_feature_gate.json"
CONTEXT_COLUMNS = ["manager_edge", "player_quality_edge", "lineup_continuity_edge"]


def aligned(model: RandomForestClassifier, values: np.ndarray) -> np.ndarray:
    raw = model.predict_proba(values)
    output = np.zeros((len(values), len(OUTCOME_CLASSES)))
    for index, label in enumerate(model.classes_):
        output[:, OUTCOME_CLASSES.index(label)] = raw[:, index]
    return output


def fit_probabilities(train: pd.DataFrame, test: pd.DataFrame, columns: list[str], seed: int) -> np.ndarray:
    model = RandomForestClassifier(
        n_estimators=180,
        min_samples_leaf=5,
        max_features="sqrt",
        class_weight="balanced_subsample",
        n_jobs=1,
        random_state=seed,
    )
    model.fit(train[columns].to_numpy(), train["outcome"], sample_weight=train["sample_weight"].to_numpy())
    return aligned(model, test[columns].to_numpy())


def evaluate_gate(
    frame: pd.DataFrame,
    minimum_coverage: float = 0.60,
    minimum_log_loss_improvement: float = 0.005,
    minimum_brier_improvement: float = 0.002,
    seed: int = 26,
) -> dict[str, Any]:
    _, _, test = chronological_partitions(frame)
    train, _, _ = chronological_partitions(frame)
    coverage = float(test["context_observed"].mean()) if len(test) else 0.0
    thresholds = {
        "minimum_coverage": minimum_coverage,
        "minimum_log_loss_improvement": minimum_log_loss_improvement,
        "minimum_brier_improvement": minimum_brier_improvement,
    }
    if coverage < minimum_coverage or len(train) < 100 or len(test) < 30:
        return {
            "enabled": False,
            "coverage": round(coverage, 4),
            "baseline": None,
            "candidate": None,
            "improvement": None,
            "thresholds": thresholds,
            "reason": "Insufficient chronological observed-context coverage for a trustworthy comparison.",
        }

    baseline_probs = fit_probabilities(train, test, FEATURE_COLUMNS, seed)
    candidate_columns = FEATURE_COLUMNS + CONTEXT_COLUMNS
    candidate_probs = fit_probabilities(train, test, candidate_columns, seed)
    baseline = multiclass_metrics(test["outcome"], baseline_probs)
    candidate = multiclass_metrics(test["outcome"], candidate_probs)
    improvement = {
        "log_loss": baseline["log_loss"] - candidate["log_loss"],
        "brier_score": baseline["brier_score"] - candidate["brier_score"],
    }
    enabled = (
        improvement["log_loss"] >= minimum_log_loss_improvement
        and improvement["brier_score"] >= minimum_brier_improvement
    )
    return {
        "enabled": enabled,
        "coverage": round(coverage, 4),
        "baseline": baseline,
        "candidate": candidate,
        "improvement": improvement,
        "thresholds": thresholds,
        "reason": (
            "Observed manager/player context passed chronological activation thresholds."
            if enabled
            else "Observed manager/player context did not improve both required calibration metrics."
        ),
    }


def build_frame(matches_path: Path, context_path: Path) -> pd.DataFrame:
    frame = build_training_frame(load_matches(matches_path))
    if not context_path.exists():
        for column in CONTEXT_COLUMNS:
            frame[column] = 0.0
        frame["context_observed"] = 0
        return frame
    context = pd.read_csv(context_path, parse_dates=["date"])
    required = {"date", "team_a", "team_b", *CONTEXT_COLUMNS}
    missing = required - set(context.columns)
    if missing:
        raise SystemExit(f"{context_path} is missing columns: {', '.join(sorted(missing))}")
    context["context_observed"] = 1
    frame = frame.merge(context[["date", "team_a", "team_b", *CONTEXT_COLUMNS, "context_observed"]], on=["date", "team_a", "team_b"], how="left")
    for column in CONTEXT_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    frame["context_observed"] = frame["context_observed"].fillna(0).astype(int)
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description="Chronologically gate observed manager/player context features.")
    parser.add_argument("--matches", type=Path, default=ROOT / "data" / "historical_matches.csv")
    parser.add_argument("--context", type=Path, default=CONTEXT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--seed", type=int, default=26)
    args = parser.parse_args()
    result = evaluate_gate(build_frame(args.matches, args.context), seed=args.seed)
    result["evaluated_at"] = datetime.now(timezone.utc).isoformat()
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
