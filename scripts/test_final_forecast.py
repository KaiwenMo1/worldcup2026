#!/usr/bin/env python3
"""Print one Final Forecast and its inspectable aggregation trace."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents import (  # noqa: E402
    run_expert_agent,
    run_final_forecast_agent,
    run_kevin_agent,
    run_skeptic_agent,
    run_upset_agent,
)
from app.prediction_arena.arena_aggregator import aggregate_prediction_arena  # noqa: E402


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
    brief = {
        "top_matchup_edges": [
            {
                "matchup_type": "winger_vs_fullback",
                "team_a_player": "France LW",
                "team_b_player": "Brazil RB",
                "favored_team": "France",
                "edge_score": 0.67,
                "reason": "France can repeatedly isolate Brazil's right back.",
            }
        ],
        "tactical_summary": "France has the clearer transition route, but Brazil can slow the game.",
    }
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
    skeptic = run_skeptic_agent(
        "M001",
        expert,
        kevin,
        upset,
        forecast=forecast,
        tactical_brief=brief,
    )
    aggregation = aggregate_prediction_arena(
        "M001",
        "France",
        "Brazil",
        "knockout",
        expert=expert,
        kevin=kevin,
        upset=upset,
        skeptic=skeptic,
        base_forecast=forecast,
    )
    final = run_final_forecast_agent(
        "M001",
        "France",
        "Brazil",
        "knockout",
        expert=expert,
        kevin=kevin,
        upset=upset,
        skeptic=skeptic,
        base_forecast=forecast,
        tactical_brief=brief,
    )
    print("AGGREGATION TRACE")
    print(aggregation.model_dump_json(indent=2))
    print("\nFINAL FORECAST")
    print(final.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
