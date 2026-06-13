#!/usr/bin/env python3
"""Evaluate every completed match currently recorded in live_state.json."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.evaluation import evaluate_completed_match, load_completed_matches, write_completed_evaluations  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate all completed matches.")
    parser.add_argument("--no-model", action="store_true", help="Replay the Poisson baseline instead of the saved ensemble.")
    args = parser.parse_args()

    matches = load_completed_matches()
    if not matches:
        print("No completed matches are recorded in data/live_state.json.")
        return

    issues = []
    analyst_rows = manager_rows = matchup_rows = 0
    for completed in matches:
        result = evaluate_completed_match(completed, use_model=not args.no_model)
        issues.extend(write_completed_evaluations(result))
        analyst_rows += len(result.analysts)
        manager_rows += len(result.managers)
        matchup_rows += len(result.matchups)
    critical = [issue for issue in issues if issue.severity.value in {"error", "critical"}]
    print(
        f"Evaluated {len(matches)} completed matches: managers={manager_rows}, "
        f"matchups={matchup_rows}, analysts={analyst_rows}, storage_errors={len(critical)}."
    )
    raise SystemExit(1 if critical else 0)


if __name__ == "__main__":
    main()
