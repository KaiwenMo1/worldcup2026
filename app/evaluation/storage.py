"""Idempotent CSV storage helpers for derived evaluation records."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from app.ingestion.normalizers import safe_read_csv, safe_write_csv, validate_rows
from app.ingestion.schemas import DataQualityIssue


ModelT = TypeVar("ModelT", bound=BaseModel)


def csv_row(model: BaseModel, fields: list[str]) -> dict[str, Any]:
    payload = model.model_dump(mode="json")
    return {field: "" if payload.get(field) is None else payload.get(field, "") for field in fields}


def load_records(path: Path, model: type[ModelT], fields: list[str]) -> tuple[list[ModelT], list[DataQualityIssue]]:
    read = safe_read_csv(path, fields)
    rows = [{key: (None if value == "" else value) for key, value in row.items()} for row in read.rows]
    validated = validate_rows(rows, model, file=path)
    return validated.valid_records, [*read.issues, *validated.issues]


def upsert_records(
    path: Path,
    records: list[ModelT],
    model: type[ModelT],
    fields: list[str],
    *,
    key: str = "evaluation_id",
) -> list[DataQualityIssue]:
    existing, issues = load_records(path, model, fields) if path.exists() else ([], [])
    if any(issue.severity.value in {"error", "critical"} for issue in issues):
        return issues
    by_key = {str(getattr(record, key)): record for record in existing}
    by_key.update({str(getattr(record, key)): record for record in records})
    ordered = sorted(by_key.values(), key=lambda record: str(getattr(record, key)))
    written = safe_write_csv(path, [csv_row(record, fields) for record in ordered], fields)
    return [*issues, *written.issues]
