#!/usr/bin/env python3
"""Print the top transparent matchup edges for France against Brazil."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.tactics.matchup_engine import build_matchup_edges  # noqa: E402


def main() -> None:
    print("France vs Brazil: transparent tactical matchup ranking")
    print("Scores rank matchup strength; they are not calibrated probabilities.\n")
    for index, edge in enumerate(build_matchup_edges("France", "Brazil")[:8], start=1):
        players = f"{edge.team_a_player or edge.team_a} vs {edge.team_b_player or edge.team_b}"
        print(f"{index}. {edge.matchup_type}: {players}")
        print(f"   Favored: {edge.favored_team or 'Even'} | {edge.edge_label} | score {edge.edge_score:.3f}")
        print(f"   {edge.reason}")
        if edge.lineup_assumptions:
            print(f"   Assumptions: {'; '.join(edge.lineup_assumptions)}")
        print(f"   Data quality: {edge.data_quality}\n")


if __name__ == "__main__":
    main()
