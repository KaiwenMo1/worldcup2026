#!/usr/bin/env python3
"""Build a reviewable manager skill from manually curated evidence."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingestion import (  # noqa: E402
    IngestionStatus,
    append_data_quality_issues,
    append_ingestion_run,
    create_ingestion_run,
)
from app.manager_distillation import (  # noqa: E402
    build_manager_skill,
    load_evidence_directory,
    validate_manager_skill,
    write_generated_skill,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Nuwa-inspired football manager skill.")
    parser.add_argument("--manager-id", required=True)
    parser.add_argument("--manager-name", required=True)
    parser.add_argument("--team", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--version", default="0.1")
    args = parser.parse_args()

    started = datetime.now(timezone.utc)
    loaded = load_evidence_directory(args.evidence_dir, args.manager_id)
    skill = build_manager_skill(
        manager_id=args.manager_id,
        manager_name=args.manager_name,
        team=args.team,
        records=loaded.records,
        documents=loaded.documents,
        version=args.version,
    )
    report = validate_manager_skill(skill)
    output = write_generated_skill(skill, report)
    finished = datetime.now(timezone.utc)
    status = IngestionStatus.FAILED if report.status == "FAIL" else IngestionStatus.PARTIAL if loaded.issues else IngestionStatus.SUCCEEDED
    run = create_ingestion_run(
        source_id="manual_csv",
        script="scripts/create_manager_skill.py",
        status=status,
        rows_raw=len(loaded.records) + len(loaded.issues),
        rows_normalized=len(loaded.records),
        rows_failed=len(loaded.issues),
        error_message="Manager skill validation failed." if report.status == "FAIL" else None,
        started_at=started,
        finished_at=finished,
    )
    append_ingestion_run(run)
    if loaded.issues:
        append_data_quality_issues([issue.model_copy(update={"run_id": run.run_id}) for issue in loaded.issues])
    print(f"Created {output} with validation status {report.status}")
    raise SystemExit(1 if report.status == "FAIL" else 0)


if __name__ == "__main__":
    main()
