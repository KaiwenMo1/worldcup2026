#!/usr/bin/env python3
"""Import local Agent-Reach Markdown evidence into the review queue."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.research_tools import (  # noqa: E402
    AGENT_REACH_INBOX_DIR,
    AGENT_REACH_REVIEW_QUEUE_PATH,
    import_agent_reach_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=AGENT_REACH_INBOX_DIR)
    parser.add_argument("--review-queue", type=Path, default=AGENT_REACH_REVIEW_QUEUE_PATH)
    args = parser.parse_args()

    result = import_agent_reach_markdown(args.input_dir, review_queue_path=args.review_queue)
    for issue in result.issues:
        print(f"{issue.severity}: {issue.problem}")
    print(f"Imported {len(result.documents)} Agent-Reach Markdown files.")
    print(f"Review rows written: {len(result.review_rows)} -> {args.review_queue}")
    raise SystemExit(1 if any(issue.severity.value in {"error", "critical"} for issue in result.issues) else 0)


if __name__ == "__main__":
    main()
