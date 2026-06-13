#!/usr/bin/env python3
"""Print one transparent manager-plan smoke example."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.tactics.manager_skills import generate_manager_plan  # noqa: E402
from app.tactics.schemas import MatchContext  # noqa: E402


def main() -> None:
    context = MatchContext(
        match_state="tied",
        minute=0,
        knockout=True,
        opponent_high_line=True,
        opponent_recovery_defender_score=64,
        opponent_midfield_control=True,
        opponent_possession_share=0.59,
        notes=["Demonstration context only; no external data was fetched."],
    )
    plan = generate_manager_plan("France", "Brazil", context)
    print(plan.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
