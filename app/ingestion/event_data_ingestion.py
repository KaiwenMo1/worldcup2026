"""Provider-independent post-match event ingestion and transparent match summaries."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ingestion.normalizers import make_data_quality_issue, safe_read_csv, safe_write_csv, validate_rows
from app.ingestion.schemas import DataQualityIssue, DataQualitySeverity


ROOT = Path(__file__).resolve().parents[2]
MANUAL_MATCH_EVENTS_SAMPLE_PATH = ROOT / "data" / "raw" / "event_data" / "manual_match_events_sample.csv"
MATCH_EVENTS_NORMALIZED_PATH = ROOT / "data" / "normalized" / "match_events_normalized.csv"
MATCH_SUMMARY_SIGNALS_PATH = ROOT / "data" / "derived" / "match_summary_signals.csv"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("updated_at must include a timezone")
    return value


class MatchEventType(StrEnum):
    SHOT = "shot"
    GOAL = "goal"
    PASS = "pass"
    KEY_PASS = "key_pass"
    PROGRESSIVE_PASS = "progressive_pass"
    CARRY = "carry"
    PROGRESSIVE_CARRY = "progressive_carry"
    CROSS = "cross"
    TACKLE = "tackle"
    INTERCEPTION = "interception"
    DUEL = "duel"
    AERIAL_DUEL = "aerial_duel"
    FOUL = "foul"
    CARD = "card"
    SUBSTITUTION = "substitution"
    SET_PIECE = "set_piece"
    CORNER = "corner"
    PENALTY = "penalty"
    SAVE = "save"


EVENT_TYPE_ALIASES: dict[str, MatchEventType] = {
    "shot": MatchEventType.SHOT,
    "goal": MatchEventType.GOAL,
    "pass": MatchEventType.PASS,
    "key pass": MatchEventType.KEY_PASS,
    "shot assist": MatchEventType.KEY_PASS,
    "progressive pass": MatchEventType.PROGRESSIVE_PASS,
    "carry": MatchEventType.CARRY,
    "progressive carry": MatchEventType.PROGRESSIVE_CARRY,
    "cross": MatchEventType.CROSS,
    "tackle": MatchEventType.TACKLE,
    "interception": MatchEventType.INTERCEPTION,
    "duel": MatchEventType.DUEL,
    "aerial duel": MatchEventType.AERIAL_DUEL,
    "foul": MatchEventType.FOUL,
    "foul committed": MatchEventType.FOUL,
    "card": MatchEventType.CARD,
    "booking": MatchEventType.CARD,
    "substitution": MatchEventType.SUBSTITUTION,
    "set piece": MatchEventType.SET_PIECE,
    "free kick": MatchEventType.SET_PIECE,
    "corner": MatchEventType.CORNER,
    "penalty": MatchEventType.PENALTY,
    "save": MatchEventType.SAVE,
    "goalkeeper save": MatchEventType.SAVE,
}

DEFAULT_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "event_id": ("event_id", "id", "provider_event_id"),
    "match_id": ("match_id", "fixture_id", "game_id"),
    "match_date": ("match_date", "date", "game_date"),
    "competition": ("competition", "competition_name", "tournament"),
    "team": ("team", "team_name", "possession_team"),
    "opponent": ("opponent", "opponent_name"),
    "player": ("player", "player_name"),
    "related_player": ("related_player", "recipient", "recipient_name"),
    "event_type": ("event_type", "type", "type_name"),
    "period": ("period", "half"),
    "minute": ("minute", "min"),
    "second": ("second", "sec"),
    "possession_id": ("possession_id", "possession"),
    "possession_team": ("possession_team", "possession_team_name"),
    "play_pattern": ("play_pattern", "play_pattern_name", "phase"),
    "outcome": ("outcome", "outcome_name", "result"),
    "x": ("x", "start_x", "location_x"),
    "y": ("y", "start_y", "location_y"),
    "end_x": ("end_x", "target_x"),
    "end_y": ("end_y", "target_y"),
    "xg": ("xg", "statsbomb_xg", "expected_goals"),
    "is_goal": ("is_goal", "goal"),
    "is_set_piece": ("is_set_piece", "set_piece"),
    "is_counterattack": ("is_counterattack", "counterattack", "counter_attack"),
    "under_pressure": ("under_pressure", "pressured"),
    "body_part": ("body_part", "body_part_name"),
    "card_type": ("card_type", "card"),
    "substitution_replacement": ("substitution_replacement", "replacement", "replacement_name"),
    "goalkeeper": ("goalkeeper", "keeper", "keeper_name"),
    "source": ("source", "provider"),
    "source_confidence": ("source_confidence", "confidence"),
    "updated_at": ("updated_at", "fetched_at"),
}

OPTIONAL_FIELDS_BY_TYPE: dict[MatchEventType, tuple[str, ...]] = {
    MatchEventType.SHOT: ("player", "x", "y", "xg", "outcome"),
    MatchEventType.GOAL: ("player", "x", "y", "xg"),
    MatchEventType.PENALTY: ("player", "xg", "outcome"),
    MatchEventType.SAVE: ("goalkeeper", "xg", "outcome"),
    MatchEventType.PASS: ("player", "x", "y", "end_x", "end_y"),
    MatchEventType.KEY_PASS: ("player", "x", "y", "end_x", "end_y"),
    MatchEventType.PROGRESSIVE_PASS: ("player", "x", "y", "end_x", "end_y"),
    MatchEventType.CARRY: ("player", "x", "y", "end_x", "end_y"),
    MatchEventType.PROGRESSIVE_CARRY: ("player", "x", "y", "end_x", "end_y"),
    MatchEventType.CROSS: ("player", "x", "y", "end_x", "end_y"),
    MatchEventType.CARD: ("player", "card_type"),
    MatchEventType.SUBSTITUTION: ("player", "substitution_replacement"),
}


class MatchEvent(StrictModel):
    event_id: str = Field(min_length=1)
    match_id: str = Field(min_length=1)
    match_date: date | None = None
    competition: str = ""
    team: str = Field(min_length=1)
    opponent: str = ""
    player: str = ""
    related_player: str = ""
    event_type: MatchEventType
    period: int = Field(default=1, ge=1, le=5)
    minute: int = Field(ge=0, le=130)
    second: float = Field(default=0, ge=0, lt=60)
    possession_id: str = ""
    possession_team: str = ""
    play_pattern: str = ""
    outcome: str = ""
    x: float | None = Field(default=None, ge=0, le=120)
    y: float | None = Field(default=None, ge=0, le=80)
    end_x: float | None = Field(default=None, ge=0, le=120)
    end_y: float | None = Field(default=None, ge=0, le=80)
    xg: float | None = Field(default=None, ge=0, le=1)
    is_goal: bool = False
    is_set_piece: bool = False
    is_counterattack: bool = False
    under_pressure: bool = False
    body_part: str = ""
    card_type: str = ""
    substitution_replacement: str = ""
    goalkeeper: str = ""
    source: str = Field(min_length=1)
    source_event_type: str = Field(min_length=1)
    source_confidence: float = Field(ge=0, le=1)
    updated_at: datetime

    _updated_at_aware = field_validator("updated_at")(_aware)


class MatchSummarySignal(StrictModel):
    match_id: str = Field(min_length=1)
    match_date: date | None = None
    team: str = Field(min_length=1)
    opponent: str = ""
    goals: int = Field(ge=0)
    xg: float = Field(ge=0)
    shots: int = Field(ge=0)
    shots_on_target: int = Field(ge=0)
    field_tilt: float = Field(ge=0, le=1)
    attacking_third_actions: int = Field(ge=0)
    box_entries: int = Field(ge=0)
    set_piece_xg: float = Field(ge=0)
    counterattack_xg: float = Field(ge=0)
    pressing_actions: int = Field(ge=0)
    high_pressing_actions: int = Field(ge=0)
    pressing_proxy: float = Field(ge=0)
    goalkeeper_saves: int = Field(ge=0)
    xg_faced: float = Field(ge=0)
    goals_conceded: int = Field(ge=0)
    goalkeeper_impact: float
    event_count: int = Field(ge=0)
    source: str = Field(min_length=1)
    data_quality: str = Field(min_length=1)
    updated_at: datetime

    _updated_at_aware = field_validator("updated_at")(_aware)


MATCH_EVENT_FIELDS = list(MatchEvent.model_fields)
MATCH_SUMMARY_FIELDS = list(MatchSummarySignal.model_fields)
SHOT_TYPES = {MatchEventType.SHOT, MatchEventType.GOAL, MatchEventType.PENALTY}
MOVEMENT_TYPES = {
    MatchEventType.PASS,
    MatchEventType.KEY_PASS,
    MatchEventType.PROGRESSIVE_PASS,
    MatchEventType.CARRY,
    MatchEventType.PROGRESSIVE_CARRY,
    MatchEventType.CROSS,
}
PRESSING_TYPES = {
    MatchEventType.TACKLE,
    MatchEventType.INTERCEPTION,
    MatchEventType.DUEL,
    MatchEventType.AERIAL_DUEL,
    MatchEventType.FOUL,
}


@dataclass
class EventDataIngestionResult:
    events: list[MatchEvent] = field(default_factory=list)
    issues: list[DataQualityIssue] = field(default_factory=list)
    rows_raw: int = 0


class EventDataAdapter(Protocol):
    name: str

    def fetch(self) -> tuple[list[dict[str, str]], list[DataQualityIssue]]:
        ...

    def normalize(self, raw_rows: list[dict[str, str]]) -> EventDataIngestionResult:
        ...


def normalize_event_type(value: str) -> MatchEventType | None:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    return EVENT_TYPE_ALIASES.get(normalized)


def _first(row: dict[str, str], aliases: Iterable[str]) -> str:
    return next((row.get(alias, "") for alias in aliases if row.get(alias, "") != ""), "")


def _bool(value: Any) -> bool:
    return str(value or "").casefold() in {"1", "true", "yes", "y"}


def _optional_float(value: Any) -> float | None:
    return None if value in {None, ""} else float(value)


def _stable_event_id(row: dict[str, Any]) -> str:
    identity = "|".join(
        str(row.get(field, "")).strip()
        for field in ("match_id", "team", "event_type", "period", "minute", "second", "player", "x", "y")
    )
    return f"event_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}"


def _missing_optional_issues(event: MatchEvent, path: Path, row_number: int) -> list[DataQualityIssue]:
    issues = []
    payload = event.model_dump()
    for field_name in OPTIONAL_FIELDS_BY_TYPE.get(event.event_type, ()):
        if payload.get(field_name) in {None, ""}:
            issues.append(
                make_data_quality_issue(
                    file=path,
                    row_number=row_number,
                    severity=DataQualitySeverity.INFO,
                    field_name=field_name,
                    problem=f"Optional field {field_name!r} is missing for {event.event_type.value} event",
                    suggested_fix="Populate the field when the provider exposes it; the event remains usable without it.",
                )
            )
    return issues


class ManualCsvEventAdapter:
    """Map a manual or provider-export CSV into the normalized event contract."""

    name = "manual_csv"

    def __init__(
        self,
        path: Path,
        source_confidence: float = 0.7,
        field_aliases: dict[str, tuple[str, ...]] | None = None,
    ):
        self.path = path
        self.source_confidence = source_confidence
        self.field_aliases = {**DEFAULT_FIELD_ALIASES, **(field_aliases or {})}

    def fetch(self) -> tuple[list[dict[str, str]], list[DataQualityIssue]]:
        result = safe_read_csv(self.path)
        return result.rows, result.issues

    def normalize(self, raw_rows: list[dict[str, str]]) -> EventDataIngestionResult:
        result = EventDataIngestionResult(rows_raw=len(raw_rows))
        for row_number, raw in enumerate(raw_rows, start=2):
            mapped = {field_name: _first(raw, aliases) for field_name, aliases in self.field_aliases.items()}
            event_type = normalize_event_type(mapped["event_type"])
            if event_type is None:
                result.issues.append(
                    make_data_quality_issue(
                        file=self.path,
                        row_number=row_number,
                        severity=DataQualitySeverity.ERROR,
                        field_name="event_type",
                        problem=f"Unsupported event type: {mapped['event_type']!r}",
                        suggested_fix=f"Map the provider event to one of: {', '.join(item.value for item in MatchEventType)}.",
                    )
                )
                continue
            try:
                payload: dict[str, Any] = {
                    "event_id": mapped["event_id"] or _stable_event_id({**mapped, "event_type": event_type.value}),
                    "match_id": mapped["match_id"],
                    "match_date": mapped["match_date"] or None,
                    "competition": mapped["competition"],
                    "team": mapped["team"],
                    "opponent": mapped["opponent"],
                    "player": mapped["player"],
                    "related_player": mapped["related_player"],
                    "event_type": event_type,
                    "period": int(float(mapped["period"] or 1)),
                    "minute": int(float(mapped["minute"])),
                    "second": float(mapped["second"] or 0),
                    "possession_id": mapped["possession_id"],
                    "possession_team": mapped["possession_team"] or mapped["team"],
                    "play_pattern": mapped["play_pattern"],
                    "outcome": mapped["outcome"],
                    "x": _optional_float(mapped["x"]),
                    "y": _optional_float(mapped["y"]),
                    "end_x": _optional_float(mapped["end_x"]),
                    "end_y": _optional_float(mapped["end_y"]),
                    "xg": _optional_float(mapped["xg"]),
                    "is_goal": _bool(mapped["is_goal"]) or event_type == MatchEventType.GOAL,
                    "is_set_piece": _bool(mapped["is_set_piece"]) or event_type in {MatchEventType.SET_PIECE, MatchEventType.CORNER, MatchEventType.PENALTY},
                    "is_counterattack": _bool(mapped["is_counterattack"]),
                    "under_pressure": _bool(mapped["under_pressure"]),
                    "body_part": mapped["body_part"],
                    "card_type": mapped["card_type"],
                    "substitution_replacement": mapped["substitution_replacement"],
                    "goalkeeper": mapped["goalkeeper"],
                    "source": mapped["source"] or self.name,
                    "source_event_type": mapped["event_type"],
                    "source_confidence": float(mapped["source_confidence"] or self.source_confidence),
                    "updated_at": mapped["updated_at"] or datetime.now(timezone.utc).isoformat(),
                }
            except (TypeError, ValueError) as exc:
                result.issues.append(
                    make_data_quality_issue(
                        file=self.path,
                        row_number=row_number,
                        severity=DataQualitySeverity.ERROR,
                        problem=f"Event values could not be parsed: {exc}",
                        raw_value=raw,
                        suggested_fix="Correct numeric, boolean, date, and timestamp values before retrying.",
                    )
                )
                continue
            validated = validate_rows([payload], MatchEvent, file=self.path, starting_row_number=row_number)
            result.issues.extend(validated.issues)
            if validated.valid_records:
                event = validated.valid_records[0]
                result.events.append(event)
                result.issues.extend(_missing_optional_issues(event, self.path, row_number))
        return result


def ingest_event_data(adapter: EventDataAdapter) -> EventDataIngestionResult:
    rows, read_issues = adapter.fetch()
    result = adapter.normalize(rows)
    result.issues = [*read_issues, *result.issues]
    return result


def _row(model: BaseModel, fields: list[str]) -> dict[str, Any]:
    payload = model.model_dump(mode="json")
    return {field: "" if payload.get(field) is None else payload.get(field, "") for field in fields}


def write_normalized_events(
    events: list[MatchEvent],
    path: Path = MATCH_EVENTS_NORMALIZED_PATH,
) -> list[DataQualityIssue]:
    return safe_write_csv(path, [_row(event, MATCH_EVENT_FIELDS) for event in events], MATCH_EVENT_FIELDS).issues


def load_normalized_events(
    path: Path = MATCH_EVENTS_NORMALIZED_PATH,
) -> tuple[list[MatchEvent], list[DataQualityIssue]]:
    read = safe_read_csv(path, MATCH_EVENT_FIELDS)
    optional = {"match_date", "x", "y", "end_x", "end_y", "xg"}
    rows = [{**row, **{field: row.get(field) or None for field in optional}} for row in read.rows]
    validated = validate_rows(rows, MatchEvent, file=path)
    return validated.valid_records, [*read.issues, *validated.issues]


def _is_attacking_third_action(event: MatchEvent) -> bool:
    return event.event_type in MOVEMENT_TYPES | SHOT_TYPES and max(event.x or 0, event.end_x or 0) >= 80


def _is_box_entry(event: MatchEvent) -> bool:
    if event.event_type not in MOVEMENT_TYPES or event.end_x is None or event.end_y is None:
        return False
    starts_in_box = event.x is not None and event.y is not None and event.x >= 102 and 18 <= event.y <= 62
    ends_in_box = event.end_x >= 102 and 18 <= event.end_y <= 62
    return ends_in_box and not starts_in_box


def build_match_summary_signals(
    events: list[MatchEvent],
    *,
    updated_at: datetime | None = None,
) -> list[MatchSummarySignal]:
    """Aggregate one transparent team summary per match without affecting predictions."""
    updated = updated_at or datetime.now(timezone.utc)
    grouped: defaultdict[tuple[str, str], list[MatchEvent]] = defaultdict(list)
    teams_by_match: defaultdict[str, set[str]] = defaultdict(set)
    for event in events:
        grouped[(event.match_id, event.team)].append(event)
        teams_by_match[event.match_id].add(event.team)

    output = []
    for (match_id, team), rows in grouped.items():
        opponents = sorted(teams_by_match[match_id] - {team})
        opponent = rows[0].opponent or (opponents[0] if len(opponents) == 1 else "")
        opponent_rows = [event for opponent_team in opponents for event in grouped.get((match_id, opponent_team), [])]
        shots = [event for event in rows if event.event_type in SHOT_TYPES]
        conceded_shots = [event for event in opponent_rows if event.event_type in SHOT_TYPES]
        attacking_actions = sum(_is_attacking_third_action(event) for event in rows)
        opponent_attacking_actions = sum(_is_attacking_third_action(event) for event in opponent_rows)
        field_tilt_denominator = attacking_actions + opponent_attacking_actions
        pressing_actions = [event for event in rows if event.event_type in PRESSING_TYPES]
        high_pressing_actions = [event for event in pressing_actions if (event.x or 0) >= 80]
        opponent_build_actions = sum(event.event_type in MOVEMENT_TYPES for event in opponent_rows)
        saves = sum(event.event_type == MatchEventType.SAVE for event in rows)
        goals_conceded = sum(event.is_goal for event in conceded_shots)
        xg_faced = sum(event.xg or 0 for event in conceded_shots)
        sources = sorted({event.source for event in rows})
        xg_coverage = sum(event.xg is not None for event in shots)
        output.append(
            MatchSummarySignal(
                match_id=match_id,
                match_date=next((event.match_date for event in rows if event.match_date), None),
                team=team,
                opponent=opponent,
                goals=sum(event.is_goal for event in shots),
                xg=round(sum(event.xg or 0 for event in shots), 3),
                shots=len(shots),
                shots_on_target=sum(
                    event.is_goal or event.outcome.casefold() in {"saved", "saved to post", "goal"} for event in shots
                ),
                field_tilt=round(attacking_actions / field_tilt_denominator, 3) if field_tilt_denominator else 0.5,
                attacking_third_actions=attacking_actions,
                box_entries=sum(_is_box_entry(event) for event in rows),
                set_piece_xg=round(sum((event.xg or 0) for event in shots if event.is_set_piece), 3),
                counterattack_xg=round(sum((event.xg or 0) for event in shots if event.is_counterattack), 3),
                pressing_actions=len(pressing_actions),
                high_pressing_actions=len(high_pressing_actions),
                pressing_proxy=round(
                    min(100.0, (len(high_pressing_actions) + (0.5 * len(pressing_actions))) * 100 / max(opponent_build_actions, 1)),
                    3,
                ),
                goalkeeper_saves=saves,
                xg_faced=round(xg_faced, 3),
                goals_conceded=goals_conceded,
                goalkeeper_impact=round(xg_faced - goals_conceded, 3),
                event_count=len(rows),
                source="|".join(sources),
                data_quality="observed_events_with_xg" if xg_coverage == len(shots) else "observed_events_partial_xg",
                updated_at=updated,
            )
        )
    return sorted(output, key=lambda item: (item.match_id, item.team))


def write_match_summary_signals(
    signals: list[MatchSummarySignal],
    path: Path = MATCH_SUMMARY_SIGNALS_PATH,
) -> list[DataQualityIssue]:
    return safe_write_csv(path, [_row(signal, MATCH_SUMMARY_FIELDS) for signal in signals], MATCH_SUMMARY_FIELDS).issues


def load_match_summary_signals(
    path: Path = MATCH_SUMMARY_SIGNALS_PATH,
) -> tuple[list[MatchSummarySignal], list[DataQualityIssue]]:
    read = safe_read_csv(path, MATCH_SUMMARY_FIELDS)
    rows = [{**row, "match_date": row.get("match_date") or None} for row in read.rows]
    validated = validate_rows(rows, MatchSummarySignal, file=path)
    return validated.valid_records, [*read.issues, *validated.issues]
