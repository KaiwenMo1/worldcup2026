#!/usr/bin/env python3
"""Suggest evidence-backed manager-skill refinements; apply only when explicit."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingestion import (  # noqa: E402
    MANAGER_SKILL_UPDATES_PATH,
    TACTICAL_EVIDENCE_NORMALIZED_PATH,
    IngestionStatus,
    apply_manager_skill_updates,
    append_data_quality_issues,
    append_ingestion_run,
    create_ingestion_run,
    load_normalized_tactical_evidence,
    suggest_manager_skill_updates,
    write_manager_skill_updates,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a manager-skill refinement review queue.")
    parser.add_argument("--input", type=Path, default=TACTICAL_EVIDENCE_NORMALIZED_PATH)
    parser.add_argument("--output", type=Path, default=MANAGER_SKILL_UPDATES_PATH)
    parser.add_argument("--manager-id", help="Limit suggestions to one manager.")
    parser.add_argument("--apply", action="store_true", help="Apply eligible updates to existing validated manager skill JSON.")
    args = parser.parse_args()

    started = datetime.now(timezone.utc)
    evidence, load_issues = load_normalized_tactical_evidence(args.input)
    if args.manager_id:
        evidence = [row for row in evidence if row.manager_id == args.manager_id]
    updates = suggest_manager_skill_updates(evidence)
    refinement = apply_manager_skill_updates(updates, evidence, apply=args.apply)
    applied_ids = set(refinement.applied_update_ids)
    now = datetime.now(timezone.utc)
    if applied_ids:
        updates = [
            update.model_copy(update={"applied": True, "applied_at": now}) if update.update_id in applied_ids else update
            for update in updates
        ]
    write_issues = write_manager_skill_updates(updates, args.output)
    issues = [*load_issues, *refinement.issues, *write_issues]
    critical = any(issue.severity.value == "critical" for issue in issues)
    errors = any(issue.severity.value == "error" for issue in issues)
    status = IngestionStatus.FAILED if critical else IngestionStatus.PARTIAL if issues else IngestionStatus.SUCCEEDED
    run = create_ingestion_run(
        source_id="project_repository",
        script="scripts/refine_manager_skills.py",
        status=status,
        rows_raw=len(evidence),
        rows_normalized=len(evidence),
        rows_failed=0,
        error_message="Manager refinement failed due to a critical issue." if critical else None,
        started_at=started,
        finished_at=datetime.now(timezone.utc),
    )
    append_ingestion_run(run)
    if issues:
        append_data_quality_issues([issue.model_copy(update={"run_id": run.run_id}) for issue in issues])
    ready = sum(update.review_status.value == "ready_for_review" for update in updates)
    print(
        f"Saved {len(updates)} manager-skill suggestions ({ready} ready for review, "
        f"{len(applied_ids)} applied). JSON apply mode: {'enabled' if args.apply else 'disabled'}."
    )
    raise SystemExit(1 if critical or (args.apply and errors) else 0)


if __name__ == "__main__":
    main()
