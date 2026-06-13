"""Load manually curated manager evidence from structured CSV and Markdown."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.ingestion import DataQualityIssue, DataQualitySeverity, make_data_quality_issue, safe_read_csv, validate_rows
from app.manager_distillation.schemas import EvidenceCategory, EvidenceDocument, EvidenceRecord


EVIDENCE_FIELDS = {
    "evidence_id",
    "manager_id",
    "category",
    "source_id",
    "title",
    "claim_id",
    "claim_type",
    "claim_text",
    "reliability_score",
    "predictive_power",
    "distinctive",
}
OPTIONAL_FIELDS = [
    "url",
    "observed_at",
    "match_id",
    "normalized_value",
    "condition_code",
    "parameters_json",
    "match_state",
    "minute_window",
    "notes",
]


@dataclass
class EvidenceLoadResult:
    records: list[EvidenceRecord] = field(default_factory=list)
    documents: list[EvidenceDocument] = field(default_factory=list)
    issues: list[DataQualityIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity in {DataQualitySeverity.ERROR, DataQualitySeverity.CRITICAL} for issue in self.issues)


def _optional(value: str | None) -> str | None:
    return value or None


def _bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").casefold() in {"1", "true", "yes", "y"}


def _payload(row: dict[str, str], path: Path, row_number: int) -> tuple[dict[str, Any] | None, DataQualityIssue | None]:
    try:
        parameters = json.loads(row.get("parameters_json") or "{}")
        if not isinstance(parameters, dict):
            raise ValueError("parameters_json must decode to an object")
    except (json.JSONDecodeError, ValueError) as exc:
        return None, make_data_quality_issue(
            file=path,
            row_number=row_number,
            severity=DataQualitySeverity.ERROR,
            field_name="parameters_json",
            problem=str(exc),
            raw_value=row.get("parameters_json"),
            suggested_fix="Use a JSON object such as {\"minute\": 60}.",
        )
    return (
        {
            **{key: value for key, value in row.items() if key != "parameters_json"},
            **{field: _optional(row.get(field)) for field in OPTIONAL_FIELDS if field != "parameters_json"},
            "parameters": parameters,
            "predictive_power": _bool(row.get("predictive_power")),
            "distinctive": _bool(row.get("distinctive")),
        },
        None,
    )


def load_csv_evidence(path: Path, manager_id: str | None = None) -> EvidenceLoadResult:
    read_result = safe_read_csv(path, EVIDENCE_FIELDS)
    payloads = []
    issues = list(read_result.issues)
    for row_number, row in enumerate(read_result.rows, start=2):
        payload, issue = _payload(row, path, row_number)
        if issue:
            issues.append(issue)
        elif payload is not None and (manager_id is None or payload.get("manager_id") == manager_id):
            payloads.append(payload)
    validated = validate_rows(payloads, EvidenceRecord, file=path)
    return EvidenceLoadResult(records=validated.valid_records, issues=[*issues, *validated.issues])


def _category_for_markdown(path: Path) -> EvidenceCategory:
    names = {part.casefold() for part in path.parts}
    for category in EvidenceCategory:
        if category.value in names or path.stem.casefold().startswith(category.value):
            return category
    return EvidenceCategory.EXTERNAL_VIEWS


def load_markdown_document(path: Path) -> EvidenceDocument | None:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return None
    heading = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    document_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", path.stem).strip("_") or "evidence_document"
    return EvidenceDocument(
        document_id=document_id,
        category=_category_for_markdown(path),
        title=heading.group(1).strip() if heading else path.stem.replace("_", " ").replace("-", " ").title(),
        path=str(path),
        content=content,
    )


def load_evidence_directory(path: Path, manager_id: str | None = None) -> EvidenceLoadResult:
    result = EvidenceLoadResult()
    if not path.exists():
        result.issues.append(
            make_data_quality_issue(
                file=path,
                severity=DataQualitySeverity.CRITICAL,
                problem="Evidence directory does not exist",
                suggested_fix="Create the evidence directory and add structured CSV evidence.",
            )
        )
        return result
    for csv_path in sorted(path.rglob("*.csv")):
        loaded = load_csv_evidence(csv_path, manager_id)
        result.records.extend(loaded.records)
        result.issues.extend(loaded.issues)
    for markdown_path in sorted(path.rglob("*.md")):
        if markdown_path.name.casefold() == "readme.md":
            continue
        try:
            document = load_markdown_document(markdown_path)
            if document:
                result.documents.append(document)
        except OSError as exc:
            result.issues.append(
                make_data_quality_issue(
                    file=markdown_path,
                    severity=DataQualitySeverity.WARNING,
                    problem=f"Markdown evidence could not be read: {exc}",
                )
            )
    return result
