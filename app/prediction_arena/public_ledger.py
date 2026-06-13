"""CSV-backed public prediction ledger with explicit lock semantics."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.ingestion.normalizers import safe_read_csv, safe_write_csv
from app.prediction_arena.risk_guardrails import (
    ensure_entertainment_disclaimer,
    reject_betting_advice_language,
)
from app.prediction_arena.schemas import PredictionRecord, PredictionStatus


ROOT = Path(__file__).resolve().parents[2]
PRE_MATCH_PREDICTIONS_PATH = ROOT / "data" / "prediction_arena" / "ledgers" / "pre_match_predictions.csv"
PREDICTION_FIELDS = [
    "prediction_id",
    "version",
    "match_id",
    "created_at",
    "team_a",
    "team_b",
    "stage",
    "agent_name",
    "regular_time_pick",
    "regular_time_score",
    "qualification_pick",
    "penalty_probability",
    "confidence",
    "core_reason",
    "fragile_assumptions",
    "public_card_path",
    "status",
    "entertainment_disclaimer",
]

_WRITE_LOCK = threading.Lock()


class PredictionLedgerError(ValueError):
    """Base error for invalid prediction-ledger operations."""


class PredictionLedgerConflict(PredictionLedgerError):
    """Raised when a ledger operation would violate immutability."""


class PredictionLedgerDataError(PredictionLedgerError):
    """Raised when an existing ledger cannot be validated."""


def _ensure_ledger(path: Path) -> None:
    if path.exists():
        return
    result = safe_write_csv(path, [], PREDICTION_FIELDS)
    if not result.ok:
        raise PredictionLedgerDataError("; ".join(issue.problem for issue in result.issues))


def _row(record: PredictionRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="json")
    payload["fragile_assumptions"] = json.dumps(record.fragile_assumptions, ensure_ascii=True)
    return {field: "" if payload.get(field) is None else payload.get(field, "") for field in PREDICTION_FIELDS}


def _record(row: dict[str, str]) -> PredictionRecord:
    try:
        return PredictionRecord.model_validate(
            {
                **row,
                "version": int(row["version"]),
                "penalty_probability": float(row["penalty_probability"]) if row.get("penalty_probability") else None,
                "confidence": float(row["confidence"]),
                "qualification_pick": row.get("qualification_pick") or None,
                "public_card_path": row.get("public_card_path") or None,
                "fragile_assumptions": json.loads(row.get("fragile_assumptions") or "[]"),
            }
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, ValidationError) as exc:
        raise PredictionLedgerDataError(
            f"Invalid prediction ledger row {row.get('prediction_id', '<unknown>')}: {exc}"
        ) from exc


def load_predictions(path: Path = PRE_MATCH_PREDICTIONS_PATH) -> list[PredictionRecord]:
    """Load ledger records oldest first, creating the CSV contract when absent."""
    _ensure_ledger(path)
    result = safe_read_csv(path, PREDICTION_FIELDS)
    critical = [issue.problem for issue in result.issues if issue.severity.value in {"error", "critical"}]
    if critical:
        raise PredictionLedgerDataError("; ".join(critical))
    return [_record(row) for row in result.rows]


def prevent_overwrite_locked_prediction(
    existing: PredictionRecord,
    proposed: PredictionRecord | None = None,
) -> None:
    """Reject mutation of records that have crossed the public lock boundary."""
    if existing.status != PredictionStatus.DRAFT:
        raise PredictionLedgerConflict(
            f"Prediction {existing.prediction_id!r} is {existing.status.value} and cannot be overwritten; "
            "create a new prediction ID/version instead."
        )
    if proposed is not None and existing.prediction_id != proposed.prediction_id:
        raise PredictionLedgerConflict("Overwrite checks require the same prediction_id.")


def append_prediction_record(
    record: PredictionRecord,
    path: Path = PRE_MATCH_PREDICTIONS_PATH,
) -> PredictionRecord:
    """Append one new draft record without overwriting any previous version."""
    if record.status != PredictionStatus.DRAFT:
        raise PredictionLedgerConflict("New prediction records must be appended as draft before they can be locked.")
    safe_record = ensure_entertainment_disclaimer(record)
    reject_betting_advice_language(safe_record)
    with _WRITE_LOCK:
        records = load_predictions(path)
        existing = next((item for item in records if item.prediction_id == safe_record.prediction_id), None)
        if existing is not None:
            prevent_overwrite_locked_prediction(existing, safe_record)
            raise PredictionLedgerConflict(
                f"Prediction {safe_record.prediction_id!r} already exists; create a new prediction ID/version."
            )
        result = safe_write_csv(path, [_row(safe_record)], PREDICTION_FIELDS, append=True)
        if not result.ok:
            raise PredictionLedgerDataError("; ".join(issue.problem for issue in result.issues))
    return safe_record


def lock_prediction(
    prediction_id: str,
    path: Path = PRE_MATCH_PREDICTIONS_PATH,
) -> PredictionRecord:
    """Atomically move a draft prediction to locked; repeated locking is idempotent."""
    with _WRITE_LOCK:
        records = load_predictions(path)
        index = next((position for position, item in enumerate(records) if item.prediction_id == prediction_id), None)
        if index is None:
            raise PredictionLedgerError(f"Prediction {prediction_id!r} does not exist.")
        existing = records[index]
        if existing.status != PredictionStatus.DRAFT:
            return existing
        locked = existing.model_copy(update={"status": PredictionStatus.LOCKED})
        records[index] = locked
        result = safe_write_csv(path, [_row(record) for record in records], PREDICTION_FIELDS)
        if not result.ok:
            raise PredictionLedgerDataError("; ".join(issue.problem for issue in result.issues))
    return locked
