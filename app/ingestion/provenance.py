"""Append-only ingestion run and data-quality audit helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from app.ingestion.normalizers import (
    CsvWriteResult,
    ValidationResult,
    blank_to_none,
    safe_read_csv,
    safe_write_csv,
    validate_rows,
)
from app.ingestion.schemas import DataQualityIssue, DataQualitySeverity, IngestionRun, IngestionStatus


ROOT = Path(__file__).resolve().parents[2]
INGESTION_RUNS_PATH = ROOT / "data" / "provenance" / "ingestion_runs.csv"
DATA_QUALITY_REPORT_PATH = ROOT / "data" / "provenance" / "data_quality_report.csv"
INGESTION_RUN_FIELDS = [
    "run_id",
    "source_id",
    "script",
    "started_at",
    "finished_at",
    "status",
    "rows_raw",
    "rows_normalized",
    "rows_failed",
    "error_message",
]
DATA_QUALITY_FIELDS = [
    "issue_id",
    "run_id",
    "file",
    "row_number",
    "severity",
    "field",
    "problem",
    "raw_value",
    "suggested_fix",
    "created_at",
]


def _csv_row(model: IngestionRun | DataQualityIssue, fields: list[str]) -> dict[str, Any]:
    row = model.model_dump(mode="json")
    return {field: "" if row.get(field) is None else row.get(field) for field in fields}


def create_ingestion_run(
    *,
    source_id: str,
    script: str,
    status: IngestionStatus | str,
    rows_raw: int = 0,
    rows_normalized: int = 0,
    rows_failed: int = 0,
    error_message: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    run_id: str | None = None,
) -> IngestionRun:
    now = datetime.now(timezone.utc)
    return IngestionRun(
        run_id=run_id or uuid4().hex,
        source_id=source_id,
        script=script,
        started_at=started_at or now,
        finished_at=finished_at or now,
        status=status,
        rows_raw=rows_raw,
        rows_normalized=rows_normalized,
        rows_failed=rows_failed,
        error_message=error_message,
    )


def append_ingestion_run(
    run: IngestionRun,
    path: Path = INGESTION_RUNS_PATH,
) -> CsvWriteResult:
    return safe_write_csv(path, [_csv_row(run, INGESTION_RUN_FIELDS)], INGESTION_RUN_FIELDS, append=True, run_id=run.run_id)


def append_data_quality_issues(
    issues: Iterable[DataQualityIssue],
    path: Path = DATA_QUALITY_REPORT_PATH,
) -> CsvWriteResult:
    materialized = list(issues)
    return safe_write_csv(
        path,
        [_csv_row(issue, DATA_QUALITY_FIELDS) for issue in materialized],
        DATA_QUALITY_FIELDS,
        append=True,
    )


def load_ingestion_runs(path: Path = INGESTION_RUNS_PATH) -> ValidationResult[IngestionRun]:
    read_result = safe_read_csv(path, INGESTION_RUN_FIELDS)
    rows = [
        {
            **row,
            "error_message": blank_to_none(row.get("error_message", "")),
        }
        for row in read_result.rows
    ]
    validated = validate_rows(rows, IngestionRun, file=path)
    return ValidationResult(valid_records=validated.valid_records, issues=[*read_result.issues, *validated.issues])


def load_data_quality_issues(path: Path = DATA_QUALITY_REPORT_PATH) -> ValidationResult[DataQualityIssue]:
    read_result = safe_read_csv(path, DATA_QUALITY_FIELDS)
    rows = [
        {
            **row,
            "run_id": blank_to_none(row.get("run_id", "")),
            "row_number": blank_to_none(row.get("row_number", "")),
            "field": blank_to_none(row.get("field", "")),
            "raw_value": blank_to_none(row.get("raw_value", "")),
            "suggested_fix": blank_to_none(row.get("suggested_fix", "")),
        }
        for row in read_result.rows
    ]
    validated = validate_rows(rows, DataQualityIssue, file=path)
    return ValidationResult(valid_records=validated.valid_records, issues=[*read_result.issues, *validated.issues])


def critical_issues(issues: Iterable[DataQualityIssue]) -> list[DataQualityIssue]:
    return [issue for issue in issues if issue.severity == DataQualitySeverity.CRITICAL]
