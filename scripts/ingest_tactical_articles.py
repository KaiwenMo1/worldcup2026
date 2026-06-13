#!/usr/bin/env python3
"""Ingest manually curated tactical articles and match-report evidence."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingestion import (  # noqa: E402
    MANUAL_TACTICAL_EVIDENCE_SAMPLE_PATH,
    TACTICAL_EVIDENCE_NORMALIZED_PATH,
    IngestionStatus,
    ManualCsvTacticalEvidenceAdapter,
    append_data_quality_issues,
    append_ingestion_run,
    create_ingestion_run,
    get_source,
    ingest_tactical_evidence,
    write_normalized_tactical_evidence,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest manually curated tactical evidence.")
    parser.add_argument("--source", default="manual_csv")
    parser.add_argument("--input", type=Path, default=MANUAL_TACTICAL_EVIDENCE_SAMPLE_PATH)
    parser.add_argument("--output", type=Path, default=TACTICAL_EVIDENCE_NORMALIZED_PATH)
    args = parser.parse_args()

    source = get_source(args.source)
    if source is None:
        raise SystemExit(f"Unknown source_id {args.source!r}; register it in data/provenance/source_registry.csv.")
    if not source.enabled:
        raise SystemExit(f"Source {args.source!r} is disabled.")

    started = datetime.now(timezone.utc)
    result = ingest_tactical_evidence(ManualCsvTacticalEvidenceAdapter(args.input, source.reliability_score))
    write_issues = write_normalized_tactical_evidence(result.records, args.output)
    issues = [*result.issues, *write_issues]
    normalized = len(result.records)
    failed = max(0, result.rows_raw - normalized)
    critical = any(issue.severity.value == "critical" for issue in issues)
    status = (
        IngestionStatus.FAILED
        if critical or (result.rows_raw > 0 and normalized == 0)
        else IngestionStatus.PARTIAL
        if issues
        else IngestionStatus.SUCCEEDED
    )
    run = create_ingestion_run(
        source_id=source.source_id,
        script="scripts/ingest_tactical_articles.py",
        status=status,
        rows_raw=result.rows_raw,
        rows_normalized=normalized,
        rows_failed=failed,
        error_message="Tactical-evidence ingestion failed validation." if status == IngestionStatus.FAILED else None,
        started_at=started,
        finished_at=datetime.now(timezone.utc),
    )
    append_ingestion_run(run)
    if issues:
        append_data_quality_issues([issue.model_copy(update={"run_id": run.run_id}) for issue in issues])
    print(f"Ingested {normalized} tactical evidence rows from {result.rows_raw} raw rows ({len(issues)} issues).")
    raise SystemExit(1 if status == IngestionStatus.FAILED else 0)


if __name__ == "__main__":
    main()
