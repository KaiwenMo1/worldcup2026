#!/usr/bin/env python3
"""Collect public research evidence into reviewable Markdown artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.research_tools import collect_public_evidence, write_research_documents  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", action="append", default=[], help="Public URL to collect. May be passed multiple times.")
    parser.add_argument("--input-html", type=Path, help="Local HTML file to parse instead of fetching a URL.")
    parser.add_argument("--title", help="Optional title override for local HTML or URL evidence.")
    parser.add_argument("--source-id", default="research_scout_public_web")
    parser.add_argument("--manager-id")
    parser.add_argument("--team")
    parser.add_argument("--category", default="external_views")
    parser.add_argument("--notes")
    args = parser.parse_args()

    documents = []
    issues = []
    if args.input_html:
        result = collect_public_evidence(
            html=args.input_html.read_text(encoding="utf-8"),
            title=args.title,
            source_id=args.source_id,
            manager_id=args.manager_id,
            team=args.team,
            category=args.category,
            notes=args.notes,
        )
        documents.extend(result.documents)
        issues.extend(result.issues)
    for url in args.url:
        result = collect_public_evidence(
            url=url,
            title=args.title,
            source_id=args.source_id,
            manager_id=args.manager_id,
            team=args.team,
            category=args.category,
            notes=args.notes,
        )
        documents.extend(result.documents)
        issues.extend(result.issues)

    issues.extend(write_research_documents(documents))
    for issue in issues:
        print(f"{issue.severity}: {issue.problem}")
    for document in documents:
        print(f"Collected {document.evidence_id}: {document.title} ({document.word_count} words)")
    raise SystemExit(1 if any(issue.severity.value in {"error", "critical"} for issue in issues) else 0)


if __name__ == "__main__":
    main()
