#!/usr/bin/env python3
"""Smoke-test Prediction Arena contracts without touching project ledgers."""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.prediction_arena import (  # noqa: E402
    PredictionLedgerConflict,
    PredictionRecord,
    PredictionStage,
    append_prediction_record,
    compute_leaderboard,
    ensure_entertainment_disclaimer,
    load_predictions,
    lock_prediction,
    reject_betting_advice_language,
    settle_virtual_pick,
)


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger = root / "pre_match_predictions.csv"
        results = root / "virtual_pick_results.csv"
        prediction = PredictionRecord(
            prediction_id="smoke-kevin-v1",
            match_id="M001",
            created_at=datetime.now(timezone.utc),
            team_a="France",
            team_b="Brazil",
            stage=PredictionStage.KNOCKOUT,
            agent_name="Kevin Agent",
            regular_time_pick="Draw",
            regular_time_score="1-1",
            qualification_pick="France advance",
            penalty_probability=0.22,
            confidence=0.61,
            core_reason="France has the clearest transition matchup.",
            fragile_assumptions=["France's left winger starts and is fully fit."],
        )

        append_prediction_record(prediction, ledger)
        locked = lock_prediction(prediction.prediction_id, ledger)
        assert len(load_predictions(ledger)) == 1
        assert locked.status.value == "locked"
        try:
            append_prediction_record(prediction, ledger)
        except PredictionLedgerConflict:
            pass
        else:
            raise AssertionError("locked prediction overwrite was not rejected")

        settled = settle_virtual_pick(
            locked,
            actual_regular_time_result="Draw",
            actual_score="1-1",
            actual_qualification_result="France advance",
            path=results,
        )
        leaderboard = compute_leaderboard(results)
        assert settled.total_points == 10
        assert leaderboard[0].agent_name == "Kevin Agent"
        reject_betting_advice_language(locked)
        assert "not betting advice" in ensure_entertainment_disclaimer("France vs Brazil prediction").casefold()
        print(
            "Prediction Arena skeleton smoke test passed: "
            f"ledger=1, locked=1, virtual_points={settled.total_points}, leaders={len(leaderboard)}"
        )


if __name__ == "__main__":
    main()
