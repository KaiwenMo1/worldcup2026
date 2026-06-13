"""Non-throwing CSV and typed-row normalization helpers."""

from __future__ import annotations

import csv
import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generic, Iterable, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from app.ingestion.schemas import DataQualityIssue, DataQualitySeverity


ModelT = TypeVar("ModelT", bound=BaseModel)
_WRITE_LOCK = threading.Lock()


@dataclass
class CsvReadResult:
    rows: list[dict[str, str]] = field(default_factory=list)
    issues: list[DataQualityIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity in {DataQualitySeverity.ERROR, DataQualitySeverity.CRITICAL} for issue in self.issues)


@dataclass
class CsvWriteResult:
    rows_written: int = 0
    issues: list[DataQualityIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity in {DataQualitySeverity.ERROR, DataQualitySeverity.CRITICAL} for issue in self.issues)


@dataclass
class ValidationResult(Generic[ModelT]):
    valid_records: list[ModelT] = field(default_factory=list)
    issues: list[DataQualityIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity in {DataQualitySeverity.ERROR, DataQualitySeverity.CRITICAL} for issue in self.issues)


def blank_to_none(value: Any) -> Any:
    return None if value == "" else value


def _raw_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, default=str)
    except (TypeError, ValueError):
        return repr(value)


def make_data_quality_issue(
    *,
    file: str | Path,
    severity: DataQualitySeverity | str,
    problem: str,
    run_id: str | None = None,
    row_number: int | None = None,
    field_name: str | None = None,
    raw_value: Any = None,
    suggested_fix: str | None = None,
    created_at: datetime | None = None,
) -> DataQualityIssue:
    return DataQualityIssue(
        issue_id=uuid4().hex,
        run_id=run_id,
        file=str(file),
        row_number=row_number,
        severity=severity,
        field=field_name,
        problem=problem,
        raw_value=None if raw_value is None else _raw_text(raw_value),
        suggested_fix=suggested_fix,
        created_at=created_at or datetime.now(timezone.utc),
    )


def safe_read_csv(
    path: Path,
    required_fields: Iterable[str] | None = None,
    *,
    run_id: str | None = None,
) -> CsvReadResult:
    """Read CSV rows while returning storage/schema problems as structured issues."""
    required = set(required_fields or [])
    if not path.exists():
        return CsvReadResult(
            issues=[
                make_data_quality_issue(
                    file=path,
                    run_id=run_id,
                    severity=DataQualitySeverity.WARNING,
                    problem="CSV file does not exist",
                    suggested_fix="Create the file with the expected header before ingestion.",
                )
            ]
        )

    rows: list[dict[str, str]] = []
    issues: list[DataQualityIssue] = []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            if not fieldnames:
                return CsvReadResult(
                    issues=[
                        make_data_quality_issue(
                            file=path,
                            run_id=run_id,
                            severity=DataQualitySeverity.CRITICAL,
                            problem="CSV file has no header",
                            suggested_fix="Add the expected CSV header.",
                        )
                    ]
                )
            missing = sorted(required - set(fieldnames))
            if missing:
                return CsvReadResult(
                    issues=[
                        make_data_quality_issue(
                            file=path,
                            run_id=run_id,
                            severity=DataQualitySeverity.CRITICAL,
                            problem=f"CSV header is missing required fields: {', '.join(missing)}",
                            raw_value=fieldnames,
                            suggested_fix="Add the missing fields before ingestion.",
                        )
                    ]
                )
            for row_number, row in enumerate(reader, start=2):
                extra_values = row.pop(None, None)
                if extra_values:
                    issues.append(
                        make_data_quality_issue(
                            file=path,
                            run_id=run_id,
                            row_number=row_number,
                            severity=DataQualitySeverity.WARNING,
                            problem="CSV row contains more values than the header",
                            raw_value=extra_values,
                            suggested_fix="Align the row with the CSV header.",
                        )
                    )
                rows.append({str(key): value or "" for key, value in row.items()})
    except (OSError, csv.Error, UnicodeError) as exc:
        issues.append(
            make_data_quality_issue(
                file=path,
                run_id=run_id,
                severity=DataQualitySeverity.CRITICAL,
                problem=f"CSV file could not be read: {exc}",
                suggested_fix="Verify file permissions, UTF-8 encoding, and CSV syntax.",
            )
        )
    return CsvReadResult(rows=rows, issues=issues)


