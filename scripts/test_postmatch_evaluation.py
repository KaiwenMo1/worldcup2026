#!/usr/bin/env python3
"""Smoke-test the complete transparent post-match feedback loop."""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.evaluation import (  # noqa: E402
    CompletedMatch,
    ModelPredictionSnapshot,
    evaluate_completed_match,
)
from app.evaluation.analyst_evaluator import write_analyst_evaluations  # noqa: E402
from app.evaluation.manager_skill_evaluator import write_manager_skill_evaluations  # noqa: E402
from app.evaluation.matchup_evaluator import write_matchup_evaluations  # noqa: E402
from app.evaluation.postmatch_evaluator import write_model_evaluations  # noqa: E402


def main() -> None:
    completed = CompletedMatch(
        match_id="FRA-BRA-TEST",
        team_a="France",
        team_b="Brazil",
        team_a_score=2,
        team_b_score=1,
        source="event_sample",
    )
    prediction = ModelPredictionSnapshot(
        match_id=completed.match_id,
        team_a=completed.team_a,
        team_b=completed.team_b,
        predicted_team_a_score=2,
        predicted_team_b_score=1,
        team_a_win_probability=0.55,
        draw_probability=0.25,
        team_b_win_probability=0.20,
        model_version="smoke-test",
        prediction_source="fixed_test_snapshot",
    )
    evaluated_at = datetime(2026, 6, 12, 12, tzinfo=timezone.utc)
    result = evaluate_completed_match(
        completed,
        prediction,
        actual_formations={"France": "4-2-3-1"},
        evaluated_at=evaluated_at,
    )
    assert result.model.winner_hit and result.model.exact_score_hit
    assert len(result.managers) == 2
    assert result.matchups
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        assert not write_model_evaluations([result.model], root / "model.csv")
        assert not write_manager_skill_evaluations(result.managers, root / "managers.csv")
        assert not write_matchup_evaluations(result.matchups, root / "matchups.csv")
        assert not write_analyst_evaluations(result.analysts, root / "analysts.csv")
    print(
        f"Post-match evaluation smoke test passed: brier={result.model.brier_score:.3f}, "
        f"managers={len(result.managers)}, matchups={len(result.matchups)}, analysts={len(result.analysts)}"
    )


if __name__ == "__main__":
    main()
