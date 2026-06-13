"""Typed contracts shared by future ingestion pipelines."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceType(StrEnum):
    MANUAL_CSV = "manual_csv"
    PROJECT_FILE = "project_file"
    PUBLIC_DATASET = "public_dataset"
    API = "api"
    WEB = "web"
    OTHER = "other"


class IngestionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class DataQualitySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


def _timezone_aware(value: datetime | None, field_name: str) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field_name} must include a timezone")
    return value


class SourceRecord(StrictModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    source_name: str = Field(min_length=1)
    source_type: SourceType
    reliability_score: float = Field(ge=0, le=1)
    requires_api_key: bool = False
    terms_note: str | None = None
    enabled: bool = True
    last_checked: datetime | None = None
    notes: str | None = None

    @field_validator("last_checked")
    @classmethod
    def validate_last_checked(cls, value: datetime | None) -> datetime | None:
        return _timezone_aware(value, "last_checked")


class IngestionRun(StrictModel):
    run_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    script: str = Field(min_length=1)
    started_at: datetime
    finished_at: datetime
    status: IngestionStatus
    rows_raw: int = Field(default=0, ge=0)
    rows_normalized: int = Field(default=0, ge=0)
    rows_failed: int = Field(default=0, ge=0)
    error_message: str | None = None

    @field_validator("started_at", "finished_at")
    @classmethod
    def validate_timestamp(cls, value: datetime, info) -> datetime:
        return _timezone_aware(value, info.field_name)  # type: ignore[return-value]

    @model_validator(mode="after")
    def validate_run_consistency(self) -> "IngestionRun":
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must be at or after started_at")
        if self.rows_normalized + self.rows_failed > self.rows_raw:
            raise ValueError("rows_normalized plus rows_failed cannot exceed rows_raw")
        if self.status == IngestionStatus.FAILED and not self.error_message:
            raise ValueError("failed ingestion runs require error_message")
        return self


class DataQualityIssue(StrictModel):
    issue_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    run_id: str | None = None
    file: str = Field(min_length=1)
    row_number: int | None = Field(default=None, ge=1)
    severity: DataQualitySeverity
    field: str | None = None
    problem: str = Field(min_length=1)
    raw_value: str | None = None
    suggested_fix: str | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return _timezone_aware(value, "created_at")  # type: ignore[return-value]
