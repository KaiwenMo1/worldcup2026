"""Provider-independent actual-lineup ingestion and transparent lineup deltas."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ingestion.normalizers import make_data_quality_issue, safe_read_csv, safe_write_csv, validate_rows
from app.ingestion.player_stats_ingestion import ROLE_VECTORS_PATH
from app.ingestion.schemas import DataQualityIssue, DataQualitySeverity
from app.tactics.player_profiles import player_id_for


ROOT = Path(__file__).resolve().parents[2]
MANUAL_LINEUPS_SAMPLE_PATH = ROOT / "data" / "raw" / "lineups" / "manual_lineups_sample.csv"
CONFIRMED_LINEUPS_PATH = ROOT / "data" / "confirmed_lineups.csv"
PROJECTED_LINEUPS_PATH = ROOT / "data" / "projected_lineups.csv"
ACTUAL_LINEUPS_PATH = ROOT / "data" / "normalized" / "actual_lineups_normalized.csv"
LINEUP_DELTA_SIGNALS_PATH = ROOT / "data" / "derived" / "lineup_delta_signals.csv"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("updated_at must include a timezone")
    return value


class ActualLineupPlayer(StrictModel):
    match_id: str = Field(min_length=1)
    team: str = Field(min_length=1)
    opponent: str = ""
    formation: str = ""
    player_id: str = Field(min_length=1)
    player: str = Field(min_length=1)
    position: str = ""
    role: str = ""
    starter: bool = True
    confirmed: bool = True
    source: str = Field(min_length=1)
    source_confidence: float = Field(ge=0, le=1)
    updated_at: datetime

    _updated_at_aware = field_validator("updated_at")(_aware)


class LineupDeltaSignal(StrictModel):
    match_id: str = Field(min_length=1)
    team: str = Field(min_length=1)
    projected_formation: str = ""
    actual_formation: str = ""
    formation_changed: bool
    projected_starters: int = Field(ge=0)
    actual_starters: int = Field(ge=0)
    unchanged_starters: int = Field(ge=0)
    missing_projected_starters: list[str] = Field(default_factory=list)
    unexpected_starters: list[str] = Field(default_factory=list)
    lineup_strength_delta: float
    pressing_delta: float
    creation_delta: float
    set_piece_delta: float
    defensive_delta: float
    goalkeeper_delta: float
    confidence: float = Field(ge=0, le=1)
    source: str = Field(min_length=1)
    data_quality: str = Field(min_length=1)
    updated_at: datetime

    _updated_at_aware = field_validator("updated_at")(_aware)


ACTUAL_LINEUP_FIELDS = list(ActualLineupPlayer.model_fields)
LINEUP_DELTA_FIELDS = list(LineupDeltaSignal.model_fields)


@dataclass
class LineupIngestionResult:
    records: list[ActualLineupPlayer] = field(default_factory=list)
    issues: list[DataQualityIssue] = field(default_factory=list)
    rows_raw: int = 0


class LineupAdapter(Protocol):
    name: str

    def fetch(self) -> tuple[list[dict[str, str]], list[DataQualityIssue]]:
        ...

    def normalize(self, raw_rows: list[dict[str, str]]) -> LineupIngestionResult:
        ...


def _bool(value: Any, default: bool = False) -> bool:
    if value in {None, ""}:
        return default
    return str(value).casefold() in {"1", "true", "yes", "y"}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _stable_match_id(row: dict[str, Any]) -> str:
    supplied = str(row.get("match_id") or row.get("fixture_id") or "").strip()
    if supplied:
        return supplied
    identity = "|".join(
        str(row.get(field, "")).strip().casefold()
        for field in ("team", "opponent", "updated_at")
    )
    return f"lineup_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"


class CsvLineupAdapter:
    """Normalize manual or provider-exported lineup CSV rows."""

    name = "csv_lineup"

    def __init__(self, path: Path, *, require_confirmed: bool = True, source_confidence: float = 0.8):
        self.path = path
        self.require_confirmed = require_confirmed
        self.source_confidence = source_confidence

    def fetch(self) -> tuple[list[dict[str, str]], list[DataQualityIssue]]:
        result = safe_read_csv(self.path, {"team", "player"})
        return result.rows, result.issues

    def normalize(self, raw_rows: list[dict[str, str]]) -> LineupIngestionResult:
        result = LineupIngestionResult(rows_raw=len(raw_rows))
        for row_number, row in enumerate(raw_rows, start=2):
            starter = _bool(row.get("starter"), True)
            confirmed = _bool(row.get("confirmed"), True)
            if not starter or (self.require_confirmed and not confirmed):
                continue
            team = row.get("team", "").strip()
            player = row.get("player", "").strip()
            payload = {
                "match_id": _stable_match_id(row),
                "team": team,
                "opponent": row.get("opponent", ""),
                "formation": row.get("formation", ""),
                "player_id": row.get("player_id") or player_id_for(team, player),
                "player": player,
                "position": row.get("position") or row.get("position_slot") or row.get("formation_field", ""),
                "role": row.get("role", ""),
                "starter": starter,
                "confirmed": confirmed,
                "source": row.get("source") or self.name,
                "source_confidence": _float(row.get("source_confidence") or row.get("confidence"), self.source_confidence),
                "updated_at": row.get("updated_at") or row.get("fetched_at") or datetime.now(timezone.utc).isoformat(),
            }
            validated = validate_rows([payload], ActualLineupPlayer, file=self.path, starting_row_number=row_number)
            result.records.extend(validated.valid_records)
            result.issues.extend(validated.issues)
        if raw_rows and not result.records:
            result.issues.append(
                make_data_quality_issue(
                    file=self.path,
                    severity=DataQualitySeverity.WARNING,
                    problem="No confirmed starters were present in the lineup input",
                    suggested_fix="Wait for confirmed lineups or set confirmed=true on verified starter rows.",
                )
            )
        return result


def ingest_lineups(adapter: LineupAdapter) -> LineupIngestionResult:
    rows, issues = adapter.fetch()
    result = adapter.normalize(rows)
    result.issues = [*issues, *result.issues]
    return result


def _csv_row(model: BaseModel, fields: list[str]) -> dict[str, Any]:
    payload = model.model_dump(mode="json")
    for field_name in fields:
        if isinstance(payload.get(field_name), list):
            payload[field_name] = "|".join(payload[field_name])
    return {field_name: "" if payload.get(field_name) is None else payload.get(field_name, "") for field_name in fields}


def write_actual_lineups(
    records: list[ActualLineupPlayer],
    path: Path = ACTUAL_LINEUPS_PATH,
) -> list[DataQualityIssue]:
    result = safe_write_csv(path, [_csv_row(record, ACTUAL_LINEUP_FIELDS) for record in records], ACTUAL_LINEUP_FIELDS)
    return result.issues


def load_actual_lineups(path: Path = ACTUAL_LINEUPS_PATH) -> tuple[list[ActualLineupPlayer], list[DataQualityIssue]]:
    read = safe_read_csv(path, ACTUAL_LINEUP_FIELDS)
    validated = validate_rows(read.rows, ActualLineupPlayer, file=path)
    return validated.valid_records, [*read.issues, *validated.issues]


def _projected_rows(path: Path = PROJECTED_LINEUPS_PATH) -> tuple[list[dict[str, str]], list[DataQualityIssue]]:
    read = safe_read_csv(path)
    return read.rows, read.issues


def _role_vectors(path: Path = ROLE_VECTORS_PATH) -> tuple[dict[str, dict[str, float]], list[DataQualityIssue]]:
    read = safe_read_csv(path)
    output: dict[str, dict[str, float]] = {}
    for row in read.rows:
        player_id = row.get("player_id", "")
        if not player_id:
            continue
        dimensions = {
            "strength": _float(row.get("role_fit_score"), 50.0),
            "pressing": _float(row.get("pressing_score"), 50.0),
            "creation": _float(row.get("creation_score"), 50.0),
            "set_piece": _float(row.get("set_piece_score"), 50.0),
            "defensive": _float(row.get("defending_score"), 50.0),
            "goalkeeper": _float(row.get("defending_score"), 50.0)
            if str(row.get("position", "")).casefold() in {"gk", "goalkeeper"}
            else 0.0,
        }
        previous = output.get(player_id)
        if previous is None or dimensions["strength"] > previous["strength"]:
            output[player_id] = dimensions
    return output, read.issues


def _squad_vector(player_ids: Iterable[str], vectors: dict[str, dict[str, float]]) -> dict[str, float]:
    rows = [vectors.get(player_id, {key: 50.0 if key != "goalkeeper" else 0.0 for key in (
        "strength", "pressing", "creation", "set_piece", "defensive", "goalkeeper"
    )}) for player_id in player_ids]
    if not rows:
        return {key: 0.0 for key in ("strength", "pressing", "creation", "set_piece", "defensive", "goalkeeper")}
    return {key: mean(row[key] for row in rows) for key in rows[0]}


def build_lineup_delta_signals(
    actual: list[ActualLineupPlayer],
    *,
    projected_path: Path = PROJECTED_LINEUPS_PATH,
    role_vectors_path: Path = ROLE_VECTORS_PATH,
) -> tuple[list[LineupDeltaSignal], list[DataQualityIssue]]:
    projected, projected_issues = _projected_rows(projected_path)
    vectors, vector_issues = _role_vectors(role_vectors_path)
    issues = [*projected_issues, *vector_issues]
    actual_groups: dict[tuple[str, str], list[ActualLineupPlayer]] = defaultdict(list)
    for row in actual:
        actual_groups[(row.match_id, row.team)].append(row)

    signals = []
    for (match_id, team), actual_rows in sorted(actual_groups.items()):
        candidates = [
            row for row in projected
            if row.get("team", "").casefold() == team.casefold()
            and row.get("match_id", "") in {"", match_id}
            and _float(row.get("starter_probability"), 0.0) >= 0.5
        ]
        projected_ids = {row.get("player_id") or player_id_for(team, row.get("player", "")): row for row in candidates}
        actual_ids = {row.player_id: row for row in actual_rows}
        missing_ids = sorted(set(projected_ids) - set(actual_ids))
        unexpected_ids = sorted(set(actual_ids) - set(projected_ids))
        projected_vector = _squad_vector(projected_ids, vectors)
        actual_vector = _squad_vector(actual_ids, vectors)
        projected_formation = next((row.get("formation", "") for row in candidates if row.get("formation")), "")
        actual_formation = next((row.formation for row in actual_rows if row.formation), "")
        confidence = mean(row.source_confidence for row in actual_rows) if actual_rows else 0.0
        data_quality = "confirmed_complete" if len(actual_rows) >= 11 else "confirmed_partial"
        signals.append(
            LineupDeltaSignal(
                match_id=match_id,
                team=team,
                projected_formation=projected_formation,
                actual_formation=actual_formation,
                formation_changed=bool(projected_formation and actual_formation and projected_formation != actual_formation),
                projected_starters=len(projected_ids),
                actual_starters=len(actual_ids),
                unchanged_starters=len(set(projected_ids) & set(actual_ids)),
                missing_projected_starters=[projected_ids[player_id].get("player", player_id) for player_id in missing_ids],
                unexpected_starters=[actual_ids[player_id].player for player_id in unexpected_ids],
                lineup_strength_delta=round(actual_vector["strength"] - projected_vector["strength"], 3),
                pressing_delta=round(actual_vector["pressing"] - projected_vector["pressing"], 3),
                creation_delta=round(actual_vector["creation"] - projected_vector["creation"], 3),
                set_piece_delta=round(actual_vector["set_piece"] - projected_vector["set_piece"], 3),
                defensive_delta=round(actual_vector["defensive"] - projected_vector["defensive"], 3),
                goalkeeper_delta=round(actual_vector["goalkeeper"] - projected_vector["goalkeeper"], 3),
                confidence=round(confidence, 3),
                source="actual_lineups + projected_lineups + player_role_vectors",
                data_quality=data_quality,
                updated_at=max(row.updated_at for row in actual_rows),
            )
        )
    return signals, issues


def write_lineup_delta_signals(
    signals: list[LineupDeltaSignal],
    path: Path = LINEUP_DELTA_SIGNALS_PATH,
) -> list[DataQualityIssue]:
    result = safe_write_csv(path, [_csv_row(signal, LINEUP_DELTA_FIELDS) for signal in signals], LINEUP_DELTA_FIELDS)
    return result.issues


def load_lineup_delta_signals(
    path: Path = LINEUP_DELTA_SIGNALS_PATH,
) -> tuple[list[LineupDeltaSignal], list[DataQualityIssue]]:
    read = safe_read_csv(path, LINEUP_DELTA_FIELDS)
    rows = []
    for row in read.rows:
        row["missing_projected_starters"] = [item for item in row.get("missing_projected_starters", "").split("|") if item]
        row["unexpected_starters"] = [item for item in row.get("unexpected_starters", "").split("|") if item]
        rows.append(row)
    validated = validate_rows(rows, LineupDeltaSignal, file=path)
    return validated.valid_records, [*read.issues, *validated.issues]


def get_lineup_delta_signal(team: str, match_id: str | None = None) -> LineupDeltaSignal | None:
    signals, _ = load_lineup_delta_signals()
    candidates = [
        signal for signal in signals
        if signal.team.casefold() == team.casefold() and (match_id is None or signal.match_id == match_id)
    ]
    return max(candidates, key=lambda signal: signal.updated_at, default=None)


__all__ = [
    "ACTUAL_LINEUPS_PATH",
    "LINEUP_DELTA_SIGNALS_PATH",
    "MANUAL_LINEUPS_SAMPLE_PATH",
    "ActualLineupPlayer",
    "CsvLineupAdapter",
    "LineupDeltaSignal",
    "LineupIngestionResult",
    "build_lineup_delta_signals",
    "get_lineup_delta_signal",
    "ingest_lineups",
    "load_actual_lineups",
    "load_lineup_delta_signals",
    "write_actual_lineups",
    "write_lineup_delta_signals",
]
