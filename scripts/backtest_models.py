#!/usr/bin/env python3
"""Print or export the chronological model report stored by train_model.py."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import joblib

from predict_worldcup import MODEL_PATH

OUTCOME_KEYS = {
    "team_a_win": "team_a_win",
    "draw": "draw",
    "team_b_win": "team_b_win",
}


def by_year_summary(report: dict) -> dict:
    rows = report.get("test_predictions") or []
    if not rows:
        return {
            "available": False,
            "message": "This saved model report does not include per-match test_predictions. Retrain with: python scripts/train_model.py",
            "test_period": report.get("periods", {}).get("test"),
            "aggregate_models": report.get("models"),
        }

    grouped: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(int(row["year"]), row["tournament"])].append(row)

    periods = []
    for (year, tournament), items in sorted(grouped.items()):
        correct = sum(1 for row in items if row.get("correct"))
        log_loss = 0.0
        favorite_confidence = 0.0
        for row in items:
            actual = OUTCOME_KEYS[row["actual_outcome"]]
            probability = max(float(row[actual]), 1e-6)
            log_loss -= math.log(probability)
            favorite_confidence += max(float(row["team_a_win"]), float(row["draw"]), float(row["team_b_win"]))
        periods.append(
            {
                "year": year,
                "tournament": tournament,
                "matches": len(items),
                "accuracy": round(correct / len(items), 4),
                "log_loss": round(log_loss / len(items), 4),
                "avg_favorite_confidence": round(favorite_confidence / len(items), 4),
            }
        )

    return {
        "available": True,
        "title": "Chronological holdout by tournament year",
        "test_period": report.get("periods", {}).get("test"),
        "periods": periods,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect the saved World Cup model backtest.")
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--output", type=Path, help="Optional JSON output path.")
    parser.add_argument("--by-year", action="store_true", help="Summarize saved holdout predictions by year and tournament.")
    args = parser.parse_args()

    payload = joblib.load(args.model)
    report = payload.get("model_report")
    if not report:
        raise SystemExit("Saved model has no report. Retrain with: python scripts/train_model.py")
    rendered_payload = by_year_summary(report) if args.by_year else report
    rendered = json.dumps(rendered_payload, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Saved report to {args.output}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
