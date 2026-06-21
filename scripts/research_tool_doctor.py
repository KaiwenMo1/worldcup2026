#!/usr/bin/env python3
"""Print optional research-agent tool availability and recommended workflow."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.research_tools import recommended_research_workflow, research_tool_summary  # noqa: E402


def main() -> None:
    summary = research_tool_summary()
    print(json.dumps(summary, indent=2))
    print("\nRecommended workflow:")
    for step in recommended_research_workflow():
        print(f"- {step}")


if __name__ == "__main__":
    main()
