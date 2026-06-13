#!/usr/bin/env python3
"""Run all deterministic Prediction Arena agents on one sample match."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents import (  # noqa: E402
    run_expert_agent,
    run_kevin_agent,
    run_skeptic_agent,
    run_upset_agent,
)
from app.tactics.tactical_brief import build_tactical_brief  # noqa: E402


def main() -> None:
    forecast = {
        "expected_score": {"team_a": 1.42, "team_b": 1.08},
        "probabilities": {"team_a_win": 44.0, "draw": 29.0, "team_b_win": 27.0},
        "scorelines": [
            {"team_a_score": 1, "team_b_score": 1, "probability": 13.0},
            {"team_a_score": 1, "team_b_score": 0, "probability": 12.5},
            {"team_a_score": 2, "team_b_score": 1, "probability": 9.5},
        ],
    }
    brief = build_tactical_brief("France", "Brazil", match_id="M001", forecast=forecast)
    expert = run_expert_agent("M001", "France", "Brazil", "knockout", forecast=forecast, tactical_brief=brief)
    kevin = run_kevin_agent("M001", "France", "Brazil", "knockout", forecast=forecast, tactical_brief=brief)
    upset = run_upset_agent(
        "M001",
        "France",
        "Brazil",
        "knockout",
        forecast=forecast,
        tactical_brief=brief,
        context={"weather": "humid", "favorite_fatigue": True},
    )
    skeptic = run_skeptic_agent("M001", expert, kevin, upset, forecast=forecast, tactical_brief=brief)
    for output in (expert, kevin, upset, skeptic):
        print(output.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
