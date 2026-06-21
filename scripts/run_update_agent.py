#!/usr/bin/env python3
"""Run the accountable World Cup update agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from app.agentic_update import AgenticUpdateConfig, run_update_agent  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Observe, plan, run, and report tournament update tools.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Execute the planned safe update tools.")
    mode.add_argument("--dry-run", action="store_true", help="Plan only. This is the default.")
    parser.add_argument("--include-provider", action="store_true", help="Use configured provider score APIs when keys exist.")
    parser.add_argument("--skip-official", action="store_true", help="Skip official FIFA calendar score refresh.")
    parser.add_argument("--skip-event-feed", action="store_true", help="Skip configured event-feed ingestion.")
    parser.add_argument("--skip-lineups", action="store_true", help="Skip lineup/squad refresh tools.")
    parser.add_argument("--run-arena", action="store_true", help="Publish nearby Prediction Arena cards.")
    parser.add_argument("--verify", action="store_true", help="Run compact verification after update tools.")
    parser.add_argument("--no-subprocess", action="store_true", help="Disallow command-based tools.")
    parser.add_argument("--hours-ahead", type=int, default=36)
    return parser.parse_args()


def main() -> None:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    config = AgenticUpdateConfig(
        apply=args.apply,
        refresh_official=not args.skip_official,
        include_provider=args.include_provider,
        include_event_feed=not args.skip_event_feed,
        include_lineups=not args.skip_lineups,
        run_arena=args.run_arena,
        verify=args.verify,
        allow_subprocess=not args.no_subprocess,
        hours_ahead=args.hours_ahead,
    )
    report = run_update_agent(config)
    print(json.dumps(report.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
