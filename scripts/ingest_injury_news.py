#!/usr/bin/env python3
"""Ingest manual injury/news evidence and build reviewable risk signals."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingestion import (  # noqa: E402
    INJURY_NEWS_NORMALIZED_PATH,
    INJURY_RISK_SIGNALS_PATH,
    MANUAL_INJURY_NEWS_SAMPLE_PATH,
    IngestionStatus,
    ManualCsvInjuryNewsAdapter,
    append_data_quality_issues,
    append_ingestion_run,
    build_injury_risk_signals,
    conflict_quality_issues,
    create_ingestion_run,
    get_source,
    ingest_injury_news,
    write_injury_risk_signals,
    write_normalized_injury_news,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest injury/news evidence using a manual CSV adapter.")
    parser.add_argument("--source", default="manual_csv")
    parser.add_argument("--input", type=Path, default=MANUAL_INJURY_NEWS_SAMPLE_PATH)
    parser.add_argument("--normalized-output", type=Path, default=INJURY_NEWS_NORMALIZED_PATH)
    parser.add_argument("--risk-output", type=Path, default=INJURY_RISK_SIGNALS_PATH)
    args = parser.parse_args()

    source = get_source(args.source)
    if source is None:
        raise SystemExit(f"Unknown source_id {args.source!r}; register it in data/provenance/source_registry.csv.")
    if not source.enabled:
        raise SystemExit(f"Source {args.source!r} is disabled.")

    started = datetime.now(timezone.utc)
    result = ingest_injury_news(ManualCsvInjuryNewsAdapter(args.input, source.reliability_score))
    signals = build_injury_risk_signals(result.records)
    write_issues = [
        *write_normalized_injury_news(result.records, args.normalized_output),
        *write_injury_risk_signals(signals, args.risk_output),
    ]
    conflicts = conflict_quality_issues(signals, file=args.risk_output)
    all_issues = [*result.issues, *write_issues, *conflicts]
    normalized = len(result.records)
    failed_rows = max(0, result.rows_raw - normalized)
    critical = any(issue.severity.value == "critical" for issue in all_issues)
    status = (
        IngestionStatus.FAILED
        if critical or (result.rows_raw > 0 and normalized == 0)
        else IngestionStatus.PARTIAL
        if all_issues
        else IngestionStatus.SUCCEEDED
    )
    run = create_ingestion_run(
        source_id=source.source_id,
        script="scripts/ingest_injury_news.py",
        status=status,
        rows_raw=result.rows_raw,
        rows_normalized=normalized,
        rows_failed=failed_rows,
        error_message="Injury/news ingestion failed validation." if status == IngestionStatus.FAILED else None,
        started_at=started,
        finished_at=datetime.now(timezone.utc),
    )
    append_ingestion_run(run)
    if all_issues:
        append_data_quality_issues([issue.model_copy(update={"run_id": run.run_id}) for issue in all_issues])
    print(
        f"Ingested {normalized} injury/news rows into {len(signals)} risk signals "
        f"({len(conflicts)} conflicts requiring review, {failed_rows} rejected rows)."
    )
    raise SystemExit(1 if status == IngestionStatus.FAILED else 0)


if __name__ == "__main__":
    main()
