#!/usr/bin/env python3
"""Ingest manual player statistics into provider-independent normalized files."""

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
    ManualCsvPlayerStatsAdapter,
    append_data_quality_issues,
    append_ingestion_run,
    create_ingestion_run,
    get_source,
    ingest_player_stats,
    write_normalized_stats,
)
from app.ingestion.player_stats_ingestion import MANUAL_SAMPLE_PATH, MATCH_STATS_PATH, SEASON_STATS_PATH  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest player stats using a manual CSV adapter.")
    parser.add_argument("--source", default="manual_csv")
    parser.add_argument("--input", type=Path, default=MANUAL_SAMPLE_PATH)
    parser.add_argument("--season-output", type=Path, default=SEASON_STATS_PATH)
    parser.add_argument("--match-output", type=Path, default=MATCH_STATS_PATH)
    args = parser.parse_args()

    source = get_source(args.source)
    if source is None:
        raise SystemExit(f"Unknown source_id {args.source!r}; register it in data/provenance/source_registry.csv.")
    if not source.enabled:
        raise SystemExit(f"Source {args.source!r} is disabled.")
    started = datetime.now(timezone.utc)
    result = ingest_player_stats(ManualCsvPlayerStatsAdapter(args.input, source.reliability_score))
    write_issues = write_normalized_stats(result, args.season_output, args.match_output)
    all_issues = [*result.issues, *write_issues]
    normalized = len(result.season_stats) + len(result.match_stats)
    failed_rows = max(0, result.rows_raw - normalized)
    critical = any(issue.severity.value == "critical" for issue in all_issues)
    status = IngestionStatus.FAILED if critical or (result.rows_raw > 0 and normalized == 0) else IngestionStatus.PARTIAL if all_issues else IngestionStatus.SUCCEEDED
    run = create_ingestion_run(
        source_id=source.source_id,
        script="scripts/ingest_player_stats.py",
        status=status,
        rows_raw=result.rows_raw,
        rows_normalized=normalized,
        rows_failed=failed_rows,
        error_message="Player-stat ingestion failed validation." if status == IngestionStatus.FAILED else None,
        started_at=started,
        finished_at=datetime.now(timezone.utc),
    )
    append_ingestion_run(run)
    if all_issues:
        append_data_quality_issues([issue.model_copy(update={"run_id": run.run_id}) for issue in all_issues])
    print(
        f"Ingested {len(result.season_stats)} season rows and {len(result.match_stats)} match rows "
        f"from {result.rows_raw} raw rows ({len(all_issues)} issues)."
    )
    raise SystemExit(1 if status == IngestionStatus.FAILED else 0)


if __name__ == "__main__":
    main()
