"""Manual tactical-evidence ingestion and reviewable manager-skill refinement."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ingestion.normalizers import make_data_quality_issue, safe_read_csv, safe_write_csv, validate_rows
from app.ingestion.schemas import DataQualityIssue, DataQualitySeverity
from app.tactics.schemas import EvidenceReference, ManagerSkill


ROOT = Path(__file__).resolve().parents[2]
MANUAL_TACTICAL_EVIDENCE_SAMPLE_PATH = ROOT / "data" / "raw" / "tactical_articles" / "manual_tactical_evidence_sample.csv"
TACTICAL_EVIDENCE_NORMALIZED_PATH = ROOT / "data" / "normalized" / "tactical_evidence_normalized.csv"
MANAGER_SKILL_UPDATES_PATH = ROOT / "data" / "derived" / "manager_skill_updates.csv"
MANAGER_SKILLS_DIR = ROOT / "data" / "manager_skills"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("timestamp must include a timezone")
    return value


class TacticalEvidenceType(StrEnum):
    TACTICAL_ARTICLE = "tactical_article"
    MATCH_REPORT = "match_report"
    PRESS_CONFERENCE = "press_conference"
    DECISION_RECORD = "decision_record"
    ANALYST_REPORT = "analyst_report"
    OTHER = "other"


class TacticalTopic(StrEnum):
    PRIMARY_STYLE = "primary_style"
    PREFERRED_FORMATION = "preferred_formation"
    BUILD_UP = "build_up"
    DEFENSIVE_SHAPE = "defensive_shape"
    PRESSING = "pressing"
    TRANSITION = "transition"
    SET_PIECES = "set_pieces"
    IN_POSSESSION = "in_possession"
    OUT_OF_POSSESSION = "out_of_possession"
    TRANSITION_ACTION = "transition_action"
    SET_PIECE_ACTION = "set_piece_action"
    OTHER = "other"


class ContentOrigin(StrEnum):
    MANUAL = "manual"
    LLM_ASSISTED = "llm_assisted"
    LLM_GENERATED = "llm_generated"
    UNKNOWN = "unknown"


class UpdateReviewStatus(StrEnum):
    READY_FOR_REVIEW = "ready_for_review"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    UNSUPPORTED_TARGET = "unsupported_target"


EVIDENCE_TYPE_ALIASES = {
    "article": TacticalEvidenceType.TACTICAL_ARTICLE,
    "tactical analysis": TacticalEvidenceType.TACTICAL_ARTICLE,
    "tactical article": TacticalEvidenceType.TACTICAL_ARTICLE,
    "match analysis": TacticalEvidenceType.MATCH_REPORT,
    "match report": TacticalEvidenceType.MATCH_REPORT,
    "post match report": TacticalEvidenceType.MATCH_REPORT,
    "press conference": TacticalEvidenceType.PRESS_CONFERENCE,
    "manager interview": TacticalEvidenceType.PRESS_CONFERENCE,
    "lineup decision": TacticalEvidenceType.DECISION_RECORD,
    "substitution record": TacticalEvidenceType.DECISION_RECORD,
    "decision record": TacticalEvidenceType.DECISION_RECORD,
    "analyst report": TacticalEvidenceType.ANALYST_REPORT,
}
TACTICAL_TOPIC_ALIASES = {
    "style": TacticalTopic.PRIMARY_STYLE,
    "tactical identity": TacticalTopic.PRIMARY_STYLE,
    "primary style": TacticalTopic.PRIMARY_STYLE,
    "formation": TacticalTopic.PREFERRED_FORMATION,
    "preferred formation": TacticalTopic.PREFERRED_FORMATION,
    "build up": TacticalTopic.BUILD_UP,
    "build-up": TacticalTopic.BUILD_UP,
    "defensive block": TacticalTopic.DEFENSIVE_SHAPE,
    "defensive shape": TacticalTopic.DEFENSIVE_SHAPE,
    "press": TacticalTopic.PRESSING,
    "pressing": TacticalTopic.PRESSING,
    "transition": TacticalTopic.TRANSITION,
    "set piece": TacticalTopic.SET_PIECES,
    "set pieces": TacticalTopic.SET_PIECES,
    "in possession": TacticalTopic.IN_POSSESSION,
    "out of possession": TacticalTopic.OUT_OF_POSSESSION,
    "transition action": TacticalTopic.TRANSITION_ACTION,
    "set piece action": TacticalTopic.SET_PIECE_ACTION,
}
SOURCE_KIND_BASE_QUALITY = {
    "official": 0.95,
    "direct_manager_quote": 0.9,
    "reputable_tactical_analysis": 0.82,
    "match_report": 0.76,
    "secondary_analysis": 0.62,
    "social_media": 0.35,
    "unknown": 0.45,
}
TOPIC_TARGETS: dict[TacticalTopic, tuple[str, Literal["set", "append"]] | None] = {
    TacticalTopic.PRIMARY_STYLE: ("tactical_identity.primary_style", "set"),
    TacticalTopic.PREFERRED_FORMATION: ("tactical_identity.preferred_formations", "append"),
    TacticalTopic.BUILD_UP: ("tactical_identity.build_up", "set"),
    TacticalTopic.DEFENSIVE_SHAPE: ("tactical_identity.defensive_shape", "set"),
    TacticalTopic.PRESSING: ("tactical_identity.pressing", "set"),
    TacticalTopic.TRANSITION: ("tactical_identity.transition", "set"),
    TacticalTopic.SET_PIECES: ("tactical_identity.set_pieces", "set"),
    TacticalTopic.IN_POSSESSION: ("tactical_identity.in_possession", "append"),
    TacticalTopic.OUT_OF_POSSESSION: ("tactical_identity.out_of_possession", "append"),
    TacticalTopic.TRANSITION_ACTION: ("tactical_identity.transition_actions", "append"),
    TacticalTopic.SET_PIECE_ACTION: ("tactical_identity.set_piece_actions", "append"),
    TacticalTopic.OTHER: None,
}


class TacticalEvidenceRecord(StrictModel):
    evidence_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    manager_id: str = Field(pattern=r"^[a-z0-9_]+$")
    manager_name: str = Field(min_length=1)
    team: str = Field(min_length=1)
    evidence_type: TacticalEvidenceType
    tactical_topic: TacticalTopic
    claim_text: str = Field(min_length=1)
    proposed_value: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    source_url: str | None = None
    source_kind: str = Field(min_length=1)
    published_at: date | None = None
    match_id: str | None = None
    source_quality: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    content_origin: ContentOrigin = ContentOrigin.MANUAL
    reviewed_by_human: bool = True
    recurrence_key: str = Field(min_length=1)
    notes: str | None = None
    data_quality: str = Field(min_length=1)


class ManagerSkillUpdate(StrictModel):
    update_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    manager_id: str = Field(pattern=r"^[a-z0-9_]+$")
    manager_name: str = Field(min_length=1)
    team: str = Field(min_length=1)
    tactical_topic: TacticalTopic
    target_path: str = Field(min_length=1)
    operation: Literal["set", "append", "review_only"]
    proposed_value: str = Field(min_length=1)
    claim_text: str = Field(min_length=1)
    evidence_ids: str = Field(min_length=1)
    source_ids: str = Field(min_length=1)
    evidence_count: int = Field(ge=1)
    distinct_sources: int = Field(ge=1)
    distinct_matches: int = Field(ge=0)
    source_quality: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    review_status: UpdateReviewStatus
    reason: str = Field(min_length=1)
    applied: bool = False
    applied_at: datetime | None = None

    _applied_at_aware = field_validator("applied_at")(_aware)


TACTICAL_EVIDENCE_FIELDS = list(TacticalEvidenceRecord.model_fields)
MANAGER_SKILL_UPDATE_FIELDS = list(ManagerSkillUpdate.model_fields)
RAW_REQUIRED_FIELDS = {
    "manager_id",
    "manager_name",
    "team",
    "evidence_type",
    "tactical_topic",
    "claim_text",
    "proposed_value",
    "source_id",
    "source_title",
}


@dataclass
class TacticalEvidenceIngestionResult:
    records: list[TacticalEvidenceRecord] = field(default_factory=list)
    issues: list[DataQualityIssue] = field(default_factory=list)
    rows_raw: int = 0


@dataclass
class ManagerRefinementResult:
    applied_update_ids: list[str] = field(default_factory=list)
    written_files: list[Path] = field(default_factory=list)
    issues: list[DataQualityIssue] = field(default_factory=list)


class TacticalEvidenceAdapter(Protocol):
    name: str

    def fetch(self) -> tuple[list[dict[str, str]], list[DataQualityIssue]]:
        ...

    def normalize(self, raw_rows: list[dict[str, str]]) -> TacticalEvidenceIngestionResult:
        ...


def _normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def normalize_evidence_type(value: str) -> TacticalEvidenceType:
    normalized = _normalized_text(value)
    return EVIDENCE_TYPE_ALIASES.get(normalized, TacticalEvidenceType.OTHER)


def normalize_tactical_topic(value: str) -> TacticalTopic:
    normalized = _normalized_text(value)
    return TACTICAL_TOPIC_ALIASES.get(normalized, TacticalTopic.OTHER)


def _bool(value: Any, default: bool = False) -> bool:
    if value in {None, ""}:
        return default
    return str(value).casefold() in {"1", "true", "yes", "y"}


def _quality(source_kind: str, source_reliability: float, directness: float) -> tuple[float, float]:
    base = SOURCE_KIND_BASE_QUALITY.get(_normalized_text(source_kind).replace(" ", "_"), SOURCE_KIND_BASE_QUALITY["unknown"])
    reliability = max(0.0, min(1.0, source_reliability))
    direct = max(0.0, min(1.0, directness))
    source_quality = round((0.6 * base) + (0.4 * reliability), 3)
    confidence = round(source_quality * (0.65 + (0.35 * direct)), 3)
    return source_quality, confidence


def _stable_id(prefix: str, values: Iterable[Any]) -> str:
    identity = "|".join(str(value or "").strip() for value in values)
    return f"{prefix}_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}"


class ManualCsvTacticalEvidenceAdapter:
    name = "manual_csv"

    def __init__(self, path: Path, source_reliability: float = 0.7):
        self.path = path
        self.source_reliability = source_reliability

    def fetch(self) -> tuple[list[dict[str, str]], list[DataQualityIssue]]:
        result = safe_read_csv(self.path, RAW_REQUIRED_FIELDS)
        return result.rows, result.issues

    def normalize(self, raw_rows: list[dict[str, str]]) -> TacticalEvidenceIngestionResult:
        result = TacticalEvidenceIngestionResult(rows_raw=len(raw_rows))
        for row_number, row in enumerate(raw_rows, start=2):
            try:
                reliability = float(row.get("source_reliability") or self.source_reliability)
                directness = float(row.get("directness") or 0.7)
                source_quality, confidence = _quality(row.get("source_kind") or "unknown", reliability, directness)
            except (TypeError, ValueError):
                reliability = directness = -1
                source_quality = confidence = -1
            evidence_type = normalize_evidence_type(row.get("evidence_type", ""))
            topic = normalize_tactical_topic(row.get("tactical_topic", ""))
            evidence_id = row.get("evidence_id") or _stable_id(
                "tactical",
                (
                    row.get("manager_id"),
                    row.get("tactical_topic"),
                    row.get("proposed_value"),
                    row.get("source_id"),
                    row.get("match_id"),
                ),
            )
            recurrence_key = row.get("recurrence_key") or _stable_id(
                "claim",
                (row.get("manager_id"), topic.value, row.get("proposed_value")),
            )
            payload: dict[str, Any] = {
                "evidence_id": evidence_id,
                "manager_id": row.get("manager_id"),
                "manager_name": row.get("manager_name"),
                "team": row.get("team"),
                "evidence_type": evidence_type,
                "tactical_topic": topic,
                "claim_text": row.get("claim_text"),
                "proposed_value": row.get("proposed_value"),
                "source_id": row.get("source_id"),
                "source_title": row.get("source_title"),
                "source_url": row.get("source_url") or None,
                "source_kind": row.get("source_kind") or "unknown",
                "published_at": row.get("published_at") or None,
                "match_id": row.get("match_id") or None,
                "source_quality": source_quality,
                "confidence": confidence,
                "content_origin": row.get("content_origin") or ContentOrigin.MANUAL,
                "reviewed_by_human": _bool(row.get("reviewed_by_human"), False),
                "recurrence_key": recurrence_key,
                "notes": row.get("notes") or None,
                "data_quality": "manual_curated_evidence",
            }
            validated = validate_rows([payload], TacticalEvidenceRecord, file=self.path, starting_row_number=row_number)
            result.records.extend(validated.valid_records)
            result.issues.extend(validated.issues)
        return result


def ingest_tactical_evidence(adapter: TacticalEvidenceAdapter) -> TacticalEvidenceIngestionResult:
    rows, read_issues = adapter.fetch()
    result = adapter.normalize(rows)
    result.issues = [*read_issues, *result.issues]
    return result


def _row(model: BaseModel, fields: list[str]) -> dict[str, Any]:
    payload = model.model_dump(mode="json")
    return {field: "" if payload.get(field) is None else payload.get(field, "") for field in fields}


def write_normalized_tactical_evidence(
    records: list[TacticalEvidenceRecord],
    path: Path = TACTICAL_EVIDENCE_NORMALIZED_PATH,
) -> list[DataQualityIssue]:
    return safe_write_csv(path, [_row(item, TACTICAL_EVIDENCE_FIELDS) for item in records], TACTICAL_EVIDENCE_FIELDS).issues


def load_normalized_tactical_evidence(
    path: Path = TACTICAL_EVIDENCE_NORMALIZED_PATH,
) -> tuple[list[TacticalEvidenceRecord], list[DataQualityIssue]]:
    read = safe_read_csv(path, TACTICAL_EVIDENCE_FIELDS)
    rows = [
        {
            **row,
            "source_url": row.get("source_url") or None,
            "published_at": row.get("published_at") or None,
            "match_id": row.get("match_id") or None,
            "notes": row.get("notes") or None,
        }
        for row in read.rows
    ]
    validated = validate_rows(rows, TacticalEvidenceRecord, file=path)
    return validated.valid_records, [*read.issues, *validated.issues]


def suggest_manager_skill_updates(records: list[TacticalEvidenceRecord]) -> list[ManagerSkillUpdate]:
    """Build an evidence-backed review queue; no manager skill is changed here."""
    grouped: defaultdict[tuple[str, TacticalTopic, str], list[TacticalEvidenceRecord]] = defaultdict(list)
    topic_values: defaultdict[tuple[str, TacticalTopic], set[str]] = defaultdict(set)
    for record in records:
        key = (record.manager_id, record.tactical_topic, record.proposed_value)
        grouped[key].append(record)
        topic_values[(record.manager_id, record.tactical_topic)].add(record.proposed_value)

    updates = []
    for (manager_id, topic, proposed_value), evidence in sorted(grouped.items(), key=lambda item: item[0]):
        first = evidence[0]
        target = TOPIC_TARGETS[topic]
        evidence_ids = sorted({item.evidence_id for item in evidence})
        source_ids = sorted({item.source_id for item in evidence})
        matches = {item.match_id for item in evidence if item.match_id}
        confidence = mean(item.confidence for item in evidence)
        source_quality = mean(item.source_quality for item in evidence)
        recurrence = len(source_ids) >= 2 or len(matches) >= 2
        conflicting = len(topic_values[(manager_id, topic)]) > 1
        human_reviewed = all(item.reviewed_by_human and item.content_origin != ContentOrigin.LLM_GENERATED for item in evidence)
        if target is None:
            review_status = UpdateReviewStatus.UNSUPPORTED_TARGET
            reason = "The tactical topic has no supported ManagerSkill target and remains review-only."
            target_path, operation = "review_only", "review_only"
        elif not human_reviewed:
            review_status = UpdateReviewStatus.NEEDS_HUMAN_REVIEW
            reason = "At least one claim is unreviewed or LLM-generated; direct application is prohibited."
            target_path, operation = target
        elif conflicting:
            review_status = UpdateReviewStatus.CONFLICTING_EVIDENCE
            reason = "Different proposed values exist for the same manager and tactical topic."
            target_path, operation = target
        elif not recurrence or confidence < 0.65:
            review_status = UpdateReviewStatus.NEEDS_MORE_EVIDENCE
            reason = "More independent evidence or higher confidence is required before application."
            target_path, operation = target
        else:
            review_status = UpdateReviewStatus.READY_FOR_REVIEW
            reason = "Recurring, human-reviewed evidence supports an explicit reviewable update."
            target_path, operation = target
        updates.append(
            ManagerSkillUpdate(
                update_id=_stable_id("update", (manager_id, topic.value, proposed_value, *evidence_ids)),
                manager_id=manager_id,
                manager_name=first.manager_name,
                team=first.team,
                tactical_topic=topic,
                target_path=target_path,
                operation=operation,
                proposed_value=proposed_value,
                claim_text=first.claim_text,
                evidence_ids="|".join(evidence_ids),
                source_ids="|".join(source_ids),
                evidence_count=len(evidence_ids),
                distinct_sources=len(source_ids),
                distinct_matches=len(matches),
                source_quality=round(source_quality, 3),
                confidence=round(confidence, 3),
                review_status=review_status,
                reason=reason,
            )
        )
    return updates


def write_manager_skill_updates(
    updates: list[ManagerSkillUpdate],
    path: Path = MANAGER_SKILL_UPDATES_PATH,
) -> list[DataQualityIssue]:
    return safe_write_csv(path, [_row(item, MANAGER_SKILL_UPDATE_FIELDS) for item in updates], MANAGER_SKILL_UPDATE_FIELDS).issues


def load_manager_skill_updates(
    path: Path = MANAGER_SKILL_UPDATES_PATH,
) -> tuple[list[ManagerSkillUpdate], list[DataQualityIssue]]:
    read = safe_read_csv(path, MANAGER_SKILL_UPDATE_FIELDS)
    rows = [{**row, "applied_at": row.get("applied_at") or None} for row in read.rows]
    validated = validate_rows(rows, ManagerSkillUpdate, file=path)
    return validated.valid_records, [*read.issues, *validated.issues]


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _apply_target(payload: dict[str, Any], update: ManagerSkillUpdate) -> None:
    _, field_name = update.target_path.split(".", 1)
    identity = payload["tactical_identity"]
    if update.operation == "set":
        identity[field_name] = update.proposed_value
    elif update.operation == "append":
        values = list(identity.get(field_name) or [])
        if update.proposed_value not in values:
            values.append(update.proposed_value)
        identity[field_name] = values


def apply_manager_skill_updates(
    updates: list[ManagerSkillUpdate],
    evidence: list[TacticalEvidenceRecord],
    *,
    apply: bool = False,
    manager_skills_dir: Path = MANAGER_SKILLS_DIR,
) -> ManagerRefinementResult:
    """Apply only eligible human-reviewed updates after full schema validation."""
    result = ManagerRefinementResult()
    if not apply:
        return result
    evidence_by_id = {item.evidence_id: item for item in evidence}
    eligible_ids = {
        update.update_id
        for update in suggest_manager_skill_updates(evidence)
        if update.review_status == UpdateReviewStatus.READY_FOR_REVIEW
    }
    grouped: defaultdict[str, list[ManagerSkillUpdate]] = defaultdict(list)
    for update in updates:
        if update.review_status == UpdateReviewStatus.READY_FOR_REVIEW and update.update_id in eligible_ids:
            grouped[update.manager_id].append(update)

    for manager_id, manager_updates in grouped.items():
        path = manager_skills_dir / f"{manager_id}.json"
        if not path.exists():
            result.issues.append(
                make_data_quality_issue(
                    file=path,
                    severity=DataQualitySeverity.WARNING,
                    problem=f"No existing manager skill JSON for {manager_id}; updates remain review-only.",
                    suggested_fix="Create and validate a manager skill before applying refinements.",
                )
            )
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            ManagerSkill.model_validate(payload)
            applied_ids = []
            referenced_evidence: list[TacticalEvidenceRecord] = []
            for update in manager_updates:
                ids = update.evidence_ids.split("|")
                rows = [evidence_by_id[item] for item in ids if item in evidence_by_id]
                if len(rows) != len(ids):
                    raise ValueError(f"Update {update.update_id} references unavailable evidence IDs.")
                if not all(row.reviewed_by_human and row.content_origin != ContentOrigin.LLM_GENERATED for row in rows):
                    raise ValueError(f"Update {update.update_id} includes evidence that cannot be directly applied.")
                _apply_target(payload, update)
                applied_ids.append(update.update_id)
                referenced_evidence.extend(rows)
                payload.setdefault("evidence_notes", []).append(
                    f"Applied refinement {update.update_id}; evidence: {update.evidence_ids}; confidence: {update.confidence:.3f}."
                )
            existing_refs = {item.get("source_id") for item in payload.get("source_refs", [])}
            for row in referenced_evidence:
                if row.source_id in existing_refs:
                    continue
                payload.setdefault("source_refs", []).append(
                    EvidenceReference(
                        source_id=row.source_id,
                        title=row.source_title,
                        url=row.source_url,
                        observed_at=row.published_at,
                        note=f"Evidence-backed manager refinement; evidence_id={row.evidence_id}.",
                    ).model_dump(mode="json")
                )
                existing_refs.add(row.source_id)
            latest = max((row.published_at for row in referenced_evidence if row.published_at), default=None)
            if latest:
                payload["last_verified"] = latest.isoformat()
            validated = ManagerSkill.model_validate(payload)
            _atomic_json_write(path, validated.model_dump(mode="json"))
            result.applied_update_ids.extend(applied_ids)
            result.written_files.append(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            result.issues.append(
                make_data_quality_issue(
                    file=path,
                    severity=DataQualitySeverity.ERROR,
                    problem=f"Manager skill refinements could not be applied: {exc}",
                    suggested_fix="Review the proposed updates and existing manager skill JSON.",
                )
            )
    return result
