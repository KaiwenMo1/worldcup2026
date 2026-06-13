"""Manual-first player-stat ingestion and transparent role-vector derivation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ingestion.normalizers import (
    make_data_quality_issue,
    safe_read_csv,
    safe_write_csv,
    validate_rows,
)
from app.ingestion.schemas import DataQualityIssue, DataQualitySeverity


ROOT = Path(__file__).resolve().parents[2]
MANUAL_SAMPLE_PATH = ROOT / "data" / "raw" / "player_stats" / "manual_player_stats_sample.csv"
SEASON_STATS_PATH = ROOT / "data" / "normalized" / "player_season_stats_normalized.csv"
MATCH_STATS_PATH = ROOT / "data" / "normalized" / "player_match_stats_normalized.csv"
ROLE_VECTORS_PATH = ROOT / "data" / "derived" / "player_role_vectors.csv"
FORM_SIGNALS_PATH = ROOT / "data" / "derived" / "player_form_signals.csv"
CURATED_PROFILES_PATH = ROOT / "data" / "player_profiles.csv"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("updated_at must include a timezone")
    return value


class PlayerSeasonStat(StrictModel):
    player_id: str = Field(min_length=1)
    player: str = Field(min_length=1)
    team: str = Field(min_length=1)
    national_team: str = ""
    club: str = ""
    season: str = Field(min_length=1)
    competition: str = Field(min_length=1)
    position: str = Field(min_length=1)
    minutes: float = Field(ge=0)
    goals: float = Field(default=0, ge=0)
    assists: float = Field(default=0, ge=0)
    shots: float = Field(default=0, ge=0)
    shots_on_target: float = Field(default=0, ge=0)
    xg: float = Field(default=0, ge=0)
    xa: float = Field(default=0, ge=0)
    key_passes: float = Field(default=0, ge=0)
    progressive_passes: float = Field(default=0, ge=0)
    progressive_carries: float = Field(default=0, ge=0)
    passes_completed: float = Field(default=0, ge=0)
    passes_attempted: float = Field(default=0, ge=0)
    pass_completion: float = Field(default=0, ge=0, le=1)
    dribbles_completed: float = Field(default=0, ge=0)
    dribbles_attempted: float = Field(default=0, ge=0)
    tackles: float = Field(default=0, ge=0)
    interceptions: float = Field(default=0, ge=0)
    pressures: float = Field(default=0, ge=0)
    aerials_won: float = Field(default=0, ge=0)
    aerials_lost: float = Field(default=0, ge=0)
    yellow_cards: float = Field(default=0, ge=0)
    red_cards: float = Field(default=0, ge=0)
    saves: float = Field(default=0, ge=0)
    goals_conceded: float = Field(default=0, ge=0)
    source: str = Field(min_length=1)
    source_confidence: float = Field(ge=0, le=1)
    updated_at: datetime

    _updated_at_aware = field_validator("updated_at")(_aware)


class PlayerMatchStat(StrictModel):
    match_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    player: str = Field(min_length=1)
    team: str = Field(min_length=1)
    opponent: str = Field(min_length=1)
    date: date
    competition: str = Field(min_length=1)
    position: str = Field(min_length=1)
    started: bool = False
    minutes: float = Field(ge=0, le=130)
    goals: float = Field(default=0, ge=0)
    assists: float = Field(default=0, ge=0)
    xg: float = Field(default=0, ge=0)
    xa: float = Field(default=0, ge=0)
    shots: float = Field(default=0, ge=0)
    shots_on_target: float = Field(default=0, ge=0)
    key_passes: float = Field(default=0, ge=0)
    progressive_passes: float = Field(default=0, ge=0)
    progressive_carries: float = Field(default=0, ge=0)
    duels_won: float = Field(default=0, ge=0)
    duels_lost: float = Field(default=0, ge=0)
    pressures: float = Field(default=0, ge=0)
    tackles: float = Field(default=0, ge=0)
    interceptions: float = Field(default=0, ge=0)
    aerials_won: float = Field(default=0, ge=0)
    aerials_lost: float = Field(default=0, ge=0)
    saves: float = Field(default=0, ge=0)
    goals_conceded: float = Field(default=0, ge=0)
    source: str = Field(min_length=1)
    source_confidence: float = Field(ge=0, le=1)
    updated_at: datetime

    _updated_at_aware = field_validator("updated_at")(_aware)


class PlayerRoleVector(StrictModel):
    player_id: str
    player: str
    team: str
    position: str
    role_archetype: str
    role_fit_score: float = Field(ge=0, le=100)
    shooting_score: float = Field(ge=0, le=100)
    creation_score: float = Field(ge=0, le=100)
    progression_score: float = Field(ge=0, le=100)
    ball_retention_score: float = Field(ge=0, le=100)
    pressing_score: float = Field(ge=0, le=100)
    defending_score: float = Field(ge=0, le=100)
    aerial_score: float = Field(ge=0, le=100)
    transition_score: float = Field(ge=0, le=100)
    set_piece_score: float = Field(ge=0, le=100)
    form_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    source: str
    data_quality: str
    updated_at: datetime

    _updated_at_aware = field_validator("updated_at")(_aware)


class PlayerFormSignal(StrictModel):
    player_id: str
    player: str
    team: str
    recent_matches: int = Field(ge=0)
    recent_minutes: float = Field(ge=0)
    goals_per90: float = Field(ge=0)
    assists_per90: float = Field(ge=0)
    xg_per90: float = Field(ge=0)
    xa_per90: float = Field(ge=0)
    form_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    source: str
    data_quality: str
    updated_at: datetime

    _updated_at_aware = field_validator("updated_at")(_aware)


SEASON_FIELDS = list(PlayerSeasonStat.model_fields)
MATCH_FIELDS = list(PlayerMatchStat.model_fields)
ROLE_VECTOR_FIELDS = list(PlayerRoleVector.model_fields)
FORM_SIGNAL_FIELDS = list(PlayerFormSignal.model_fields)
RAW_REQUIRED_FIELDS = {"record_type", "player_id", "player", "team", "position"}


ROLE_WEIGHTS: dict[str, dict[str, float]] = {
    "inverted_winger": {"shooting": 0.25, "creation": 0.18, "progression": 0.18, "retention": 0.15, "transition": 0.24},
    "touchline_winger": {"creation": 0.28, "progression": 0.25, "retention": 0.18, "transition": 0.18, "pressing": 0.11},
    "direct_transition_winger": {"shooting": 0.20, "progression": 0.20, "transition": 0.35, "pressing": 0.15, "retention": 0.10},
    "pressing_winger": {"pressing": 0.35, "transition": 0.22, "progression": 0.18, "creation": 0.15, "shooting": 0.10},
    "target_striker": {"shooting": 0.34, "aerial": 0.34, "retention": 0.14, "creation": 0.10, "pressing": 0.08},
    "false_nine": {"creation": 0.28, "retention": 0.25, "shooting": 0.20, "progression": 0.17, "pressing": 0.10},
    "poacher": {"shooting": 0.62, "transition": 0.18, "aerial": 0.12, "retention": 0.08},
    "box_to_box_midfielder": {"progression": 0.20, "pressing": 0.20, "defending": 0.20, "transition": 0.16, "creation": 0.12, "retention": 0.12},
    "deep_lying_playmaker": {"retention": 0.32, "progression": 0.30, "creation": 0.18, "defending": 0.12, "pressing": 0.08},
    "ball_winning_midfielder": {"defending": 0.38, "pressing": 0.28, "aerial": 0.12, "retention": 0.12, "progression": 0.10},
    "attacking_midfielder": {"creation": 0.33, "shooting": 0.22, "progression": 0.20, "retention": 0.15, "transition": 0.10},
    "overlapping_fullback": {"progression": 0.27, "creation": 0.22, "transition": 0.16, "pressing": 0.14, "defending": 0.13, "retention": 0.08},
    "inverted_fullback": {"retention": 0.28, "progression": 0.25, "defending": 0.18, "pressing": 0.14, "creation": 0.10, "transition": 0.05},
    "defensive_fullback": {"defending": 0.40, "pressing": 0.18, "aerial": 0.14, "retention": 0.14, "progression": 0.14},
    "ball_playing_centerback": {"retention": 0.27, "progression": 0.25, "defending": 0.25, "aerial": 0.15, "pressing": 0.08},
    "stopper_centerback": {"defending": 0.48, "aerial": 0.28, "pressing": 0.12, "retention": 0.07, "progression": 0.05},
    "sweeper_keeper": {"retention": 0.30, "progression": 0.25, "defending": 0.20, "transition": 0.15, "aerial": 0.10},
    "shot_stopper": {"defending": 0.65, "aerial": 0.15, "retention": 0.10, "transition": 0.10},
}
POSITION_ROLES = {
    "GK": {"sweeper_keeper", "shot_stopper"},
    "DF": {"overlapping_fullback", "inverted_fullback", "defensive_fullback", "ball_playing_centerback", "stopper_centerback"},
    "MF": {"box_to_box_midfielder", "deep_lying_playmaker", "ball_winning_midfielder", "attacking_midfielder"},
    "FW": {"inverted_winger", "touchline_winger", "direct_transition_winger", "pressing_winger", "target_striker", "false_nine", "poacher"},
}
FALLBACK_ROLE_ALIASES = {
    "inside_forward": "inverted_winger",
    "wide_creator": "touchline_winger",
    "mobile_striker": "false_nine",
    "transition_target": "target_striker",
    "build_up_keeper": "sweeper_keeper",
    "centre_back": "ball_playing_centerback",
    "center_back": "ball_playing_centerback",
}


@dataclass
class PlayerStatsIngestionResult:
    season_stats: list[PlayerSeasonStat] = field(default_factory=list)
    match_stats: list[PlayerMatchStat] = field(default_factory=list)
    issues: list[DataQualityIssue] = field(default_factory=list)
    rows_raw: int = 0


class PlayerStatsAdapter(Protocol):
    name: str

    def fetch(self) -> tuple[list[dict[str, str]], list[DataQualityIssue]]:
        ...

    def normalize(self, raw_rows: list[dict[str, str]]) -> PlayerStatsIngestionResult:
        ...


def _compact(row: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    return {field: row[field] for field in fields if row.get(field) not in {None, ""}}


def _bool(value: Any) -> bool:
    return str(value or "").casefold() in {"1", "true", "yes", "y"}


class ManualCsvPlayerStatsAdapter:
    name = "manual_csv"

    def __init__(self, path: Path, source_confidence: float = 0.7):
        self.path = path
        self.source_confidence = source_confidence

    def fetch(self) -> tuple[list[dict[str, str]], list[DataQualityIssue]]:
        result = safe_read_csv(self.path, RAW_REQUIRED_FIELDS)
        return result.rows, result.issues

    def normalize(self, raw_rows: list[dict[str, str]]) -> PlayerStatsIngestionResult:
        result = PlayerStatsIngestionResult(rows_raw=len(raw_rows))
        for row_number, row in enumerate(raw_rows, start=2):
            record_type = row.get("record_type", "").casefold()
            fields = SEASON_FIELDS if record_type == "season" else MATCH_FIELDS if record_type == "match" else []
            if not fields:
                result.issues.append(
                    make_data_quality_issue(
                        file=self.path,
                        row_number=row_number,
                        severity=DataQualitySeverity.ERROR,
                        field_name="record_type",
                        problem=f"Unsupported player-stat record_type: {row.get('record_type')!r}",
                        suggested_fix="Use record_type season or match.",
                    )
                )
                continue
            payload = _compact(row, fields)
            payload.setdefault("source", self.name)
            payload.setdefault("source_confidence", self.source_confidence)
            payload.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
            if record_type == "match" and "started" in payload:
                payload["started"] = _bool(payload["started"])
            model = PlayerSeasonStat if record_type == "season" else PlayerMatchStat
            validated = validate_rows([payload], model, file=self.path, starting_row_number=row_number)
            result.issues.extend(validated.issues)
            if validated.valid_records:
                if record_type == "season":
                    result.season_stats.append(validated.valid_records[0])
                else:
                    result.match_stats.append(validated.valid_records[0])
        return result


def ingest_player_stats(adapter: PlayerStatsAdapter) -> PlayerStatsIngestionResult:
    rows, read_issues = adapter.fetch()
    result = adapter.normalize(rows)
    result.issues = [*read_issues, *result.issues]
    return result


def _row(model: BaseModel, fields: list[str]) -> dict[str, Any]:
    payload = model.model_dump(mode="json")
    return {field: "" if payload.get(field) is None else payload.get(field, "") for field in fields}


def write_normalized_stats(
    result: PlayerStatsIngestionResult,
    season_path: Path = SEASON_STATS_PATH,
    match_path: Path = MATCH_STATS_PATH,
) -> list[DataQualityIssue]:
    season_write = safe_write_csv(season_path, [_row(item, SEASON_FIELDS) for item in result.season_stats], SEASON_FIELDS)
    match_write = safe_write_csv(match_path, [_row(item, MATCH_FIELDS) for item in result.match_stats], MATCH_FIELDS)
    return [*season_write.issues, *match_write.issues]


def load_normalized_season_stats(path: Path = SEASON_STATS_PATH) -> tuple[list[PlayerSeasonStat], list[DataQualityIssue]]:
    read = safe_read_csv(path, SEASON_FIELDS)
    validated = validate_rows(read.rows, PlayerSeasonStat, file=path)
    return validated.valid_records, [*read.issues, *validated.issues]


def load_normalized_match_stats(path: Path = MATCH_STATS_PATH) -> tuple[list[PlayerMatchStat], list[DataQualityIssue]]:
    read = safe_read_csv(path, MATCH_FIELDS)
    validated = validate_rows(read.rows, PlayerMatchStat, file=path)
    return validated.valid_records, [*read.issues, *validated.issues]


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def _per90(value: float, minutes: float) -> float:
    return value * 90 / minutes if minutes > 0 else 0.0


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator > 0 else 0.0


def _position_group(position: str) -> str:
    value = position.casefold().replace("-", " ").replace("_", " ").strip()
    compact = value.replace(" ", "")
    if "goal" in value or compact in {"gk", "keeper"}:
        return "GK"
    if compact in {"cb", "lcb", "rcb", "lb", "rb", "lwb", "rwb", "df"} or any(
        token in value for token in ("back", "defender", "centre half", "center half")
    ):
        return "DF"
    if compact in {"cm", "dm", "am", "cdm", "cam", "lm", "rm", "mf"} or any(
        token in value for token in ("midfield", "midfielder", "playmaker")
    ):
        return "MF"
    return "FW"


def _season_dimensions(stat: PlayerSeasonStat) -> dict[str, float]:
    minutes = max(stat.minutes, 1)
    goals_p90 = _per90(stat.goals, minutes)
    assists_p90 = _per90(stat.assists, minutes)
    xg_p90 = _per90(stat.xg, minutes)
    xa_p90 = _per90(stat.xa, minutes)
    shots_p90 = _per90(stat.shots, minutes)
    sot_p90 = _per90(stat.shots_on_target, minutes)
    key_passes_p90 = _per90(stat.key_passes, minutes)
    progressive_passes_p90 = _per90(stat.progressive_passes, minutes)
    progressive_carries_p90 = _per90(stat.progressive_carries, minutes)
    pressures_p90 = _per90(stat.pressures, minutes)
    defending_p90 = _per90(stat.tackles + stat.interceptions, minutes)
    aerial_rate = _ratio(stat.aerials_won, stat.aerials_won + stat.aerials_lost)
    dribble_rate = _ratio(stat.dribbles_completed, stat.dribbles_attempted)
    save_rate = _ratio(stat.saves, stat.saves + stat.goals_conceded)
    goalkeeper = _position_group(stat.position) == "GK"
    return {
        "shooting": _clamp(45 * goals_p90 / 0.8 + 35 * xg_p90 / 0.8 + 12 * sot_p90 / 2.0 + 8 * shots_p90 / 4.0),
        "creation": _clamp(35 * assists_p90 / 0.5 + 35 * xa_p90 / 0.5 + 30 * key_passes_p90 / 3.0),
        "progression": _clamp(55 * progressive_passes_p90 / 8.0 + 45 * progressive_carries_p90 / 5.0),
        "retention": _clamp(70 * stat.pass_completion + 30 * dribble_rate),
        "pressing": _clamp(100 * pressures_p90 / 20.0),
        "defending": _clamp(100 * save_rate if goalkeeper else 80 * defending_p90 / 5.0 + 20 * aerial_rate),
        "aerial": _clamp(100 * aerial_rate),
        "transition": _clamp(60 * progressive_carries_p90 / 5.0 + 25 * progressive_passes_p90 / 8.0 + 15 * goals_p90 / 0.8),
        "set_piece": _clamp(55 * xa_p90 / 0.5 + 45 * key_passes_p90 / 3.0),
    }


def _fallback_dimensions(row: dict[str, str]) -> dict[str, float]:
    number = lambda key, default=50.0: float(row.get(key) or default)
    return {
        "shooting": number("finishing"),
        "creation": number("chance_creation"),
        "progression": number("progression"),
        "retention": mean([number("passing"), number("dribbling"), number("press_resistance")]),
        "pressing": number("pressing"),
        "defending": mean([number("tackling"), number("recovery")]),
        "aerial": number("aerial"),
        "transition": mean([number("pace"), number("progression"), number("dribbling")]),
        "set_piece": number("set_piece_delivery"),
    }


def _role_scores(position: str, dimensions: dict[str, float]) -> list[tuple[str, float]]:
    allowed = POSITION_ROLES[_position_group(position)]
    scores = []
    for role in sorted(allowed):
        score = sum(dimensions[dimension] * weight for dimension, weight in ROLE_WEIGHTS[role].items())
        scores.append((role, round(score, 2)))
    return sorted(scores, key=lambda item: item[1], reverse=True)


def _form_score(goals_p90: float, assists_p90: float, xg_p90: float, xa_p90: float, activity_p90: float) -> float:
    return _clamp(
        35
        + 24 * goals_p90 / 0.8
        + 14 * assists_p90 / 0.5
        + 12 * xg_p90 / 0.8
        + 8 * xa_p90 / 0.5
        + 7 * activity_p90 / 10
    )


def build_form_signals(
    match_stats: list[PlayerMatchStat],
    season_stats: list[PlayerSeasonStat] | None = None,
    *,
    updated_at: datetime | None = None,
) -> list[PlayerFormSignal]:
    updated = updated_at or datetime.now(timezone.utc)
    grouped: defaultdict[str, list[PlayerMatchStat]] = defaultdict(list)
    for stat in match_stats:
        grouped[stat.player_id].append(stat)
    output: dict[str, PlayerFormSignal] = {}
    for player_id, rows in grouped.items():
        recent = sorted(rows, key=lambda item: item.date, reverse=True)[:5]
        minutes = sum(item.minutes for item in recent)
        goals_p90 = _per90(sum(item.goals for item in recent), minutes)
        assists_p90 = _per90(sum(item.assists for item in recent), minutes)
        xg_p90 = _per90(sum(item.xg for item in recent), minutes)
        xa_p90 = _per90(sum(item.xa for item in recent), minutes)
        activity = _per90(
            sum(item.key_passes + item.progressive_passes + item.progressive_carries + item.tackles + item.interceptions for item in recent),
            minutes,
        )
        output[player_id] = PlayerFormSignal(
            player_id=player_id,
            player=recent[0].player,
            team=recent[0].team,
            recent_matches=len(recent),
            recent_minutes=round(minutes, 2),
            goals_per90=round(goals_p90, 3),
            assists_per90=round(assists_p90, 3),
            xg_per90=round(xg_p90, 3),
            xa_per90=round(xa_p90, 3),
            form_score=_form_score(goals_p90, assists_p90, xg_p90, xa_p90, activity),
            confidence=round(mean(item.source_confidence for item in recent) * min(len(recent) / 5, 1), 3),
            source="normalized_player_match_stats",
            data_quality="observed_recent_matches",
            updated_at=updated,
        )
    for stat in season_stats or []:
        if stat.player_id in output:
            continue
        minutes = max(stat.minutes, 1)
        goals_p90 = _per90(stat.goals, minutes)
        assists_p90 = _per90(stat.assists, minutes)
        xg_p90 = _per90(stat.xg, minutes)
        xa_p90 = _per90(stat.xa, minutes)
        activity = _per90(stat.key_passes + stat.progressive_passes + stat.progressive_carries + stat.tackles + stat.interceptions, minutes)
        output[stat.player_id] = PlayerFormSignal(
            player_id=stat.player_id,
            player=stat.player,
            team=stat.team,
            recent_matches=0,
            recent_minutes=round(stat.minutes, 2),
            goals_per90=round(goals_p90, 3),
            assists_per90=round(assists_p90, 3),
            xg_per90=round(xg_p90, 3),
            xa_per90=round(xa_p90, 3),
            form_score=_form_score(goals_p90, assists_p90, xg_p90, xa_p90, activity),
            confidence=round(stat.source_confidence * 0.45, 3),
            source=stat.source,
            data_quality="observed_season_baseline",
            updated_at=updated,
        )
    return sorted(output.values(), key=lambda item: (item.team, item.player))


def build_role_vectors(
    season_stats: list[PlayerSeasonStat],
    form_signals: list[PlayerFormSignal],
    *,
    curated_profiles_path: Path = CURATED_PROFILES_PATH,
    updated_at: datetime | None = None,
) -> tuple[list[PlayerRoleVector], list[DataQualityIssue]]:
    updated = updated_at or datetime.now(timezone.utc)
    form_by_player = {signal.player_id: signal for signal in form_signals}
    vectors: list[PlayerRoleVector] = []
    observed_ids = set()
    for stat in season_stats:
        observed_ids.add(stat.player_id)
        dimensions = _season_dimensions(stat)
        form = form_by_player.get(stat.player_id)
        for role, fit in _role_scores(stat.position, dimensions)[:3]:
            vectors.append(
                PlayerRoleVector(
                    player_id=stat.player_id,
                    player=stat.player,
                    team=stat.team,
                    position=stat.position,
                    role_archetype=role,
                    role_fit_score=fit,
                    shooting_score=dimensions["shooting"],
                    creation_score=dimensions["creation"],
                    progression_score=dimensions["progression"],
                    ball_retention_score=dimensions["retention"],
                    pressing_score=dimensions["pressing"],
                    defending_score=dimensions["defending"],
                    aerial_score=dimensions["aerial"],
                    transition_score=dimensions["transition"],
                    set_piece_score=dimensions["set_piece"],
                    form_score=form.form_score if form else 50.0,
                    confidence=round(stat.source_confidence * min(stat.minutes / 900, 1), 3),
                    source=stat.source,
                    data_quality="observed_season_stats",
                    updated_at=updated,
                )
            )
    curated = safe_read_csv(curated_profiles_path, {"player_id", "player", "team", "primary_position", "role_archetypes"})
    for row in curated.rows:
        if row["player_id"] in observed_ids:
            continue
        dimensions = _fallback_dimensions(row)
        preferred = list(
            dict.fromkeys(
                FALLBACK_ROLE_ALIASES.get(item.strip().casefold().replace(" ", "_"), item.strip().casefold().replace(" ", "_"))
                for item in row.get("role_archetypes", "").split("|")
                if item.strip()
            )
        )
        allowed = POSITION_ROLES[_position_group(row["primary_position"])]
        preferred = [role for role in preferred if role in allowed]
        roles = preferred or [role for role, _ in _role_scores(row["primary_position"], dimensions)[:2]]
        fit_by_role = dict(_role_scores(row["primary_position"], dimensions))
        for role in roles[:3]:
            vectors.append(
                PlayerRoleVector(
                    player_id=row["player_id"],
                    player=row["player"],
                    team=row["team"],
                    position=row["primary_position"],
                    role_archetype=role,
                    role_fit_score=fit_by_role[role],
                    shooting_score=_clamp(dimensions["shooting"]),
                    creation_score=_clamp(dimensions["creation"]),
                    progression_score=_clamp(dimensions["progression"]),
                    ball_retention_score=_clamp(dimensions["retention"]),
                    pressing_score=_clamp(dimensions["pressing"]),
                    defending_score=_clamp(dimensions["defending"]),
                    aerial_score=_clamp(dimensions["aerial"]),
                    transition_score=_clamp(dimensions["transition"]),
                    set_piece_score=_clamp(dimensions["set_piece"]),
                    form_score=50.0,
                    confidence=0.3,
                    source=row.get("source") or "manual_player_profile",
                    data_quality="manual_profile_fallback",
                    updated_at=updated,
                )
            )
    return sorted(vectors, key=lambda item: (item.team, item.player, -item.role_fit_score)), curated.issues


def write_derived_outputs(
    vectors: list[PlayerRoleVector],
    signals: list[PlayerFormSignal],
    role_path: Path = ROLE_VECTORS_PATH,
    form_path: Path = FORM_SIGNALS_PATH,
) -> list[DataQualityIssue]:
    roles = safe_write_csv(role_path, [_row(item, ROLE_VECTOR_FIELDS) for item in vectors], ROLE_VECTOR_FIELDS)
    forms = safe_write_csv(form_path, [_row(item, FORM_SIGNAL_FIELDS) for item in signals], FORM_SIGNAL_FIELDS)
    return [*roles.issues, *forms.issues]
