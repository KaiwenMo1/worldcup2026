#!/usr/bin/env python3
"""Rebuild post-match player stats, ratings, form, role vectors, and team overlays."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingestion.postmatch_player_ingestion import run_postmatch_player_update  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Turn observed match events and lineups into model-ready player signals.")
    parser.add_argument("--json", action="store_true", help="Print a JSON summary.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_postmatch_player_update()
    payload = {
        "event_rows": result.event_rows,
        "lineup_rows": result.lineup_rows,
        "derived_match_stats": result.derived_match_stats,
        "merged_match_stats": result.merged_match_stats,
        "player_postmatch_signals": result.player_postmatch_signals,
        "player_form_signals": result.player_form_signals,
        "player_role_vectors": result.player_role_vectors,
        "live_team_feature_rows": result.live_team_feature_rows,
        "issue_count": len(result.issues),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            "Post-match player data: "
            f"{result.derived_match_stats} player match rows, "
            f"{result.player_postmatch_signals} player ratings, "
            f"{result.player_form_signals} form signals, "
            f"{result.player_role_vectors} role vectors, "
            f"{result.live_team_feature_rows} live team overlays "
            f"({len(result.issues)} issues)."
        )
    critical = any(issue.severity.value == "critical" for issue in result.issues)
    raise SystemExit(1 if critical else 0)


if __name__ == "__main__":
    main()
