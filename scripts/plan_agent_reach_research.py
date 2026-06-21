#!/usr/bin/env python3
"""Create a local Agent-Reach research plan for manager-skill evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.research_tools import (  # noqa: E402
    AGENT_REACH_PLAN_PATH,
    build_agent_reach_research_tasks,
    write_agent_reach_plan,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team", help="Limit to one team.")
    parser.add_argument("--manager-id", help="Limit to one manager id.")
    parser.add_argument("--limit", type=int, help="Limit number of manager registry rows before task expansion.")
    parser.add_argument("--include-social", action="store_true", help="Include login-sensitive social research tasks.")
    parser.add_argument("--output", type=Path, default=AGENT_REACH_PLAN_PATH)
    args = parser.parse_args()

    tasks = build_agent_reach_research_tasks(
        team=args.team,
        manager_id=args.manager_id,
        include_social=args.include_social,
        limit=args.limit,
    )
    issues = write_agent_reach_plan(tasks, args.output)
    for issue in issues:
        print(f"{issue.severity}: {issue.problem}")
    print(f"Wrote {len(tasks)} Agent-Reach research tasks to {args.output}")
    if tasks:
        print("\nFirst task prompt:\n")
        print(tasks[0].agent_prompt)
    raise SystemExit(1 if any(issue.severity.value in {"error", "critical"} for issue in issues) else 0)


if __name__ == "__main__":
    main()
