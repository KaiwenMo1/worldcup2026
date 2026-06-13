#!/usr/bin/env python3
"""Ingest provider-mapped post-match events and build transparent match summaries."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingestion import (  # noqa: E402
    MANUAL_MATCH_EVENTS_SAMPLE_PATH,
    MATCH_EVENTS_NORMALIZED_PATH,
    MATCH_SUMMARY_SIGNALS_PATH,
    IngestionStatus,
    ManualCsvEventAdapter,
    append_data_quality_issues,
    append_ingestion_run,
    build_match_summary_signals,
    create_ingestion_run,
    get_source,
    ingest_event_data,
    write_match_summary_signals,
    write_normalized_events,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest post-match event data using a manual CSV adapter.")
    parser.add_argument("--source", default="manual_csv")
    parser.add_argument("--input", type=Path, default=MANUAL_MATCH_EVENTS_SAMPLE_PATH)
    parser.add_argument("--normalized-output", type=Path, default=MATCH_EVENTS_NORMALIZED_PATH)
    parser.add_argument("--summary-output", type=Path, default=MATCH_SUMMARY_SIGNALS_PATH)
    args = parser.parse_args()

    source = get_source(args.source)
    if source is None:
        raise SystemExit(f"Unknown source_id {args.source!r}; register it in data/provenance/source_registry.csv.")
    if not source.enabled:
        raise SystemExit(f"Source {args.source!r} is disabled.")

    started = datetime.now(timezone.utc)
    result = ingest_event_data(ManualCsvEventAdapter(args.input, source.reliability_score))
    summaries = build_match_summary_signals(result.events)
    write_issues = [
        *write_normalized_events(result.events, args.normalized_output),
        *write_match_summary_signals(summaries, args.summary_output),
    ]
    issues = [*result.issues, *write_issues]
    normalized = len(result.events)
    failed = max(0, result.rows_raw - normalized)
    critical = any(issue.severity.value == "critical" for issue in issues)
    errors = any(issue.severity.value == "error" for issue in issues)
    status = (
        IngestionStatus.FAILED
        if critical or (result.rows_raw > 0 and normalized == 0)
        else IngestionStatus.PARTIAL
        if errors or failed
        else IngestionStatus.SUCCEEDED
    )
    run = create_ingestion_run(
        source_id=source.source_id,
        script="scripts/ingest_event_data.py",
        status=status,
        rows_raw=result.rows_raw,
        rows_normalized=normalized,
        rows_failed=failed,
        error_message="Event-data ingestion failed validation." if status == IngestionStatus.FAILED else None,
        started_at=started,
        finished_at=datetime.now(timezone.utc),
    )
    append_ingestion_run(run)
    if issues:
        append_data_quality_issues([issue.model_copy(update={"run_id": run.run_id}) for issue in issues])
    informational = sum(issue.severity.value == "info" for issue in issues)
    print(
        f"Ingested {normalized} events into {len(summaries)} match-team summaries "
        f"({failed} rejected rows, {informational} optional-field notices)."
    )
    raise SystemExit(1 if status == IngestionStatus.FAILED else 0)


if __name__ == "__main__":
    main()
