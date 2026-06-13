#!/usr/bin/env python3
"""Smoke-test the shared ingestion foundation without touching project data."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingestion import (
    DataQualitySeverity,
    IngestionStatus,
    SourceRecord,
    SourceType,
    append_data_quality_issues,
    append_ingestion_run,
    create_ingestion_run,
    load_data_quality_issues,
    load_ingestion_runs,
    load_source_registry,
    make_data_quality_issue,
    upsert_source,
)  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        registry_path = root / "source_registry.csv"
        runs_path = root / "ingestion_runs.csv"
        quality_path = root / "data_quality_report.csv"

        source = SourceRecord(
            source_id="manual_smoke",
            source_name="Manual smoke source",
            source_type=SourceType.MANUAL_CSV,
            reliability_score=0.7,
            requires_api_key=False,
            enabled=True,
        )
        assert upsert_source(source, path=registry_path).ok

        run = create_ingestion_run(
            source_id=source.source_id,
            script="scripts/test_ingestion_foundation.py",
            status=IngestionStatus.PARTIAL,
            rows_raw=2,
            rows_normalized=1,
            rows_failed=1,
        )
        assert append_ingestion_run(run, runs_path).ok
        issue = make_data_quality_issue(
            file="smoke.csv",
            run_id=run.run_id,
            row_number=3,
            severity=DataQualitySeverity.ERROR,
            field_name="player_id",
            problem="player_id is missing",
        )
        assert append_data_quality_issues([issue], quality_path).ok

        assert len(load_source_registry(registry_path).valid_records) == 1
        assert len(load_ingestion_runs(runs_path).valid_records) == 1
        assert len(load_data_quality_issues(quality_path).valid_records) == 1
        print("Ingestion foundation smoke test passed: registry=1, runs=1, quality_issues=1")


if __name__ == "__main__":
    main()
