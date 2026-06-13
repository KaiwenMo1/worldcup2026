#!/usr/bin/env python3
"""Evaluate one completed match across model, manager, matchup, and analyst layers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.evaluation import (  # noqa: E402
    CompletedMatch,
    evaluate_completed_match,
    load_completed_matches,
    write_completed_evaluations,
)


def _completed_from_args(args: argparse.Namespace) -> CompletedMatch:
    existing = next((match for match in load_completed_matches() if match.match_id == args.match_id), None)
    if existing is not None:
        return existing
    required = (args.match_id, args.team_a, args.team_b, args.score_a, args.score_b)
    if any(value is None for value in required):
        raise SystemExit(
            "Match was not found in data/live_state.json. Supply --match-id, --team-a, --team-b, --score-a, and --score-b."
        )
    return CompletedMatch(
        match_id=args.match_id,
        team_a=args.team_a,
        team_b=args.team_b,
        team_a_score=args.score_a,
        team_b_score=args.score_b,
        source="manual_cli",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate one completed match.")
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--team-a")
    parser.add_argument("--team-b")
    parser.add_argument("--score-a", type=int)
    parser.add_argument("--score-b", type=int)
    parser.add_argument("--formation-a")
    parser.add_argument("--formation-b")
    parser.add_argument("--no-model", action="store_true", help="Replay the Poisson baseline instead of the saved ensemble.")
    args = parser.parse_args()

    completed = _completed_from_args(args)
    formations = {
        team: formation
        for team, formation in ((completed.team_a, args.formation_a), (completed.team_b, args.formation_b))
        if formation
    }
    result = evaluate_completed_match(completed, actual_formations=formations, use_model=not args.no_model)
    issues = write_completed_evaluations(result)
    critical = [issue for issue in issues if issue.severity.value in {"error", "critical"}]
    print(
        f"Evaluated {completed.match_id}: model winner_hit={result.model.winner_hit}, "
        f"brier={result.model.brier_score:.3f}, managers={len(result.managers)}, "
        f"matchups={len(result.matchups)}, analysts={len(result.analysts)}."
    )
    if issues:
        print(f"Storage notices: {len(issues)} ({len(critical)} errors).")
    raise SystemExit(1 if critical else 0)


if __name__ == "__main__":
    main()