def _existing_header(path: Path) -> list[str] | None:
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle), None)


def safe_write_csv(
    path: Path,
    rows: Iterable[dict[str, Any]],
    fieldnames: Iterable[str],
    *,
    append: bool = False,
    run_id: str | None = None,
) -> CsvWriteResult:
    """Write CSV safely using atomic replacement or a schema-checked append."""
    fields = list(fieldnames)
    materialized = list(rows)
    if not fields:
        return CsvWriteResult(
            issues=[
                make_data_quality_issue(
                    file=path,
                    run_id=run_id,
                    severity=DataQualitySeverity.CRITICAL,
                    problem="Cannot write CSV without fieldnames",
                )
            ]
        )
    issues = []
    normalized_rows = []
    for row_number, row in enumerate(materialized, start=2):
        extras = sorted(set(row) - set(fields))
        if extras:
            issues.append(
                make_data_quality_issue(
                    file=path,
                    run_id=run_id,
                    row_number=row_number,
                    severity=DataQualitySeverity.WARNING,
                    problem=f"Fields outside the CSV contract were ignored: {', '.join(extras)}",
                    raw_value={key: row[key] for key in extras},
                )
            )
        normalized_rows.append({field: row.get(field, "") for field in fields})

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    with _WRITE_LOCK:
        try:
            if append:
                header = _existing_header(path)
                if header is not None and header != fields:
                    return CsvWriteResult(
                        issues=[
                            *issues,
                            make_data_quality_issue(
                                file=path,
                                run_id=run_id,
                                severity=DataQualitySeverity.CRITICAL,
                                problem="Existing CSV header does not match append contract",
                                raw_value=header,
                                suggested_fix="Migrate or replace the file before appending.",
                            ),
                        ]
                    )
                with path.open("a", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
                    if header is None:
                        writer.writeheader()
                    writer.writerows(normalized_rows)
                    handle.flush()
                    os.fsync(handle.fileno())
            else:
                with tempfile.NamedTemporaryFile(
                    "w",
                    newline="",
                    encoding="utf-8",
                    dir=path.parent,
                    delete=False,
                ) as handle:
                    temporary_path = Path(handle.name)
                    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(normalized_rows)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, path)
                temporary_path = None
        except (OSError, csv.Error, UnicodeError) as exc:
            issues.append(
                make_data_quality_issue(
                    file=path,
                    run_id=run_id,
                    severity=DataQualitySeverity.CRITICAL,
                    problem=f"CSV file could not be written: {exc}",
                    suggested_fix="Verify the destination path and CSV contract.",
                )
            )
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    return CsvWriteResult(rows_written=len(normalized_rows) if not any(issue.severity == DataQualitySeverity.CRITICAL for issue in issues) else 0, issues=issues)


def validate_rows(
    rows: Iterable[dict[str, Any]],
    model: type[ModelT],
    *,
    file: str | Path,
    run_id: str | None = None,
    starting_row_number: int = 2,
) -> ValidationResult[ModelT]:
    """Validate rows independently so one malformed row never stops the batch."""
    records: list[ModelT] = []
    issues: list[DataQualityIssue] = []
    for offset, row in enumerate(rows):
        row_number = starting_row_number + offset
        try:
            records.append(model.model_validate(row))
        except ValidationError as exc:
            for error in exc.errors():
                location = ".".join(str(item) for item in error.get("loc", ())) or None
                issues.append(
                    make_data_quality_issue(
                        file=file,
                        run_id=run_id,
                        row_number=row_number,
                        severity=DataQualitySeverity.ERROR,
                        field_name=location,
                        problem=error.get("msg", "row validation failed"),
                        raw_value=row.get(location) if location in row else row,
                        suggested_fix="Correct the field to satisfy the normalized schema.",
                    )
                )
        except Exception as exc:  # defensive boundary for future adapter rows
            issues.append(
                make_data_quality_issue(
                    file=file,
                    run_id=run_id,
                    row_number=row_number,
                    severity=DataQualitySeverity.ERROR,
                    problem=f"Unexpected row validation failure: {exc}",
                    raw_value=row,
                    suggested_fix="Inspect the adapter output before retrying ingestion.",
                )
            )
    return ValidationResult(valid_records=records, issues=issues)
