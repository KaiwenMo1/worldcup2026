"""Manual-first injury/news ingestion and transparent availability-risk derivation."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ingestion.normalizers import make_data_quality_issue, safe_read_csv, safe_write_csv, validate_rows
from app.ingestion.schemas import DataQualityIssue, DataQualitySeverity


ROOT = Path(__file__).resolve().parents[2]
MANUAL_INJURY_NEWS_SAMPLE_PATH = ROOT / "data" / "raw" / "injury_news" / "manual_injury_news_sample.csv"
INJURY_NEWS_NORMALIZED_PATH = ROOT / "data" / "normalized" / "injury_news_normalized.csv"
INJURY_RISK_SIGNALS_PATH = ROOT / "data" / "derived" / "injury_risk_signals.csv"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value


class AvailabilityStatus(StrEnum):
    FIT = "fit"
    MINOR_DOUBT = "minor_doubt"
    MAJOR_DOUBT = "major_doubt"
    INJURED = "injured"
    SUSPENDED = "suspended"
    RESTED = "rested"
    MINUTES_LIMITED = "minutes_limited"
    UNKNOWN = "unknown"


STATUS_BASELINES: dict[AvailabilityStatus, tuple[float, int]] = {
    AvailabilityStatus.FIT: (1.0, 90),
    AvailabilityStatus.MINOR_DOUBT: (0.75, 65),
    AvailabilityStatus.MAJOR_DOUBT: (0.35, 30),
    AvailabilityStatus.INJURED: (0.02, 0),
    AvailabilityStatus.SUSPENDED: (0.0, 0),
    AvailabilityStatus.RESTED: (0.15, 10),
    AvailabilityStatus.MINUTES_LIMITED: (0.8, 45),
    AvailabilityStatus.UNKNOWN: (0.5, 45),
}

STATUS_ALIASES: dict[str, AvailabilityStatus] = {
    "available": AvailabilityStatus.FIT,
    "cleared": AvailabilityStatus.FIT,
    "fit": AvailabilityStatus.FIT,
    "full training": AvailabilityStatus.FIT,
    "minor doubt": AvailabilityStatus.MINOR_DOUBT,
    "minor injury": AvailabilityStatus.MINOR_DOUBT,
    "knock": AvailabilityStatus.MINOR_DOUBT,
    "questionable": AvailabilityStatus.MINOR_DOUBT,
    "doubtful": AvailabilityStatus.MAJOR_DOUBT,
    "major doubt": AvailabilityStatus.MAJOR_DOUBT,
    "very doubtful": AvailabilityStatus.MAJOR_DOUBT,
    "injured": AvailabilityStatus.INJURED,
    "injury": AvailabilityStatus.INJURED,
    "out": AvailabilityStatus.INJURED,
    "unavailable": AvailabilityStatus.INJURED,
    "suspended": AvailabilityStatus.SUSPENDED,
    "suspension": AvailabilityStatus.SUSPENDED,
    "rested": AvailabilityStatus.RESTED,
    "rest": AvailabilityStatus.RESTED,
    "rotation rest": AvailabilityStatus.RESTED,
    "limited": AvailabilityStatus.MINUTES_LIMITED,
    "minutes limited": AvailabilityStatus.MINUTES_LIMITED,
    "restricted": AvailabilityStatus.MINUTES_LIMITED,
    "unknown": AvailabilityStatus.UNKNOWN,
}


class InjuryNewsRecord(StrictModel):
    evidence_id: str = Field(min_length=1)
    match_id: str | None = None
    player_id: str = Field(min_length=1)
    player: str = Field(min_length=1)
    team: str = Field(min_length=1)
    reported_status: str = Field(min_length=1)
    status: AvailabilityStatus
    detail: str = ""
    expected_return: date | None = None
    availability_probability: float = Field(ge=0, le=1)
    expected_minutes: int = Field(ge=0, le=130)
    source: str = Field(min_length=1)
    source_confidence: float = Field(ge=0, le=1)
    reported_at: datetime
    data_quality: str = Field(min_length=1)

    _reported_at_aware = field_validator("reported_at")(_aware)


class InjuryRiskSignal(StrictModel):
    match_id: str | None = None
    player_id: str = Field(min_length=1)
    player: str = Field(min_length=1)
    team: str = Field(min_length=1)
    status: AvailabilityStatus
    availability_probability: float = Field(ge=0, le=1)
    expected_minutes: int = Field(ge=0, le=130)
    risk_score: float = Field(ge=0, le=1)
    source_confidence: float = Field(ge=0, le=1)
    evidence_count: int = Field(ge=1)
    sources: str = Field(min_length=1)
    conflicting_statuses: str = ""
    needs_manual_review: bool = False
    reason: str = Field(min_length=1)
    data_quality: str = Field(min_length=1)
    updated_at: datetime

    _updated_at_aware = field_validator("updated_at")(_aware)


INJURY_NEWS_FIELDS = list(InjuryNewsRecord.model_fields)
INJURY_RISK_FIELDS = list(InjuryRiskSignal.model_fields)
RAW_REQUIRED_FIELDS = {"player", "team", "reported_status", "source", "reported_at"}


@dataclass
class InjuryNewsIngestionResult:
    records: list[InjuryNewsRecord] = field(default_factory=list)
    issues: list[DataQualityIssue] = field(default_factory=list)
    rows_raw: int = 0


class InjuryNewsAdapter(Protocol):
    name: str

    def fetch(self) -> tuple[list[dict[str, str]], list[DataQualityIssue]]:
        ...

    def normalize(self, raw_rows: list[dict[str, str]]) -> InjuryNewsIngestionResult:
        ...


def player_id_for(team: str, player: str) -> str:
    raw = unicodedata.normalize("NFKD", f"{team}_{player}").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", raw.casefold()).strip("_")


def normalize_availability_status(value: str) -> AvailabilityStatus:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    if normalized in STATUS_ALIASES:
        return STATUS_ALIASES[normalized]
    if "suspend" in normalized or "suspens" in normalized:
        return AvailabilityStatus.SUSPENDED
    if any(token in normalized for token in ("injur", "ruled out", "unavailable")):
        return AvailabilityStatus.INJURED
    if any(token in normalized for token in ("major doubt", "very doubtful", "unlikely")):
        return AvailabilityStatus.MAJOR_DOUBT
    if any(token in normalized for token in ("minor doubt", "questionable", "knock")):
        return AvailabilityStatus.MINOR_DOUBT
    if any(token in normalized for token in ("limited", "restricted")):
        return AvailabilityStatus.MINUTES_LIMITED
    if "rest" in normalized:
        return AvailabilityStatus.RESTED
    if any(token in normalized for token in ("fit", "available", "cleared", "training")):
        return AvailabilityStatus.FIT
    return AvailabilityStatus.UNKNOWN


def compute_availability(status: AvailabilityStatus, source_confidence: float) -> tuple[float, int]:
    """Estimate availability while shrinking low-confidence reports toward uncertainty."""
    baseline_probability, baseline_minutes = STATUS_BASELINES[status]
    confidence = max(0.0, min(1.0, source_confidence))
    probability = 0.5 + confidence * (baseline_probability - 0.5)
    minutes = round(45 + confidence * (baseline_minutes - 45))
    return round(max(0.0, min(1.0, probability)), 3), max(0, min(130, minutes))


def _stable_evidence_id(row: dict[str, Any]) -> str:
    identity = "|".join(
        str(row.get(field, "")).strip()
        for field in ("match_id", "team", "player_id", "player", "reported_status", "source", "reported_at")
    )
    return f"injury_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}"


def _compact(row: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    return {field: row[field] for field in fields if row.get(field) not in {None, ""}}


class ManualCsvInjuryNewsAdapter:
    name = "manual_csv"

    def __init__(self, path: Path, source_confidence: float = 0.7):
        self.path = path
        self.source_confidence = source_confidence

    def fetch(self) -> tuple[list[dict[str, str]], list[DataQualityIssue]]:
        result = safe_read_csv(self.path, RAW_REQUIRED_FIELDS)
        return result.rows, result.issues

    def normalize(self, raw_rows: list[dict[str, str]]) -> InjuryNewsIngestionResult:
        result = InjuryNewsIngestionResult(rows_raw=len(raw_rows))
        for row_number, row in enumerate(raw_rows, start=2):
            try:
                confidence = float(row.get("source_confidence") or self.source_confidence)
            except (TypeError, ValueError):
                confidence = -1
            status = normalize_availability_status(row.get("reported_status", ""))
            availability, minutes = compute_availability(status, confidence)
            payload = _compact(row, INJURY_NEWS_FIELDS)
            payload.update(
                {
                    "evidence_id": row.get("evidence_id") or _stable_evidence_id(row),
                    "player_id": row.get("player_id") or player_id_for(row.get("team", ""), row.get("player", "")),
                    "status": status,
                    "availability_probability": availability,
                    "expected_minutes": minutes,
                    "source_confidence": confidence,
                    "data_quality": "manual_evidence",
                }
            )
            if not row.get("match_id"):
                payload["match_id"] = None
            if not row.get("expected_return"):
                payload["expected_return"] = None
            validated = validate_rows([payload], InjuryNewsRecord, file=self.path, starting_row_number=row_number)
            result.issues.extend(validated.issues)
            result.records.extend(validated.valid_records)
        return result


def ingest_injury_news(adapter: InjuryNewsAdapter) -> InjuryNewsIngestionResult:
    rows, read_issues = adapter.fetch()
    result = adapter.normalize(rows)
    result.issues = [*read_issues, *result.issues]
    return result


def _row(model: BaseModel, fields: list[str]) -> dict[str, Any]:
    payload = model.model_dump(mode="json")
    return {field: "" if payload.get(field) is None else payload.get(field, "") for field in fields}


def write_normalized_injury_news(
    records: list[InjuryNewsRecord],
    path: Path = INJURY_NEWS_NORMALIZED_PATH,
) -> list[DataQualityIssue]:
    return safe_write_csv(path, [_row(item, INJURY_NEWS_FIELDS) for item in records], INJURY_NEWS_FIELDS).issues


def load_normalized_injury_news(
    path: Path = INJURY_NEWS_NORMALIZED_PATH,
) -> tuple[list[InjuryNewsRecord], list[DataQualityIssue]]:
    read = safe_read_csv(path, INJURY_NEWS_FIELDS)
    rows = [
        {
            **row,
            "match_id": row.get("match_id") or None,
            "expected_return": row.get("expected_return") or None,
        }
        for row in read.rows
    ]
    validated = validate_rows(rows, InjuryNewsRecord, file=path)
    return validated.valid_records, [*read.issues, *validated.issues]


def _meaningful_statuses(records: list[InjuryNewsRecord]) -> set[AvailabilityStatus]:
    return {record.status for record in records if record.status != AvailabilityStatus.UNKNOWN}


def build_injury_risk_signals(
    records: list[InjuryNewsRecord],
    *,
    updated_at: datetime | None = None,
) -> list[InjuryRiskSignal]:
    """Consolidate evidence without hiding conflicts between meaningful statuses."""
    updated = updated_at or datetime.now(timezone.utc)
    grouped: defaultdict[tuple[str | None, str, str], list[InjuryNewsRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.match_id, record.team.casefold(), record.player_id)].append(record)

    signals = []
    for (match_id, _, player_id), evidence in grouped.items():
        ordered = sorted(evidence, key=lambda item: (item.source_confidence, item.reported_at), reverse=True)
        chosen = ordered[0]
        confidence_total = sum(max(item.source_confidence, 0.01) for item in evidence)
        availability = sum(item.availability_probability * max(item.source_confidence, 0.01) for item in evidence) / confidence_total
        minutes = sum(item.expected_minutes * max(item.source_confidence, 0.01) for item in evidence) / confidence_total
        meaningful = _meaningful_statuses(evidence)
        conflicts = sorted(status.value for status in meaningful) if len(meaningful) > 1 else []
        needs_review = bool(conflicts)
        confidence = mean(item.source_confidence for item in evidence)
        sources = sorted({item.source for item in evidence})
        reason = f"{len(evidence)} report(s); highest-confidence status is {chosen.status.value}."
        if conflicts:
            reason += f" Conflicting statuses require review: {', '.join(conflicts)}."
        signals.append(
            InjuryRiskSignal(
                match_id=match_id,
                player_id=player_id,
                player=chosen.player,
                team=chosen.team,
                status=chosen.status,
                availability_probability=round(availability, 3),
                expected_minutes=round(minutes),
                risk_score=round((1 - availability) * max(confidence, 0.35), 3),
                source_confidence=round(confidence, 3),
                evidence_count=len(evidence),
                sources="|".join(sources),
                conflicting_statuses="|".join(conflicts),
                needs_manual_review=needs_review,
                reason=reason,
                data_quality="conflicting_manual_evidence" if needs_review else "consolidated_manual_evidence",
                updated_at=updated,
            )
        )
    return sorted(signals, key=lambda item: (item.team, -item.risk_score, item.player))


def write_injury_risk_signals(
    signals: list[InjuryRiskSignal],
    path: Path = INJURY_RISK_SIGNALS_PATH,
) -> list[DataQualityIssue]:
    return safe_write_csv(path, [_row(item, INJURY_RISK_FIELDS) for item in signals], INJURY_RISK_FIELDS).issues


def load_injury_risk_signals(
    path: Path = INJURY_RISK_SIGNALS_PATH,
) -> tuple[list[InjuryRiskSignal], list[DataQualityIssue]]:
    read = safe_read_csv(path, INJURY_RISK_FIELDS)
    rows = [{**row, "match_id": row.get("match_id") or None} for row in read.rows]
    validated = validate_rows(rows, InjuryRiskSignal, file=path)
    return validated.valid_records, [*read.issues, *validated.issues]


def get_team_injury_risk_signals(
    team: str,
    match_id: str | None = None,
    *,
    path: Path = INJURY_RISK_SIGNALS_PATH,
) -> list[InjuryRiskSignal]:
    """Return match-specific signals plus global fallbacks for a tactical brief."""
    signals, _ = load_injury_risk_signals(path)
    team_signals = [signal for signal in signals if signal.team.casefold() == team.casefold()]
    if not team_signals:
        return []
    by_player: dict[str, InjuryRiskSignal] = {}
    for signal in team_signals:
        if signal.match_id is None:
            by_player[signal.player_id] = signal
    if match_id is not None:
        for signal in team_signals:
            if signal.match_id == match_id:
                by_player[signal.player_id] = signal
    elif not by_player:
        for signal in team_signals:
            by_player.setdefault(signal.player_id, signal)
    return sorted(by_player.values(), key=lambda item: item.risk_score, reverse=True)


def conflict_quality_issues(
    signals: list[InjuryRiskSignal],
    *,
    file: Path = INJURY_RISK_SIGNALS_PATH,
) -> list[DataQualityIssue]:
    """Represent conflicting reports in the shared quality log without dropping them."""
    return [
        make_data_quality_issue(
            file=file,
            severity=DataQualitySeverity.WARNING,
            field_name="status",
            problem=f"Conflicting injury/news statuses for {signal.player} ({signal.team})",
            raw_value=signal.conflicting_statuses,
            suggested_fix="Review the cited sources and add a newer, higher-confidence report.",
        )
        for signal in signals
        if signal.needs_manual_review
    ]
