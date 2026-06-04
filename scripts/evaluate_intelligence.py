#!/usr/bin/env python3
"""Evaluate deterministic routing and retrieval for the Intelligence Desk."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.intelligence import get_intelligence_index  # noqa: E402

CASES = [
    {
        "question": "Why does France have an edge over Brazil?",
        "teams": ["France", "Brazil"],
        "venues": [],
        "tools": ["retrieve_knowledge", "team_profile", "head_to_head", "match_forecast"],
    },
    {
        "question": "How does Mexico City weather affect a match?",
        "teams": [],
        "venues": ["Mexico City"],
        "tools": ["retrieve_knowledge", "venue_weather"],
    },
    {
        "question": "What is the latest live state?",
        "teams": [],
        "venues": [],
        "tools": ["retrieve_knowledge", "live_state"],
    },
    {
        "question": "Which teams are underrated by the model?",
        "teams": [],
        "venues": [],
        "tools": ["retrieve_knowledge", "team_shortlist"],
    },
    {
        "question": "Compare USA and Argentina",
        "teams": ["USA", "Argentina"],
        "venues": [],
        "tools": ["retrieve_knowledge", "team_profile", "head_to_head", "match_forecast"],
    },
]


def evaluate() -> dict[str, Any]:
    index = get_intelligence_index(ROOT)
    index.ensure_ready()
    results = []
    for case in CASES:
        entities = index.identify_entities(case["question"])
        tools = index.route(case["question"], entities)
        evidence = index.retrieve(case["question"], top_k=4, preferred_tags=[*entities["teams"], *entities["venues"]])
        checks = {
            "teams": entities["teams"] == case["teams"],
            "venues": entities["venues"] == case["venues"],
            "tools": all(tool in tools for tool in case["tools"]),
            "evidence": len(evidence) > 0,
        }
        results.append(
            {
                "question": case["question"],
                "passed": all(checks.values()),
                "checks": checks,
                "entities": entities,
                "tools": tools,
                "evidence_count": len(evidence),
            }
        )
    passed = sum(result["passed"] for result in results)
    return {
        "passed": passed,
        "total": len(results),
        "pass_rate": round(100 * passed / len(results), 1),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate()
    print(f"Intelligence eval: {report['passed']}/{report['total']} passed ({report['pass_rate']}%)")
    for result in report["results"]:
        print(f"{'PASS' if result['passed'] else 'FAIL'}  {result['question']}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Saved report to {args.output}")


if __name__ == "__main__":
    main()
