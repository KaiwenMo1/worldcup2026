"""Read and maintain the provider/source registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.ingestion.normalizers import (
    CsvWriteResult,
    ValidationResult,
    blank_to_none,
    make_data_quality_issue,
    safe_read_csv,
    safe_write_csv,
    validate_rows,
)
from app.ingestion.schemas import DataQualitySeverity, SourceRecord


ROOT = Path(__file__).resolve().parents[2]
SOURCE_REGISTRY_PATH = ROOT / "data" / "provenance" / "source_registry.csv"
SOURCE_FIELDS = [
    "source_id",
    "source_name",
    "source_type",
    "reliability_score",
    "requires_api_key",
    "terms_note",
    "enabled",
    "last_checked",
    "notes",
]


def _source_payload(row: dict[str, str]) -> dict[str, Any]:
    return {
        **row,
        "terms_note": blank_to_none(row.get("terms_note", "")),
        "last_checked": blank_to_none(row.get("last_checked", "")),
        "notes": blank_to_none(row.get("notes", "")),
    }


def _source_row(record: SourceRecord) -> dict[str, Any]:
    row = record.model_dump(mode="json")
    return {field: "" if row.get(field) is None else row.get(field) for field in SOURCE_FIELDS}


def load_source_registry(path: Path = SOURCE_REGISTRY_PATH) -> ValidationResult[SourceRecord]:
    read_result = safe_read_csv(path, SOURCE_FIELDS)
    validated = validate_rows((_source_payload(row) for row in read_result.rows), SourceRecord, file=path)
    unique = []
    seen = set()
    issues = [*read_result.issues, *validated.issues]
    for record in validated.valid_records:
        if record.source_id in seen:
            issues.append(
                make_data_quality_issue(
                    file=path,
                    severity=DataQualitySeverity.ERROR,
                    field_name="source_id",
                    problem=f"Duplicate source_id: {record.source_id}",
                    raw_value=record.source_id,
                    suggested_fix="Keep one authoritative registry row per source_id.",
                )
            )
            continue
        seen.add(record.source_id)
        unique.append(record)
    return ValidationResult(valid_records=unique, issues=issues)


def list_sources(*, enabled_only: bool = False, path: Path = SOURCE_REGISTRY_PATH) -> list[SourceRecord]:
    records = load_source_registry(path).valid_records
    return [record for record in records if record.enabled] if enabled_only else records


def get_source(source_id: str, path: Path = SOURCE_REGISTRY_PATH) -> SourceRecord | None:
    return next((record for record in list_sources(path=path) if record.source_id == source_id), None)


def upsert_source(
    record: SourceRecord,
    *,
    replace: bool = False,
    path: Path = SOURCE_REGISTRY_PATH,
) -> CsvWriteResult:
    """Atomically add a source, requiring replace=True for an existing source_id."""
    loaded = load_source_registry(path)
    blocking_issues = [
        issue
        for issue in loaded.issues
        if issue.severity in {DataQualitySeverity.ERROR, DataQualitySeverity.CRITICAL}
    ]
    if blocking_issues:
        return CsvWriteResult(issues=blocking_issues)
    records = {item.source_id: item for item in loaded.valid_records}
    if record.source_id in records and not replace:
        return CsvWriteResult(
            issues=[
                *loaded.issues,
                make_data_quality_issue(
                    file=path,
                    severity=DataQualitySeverity.ERROR,
                    field_name="source_id",
                    problem=f"Source {record.source_id!r} already exists",
                    raw_value=record.source_id,
                    suggested_fix="Pass replace=True only after reviewing the source metadata change.",
                ),
            ]
        )
    records[record.source_id] = record
    written = safe_write_csv(
        path,
        [_source_row(item) for item in sorted(records.values(), key=lambda item: item.source_id)],
        SOURCE_FIELDS,
    )
    written.issues = [*loaded.issues, *written.issues]
    return written
