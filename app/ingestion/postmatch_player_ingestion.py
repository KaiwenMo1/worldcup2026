"""Convert observed match events into player match stats, ratings, and live team features."""

from __future__ import annotations

import csv
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ingestion.event_data_ingestion import (
    MATCH_EVENTS_NORMALIZED_PATH,
    MatchEvent,
    MatchEventType,
    load_normalized_events,
)
from app.ingestion.normalizers import safe_read_csv, safe_write_csv, validate_rows
from app.ingestion.player_stats_ingestion import (
    FORM_SIGNALS_PATH,
    MATCH_FIELDS,
    MATCH_STATS_PATH,
    ROLE_VECTORS_PATH,
    SEASON_STATS_PATH,
    PlayerMatchStat,
    build_form_signals,
    build_role_vectors,
    load_normalized_match_stats,
    load_normalized_season_stats,
    write_derived_outputs,
)
from app.ingestion.schemas import DataQualityIssue


ROOT = Path(__file__).resolve().parents[2]
OBSERVED_MATCHES_PATH = ROOT / "data" / "observed_matches.csv"
ACTUAL_LINEUPS_PATH = ROOT / "data" / "normalized" / "actual_lineups_normalized.csv"
PLAYER_POSTMATCH_SIGNALS_PATH = ROOT / "data" / "derived" / "player_postmatch_signals.csv"
LIVE_PLAYER_TEAM_FEATURES_PATH = ROOT / "data" / "derived" / "live_player_team_features.csv"
BASE_PLAYER_TEAM_FEATURES_PATH = ROOT / "data" / "player_match_team_features.csv"

PLAYER_POSTMATCH_SIGNAL_FIELDS = [
    "match_id",
    "match_date",
    "player_id",
    "player",
    "team",
    "opponent",
    "position",
    "started",
    "minutes",
    "goals",
    "assists",
    "xg",
    "xa",
    "shots",
    "shots_on_target",
    "key_passes",
    "progressive_actions",
    "defensive_actions",
    "pressures",
    "saves",
    "goals_conceded",
    "cards",
    "player_rating",
    "attacking_impact",
    "creative_impact",
    "defensive_impact",
    "goalkeeper_impact",
    "discipline_risk",
    "stamina_load",
    "data_quality",
    "source",
    "updated_at",
]
LIVE_TEAM_FEATURE_FIELDS = [
    "team",
    "recent_form",
    "player_shooting_score",
    "player_chance_creation_score",
    "player_passing_score",
    "player_progression_score",
    "player_pressing_score",
    "player_defensive_activity_score",
    "player_goalkeeping_score",
    "player_keeper_sweeping_score",
    "player_keeper_diving_score",
    "player_set_piece_delivery_score",
    "player_early_goal_score",
    "player_late_goal_score",
    "player_discipline_score",
    "player_minutes_score",
]


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


class PlayerPostmatchSignal(StrictModel):
    match_id: str = Field(min_length=1)
    match_date: date | None = None
    player_id: str = Field(min_length=1)
    player: str = Field(min_length=1)
    team: str = Field(min_length=1)
    opponent: str = ""
    position: str = ""
    started: bool = False
    minutes: float = Field(ge=0, le=130)
    goals: float = Field(default=0, ge=0)
    assists: float = Field(default=0, ge=0)
    xg: float = Field(default=0, ge=0)
    xa: float = Field(default=0, ge=0)
    shots: float = Field(default=0, ge=0)
    shots_on_target: float = Field(default=0, ge=0)
    key_passes: float = Field(default=0, ge=0)
    progressive_actions: float = Field(default=0, ge=0)
    defensive_actions: float = Field(default=0, ge=0)
    pressures: float = Field(default=0, ge=0)
    saves: float = Field(default=0, ge=0)
    goals_conceded: float = Field(default=0, ge=0)
    cards: float = Field(default=0, ge=0)
    player_rating: float = Field(ge=0, le=10)
    attacking_impact: float
    creative_impact: float
    defensive_impact: float
    goalkeeper_impact: float
    discipline_risk: float = Field(ge=0, le=100)
    stamina_load: float = Field(ge=0, le=100)
    data_quality: str = Field(min_length=1)
    source: str = Field(min_length=1)
    updated_at: datetime

    _updated_at_aware = field_validator("updated_at")(_aware)


@dataclass
class PostmatchPlayerUpdateResult:
    event_rows: int = 0
    lineup_rows: int = 0
    derived_match_stats: int = 0
    merged_match_stats: int = 0
    player_postmatch_signals: int = 0
    player_form_signals: int = 0
    player_role_vectors: int = 0
    live_team_feature_rows: int = 0
    issues: list[DataQualityIssue] = field(default_factory=list)


ACTUAL_LINEUP_FIELDS = list(ActualLineupPlayer.model_fields)


def player_id_for(team: str, player: str) -> str:
    raw = unicodedata.normalize("NFKD", f"{team}_{player}").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", raw.casefold()).strip("_")


def _bool(value: Any, default: bool = False) -> bool:
    if value in {None, ""}:
        return default
    return str(value).casefold() in {"1", "true", "yes", "y"}


def load_actual_lineups(path: Path = ACTUAL_LINEUPS_PATH) -> tuple[list[ActualLineupPlayer], list[DataQualityIssue]]:
    read = safe_read_csv(path, ACTUAL_LINEUP_FIELDS)
    rows = []
    for row in read.rows:
        rows.append({**row, "starter": _bool(row.get("starter"), True), "confirmed": _bool(row.get("confirmed"), True)})
    validated = validate_rows(rows, ActualLineupPlayer, file=path)
    return validated.valid_records, [*read.issues, *validated.issues]


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def _round(value: float, digits: int = 3) -> float:
    return round(value, digits)


def _event_player(event: MatchEvent) -> str:
    if event.event_type == MatchEventType.SAVE and event.goalkeeper:
        return event.goalkeeper
    return event.player


def _event_player_id(event: MatchEvent, player: str | None = None) -> str:
    return player_id_for(event.team, player or _event_player(event))


def _observed_match_lookup(path: Path = OBSERVED_MATCHES_PATH) -> dict[str, dict[str, str]]:
    return {row.get("match_id", ""): row for row in safe_read_csv(path).rows if row.get("match_id")}


def _opponent_for(match: dict[str, str] | None, team: str, event: MatchEvent | None = None) -> str:
    if event and event.opponent:
        return event.opponent
    if not match:
        return event.opponent if event else ""
    if match.get("team_a") == team:
        return match.get("team_b", "")
    if match.get("team_b") == team:
        return match.get("team_a", "")
    return event.opponent if event else ""


def _goals_against(match: dict[str, str] | None, team: str) -> float:
    if not match:
        return 0.0
    try:
        if match.get("team_a") == team:
            return float(match.get("team_b_score") or 0)
        if match.get("team_b") == team:
            return float(match.get("team_a_score") or 0)
    except ValueError:
        return 0.0
    return 0.0


def _match_date(match: dict[str, str] | None, event: MatchEvent | None = None) -> date:
    if event and event.match_date:
        return event.match_date
    raw = (match or {}).get("kickoff_utc", "")[:10]
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return datetime.now(timezone.utc).date()


def _lineup_index(lineups: list[ActualLineupPlayer]) -> dict[tuple[str, str, str], ActualLineupPlayer]:
    return {(row.match_id, row.team.casefold(), row.player_id): row for row in lineups}


def _lineup_by_player_name(lineups: list[ActualLineupPlayer]) -> dict[tuple[str, str, str], ActualLineupPlayer]:
    return {
        (row.match_id, row.team.casefold(), row.player.casefold()): row
        for row in lineups
    }


def _match_lengths(events: list[MatchEvent]) -> dict[str, int]:
    lengths: dict[str, int] = defaultdict(lambda: 90)
    for event in events:
        lengths[event.match_id] = max(lengths[event.match_id], min(130, int(event.minute)))
    return lengths


def _minutes_and_starts(
    events: list[MatchEvent],
    lineups: list[ActualLineupPlayer],
) -> tuple[dict[tuple[str, str, str], float], dict[tuple[str, str, str], bool], dict[tuple[str, str, str], str]]:
    match_lengths = _match_lengths(events)
    minutes: dict[tuple[str, str, str], float] = {}
    starts: dict[tuple[str, str, str], bool] = {}
    positions: dict[tuple[str, str, str], str] = {}
    for row in lineups:
        key = (row.match_id, row.team.casefold(), row.player_id)
        minutes[key] = float(match_lengths.get(row.match_id, 90)) if row.starter else 0.0
        starts[key] = row.starter
        positions[key] = row.position

    for event in events:
        match_length = float(match_lengths.get(event.match_id, 90))
        if event.event_type != MatchEventType.SUBSTITUTION:
            player = _event_player(event)
            if player:
                key = (event.match_id, event.team.casefold(), _event_player_id(event, player))
                minutes.setdefault(key, max(1.0, min(match_length, match_length - min(float(event.minute), match_length) + 15.0)))
                starts.setdefault(key, False)
            continue
        minute = min(float(event.minute), match_length)
        outgoing = event.player
        incoming = event.substitution_replacement
        if outgoing:
            outgoing_key = (event.match_id, event.team.casefold(), _event_player_id(event, outgoing))
            minutes[outgoing_key] = min(minutes.get(outgoing_key, match_length), minute)
            starts.setdefault(outgoing_key, True)
        if incoming:
            incoming_key = (event.match_id, event.team.casefold(), _event_player_id(event, incoming))
            minutes[incoming_key] = max(minutes.get(incoming_key, 0.0), match_length - minute)
            starts[incoming_key] = False
    return minutes, starts, positions


def build_player_match_stats_from_events(
    events: list[MatchEvent],
    lineups: list[ActualLineupPlayer],
    *,
    observed_matches_path: Path = OBSERVED_MATCHES_PATH,
    updated_at: datetime | None = None,
) -> list[PlayerMatchStat]:
    """Build provider-independent player match stats from event and lineup rows."""
    if not events:
        return []
    updated = updated_at or datetime.now(timezone.utc)
    observed = _observed_match_lookup(observed_matches_path)
    lineup_by_id = _lineup_index(lineups)
    lineup_by_name = _lineup_by_player_name(lineups)
    minutes, starts, positions = _minutes_and_starts(events, lineups)
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    event_sources: defaultdict[tuple[str, str], list[float]] = defaultdict(list)

    def row_for(event: MatchEvent, player: str, *, team: str | None = None) -> dict[str, Any]:
        event_team = team or event.team
        player_id = player_id_for(event_team, player)
        key = (event.match_id, player_id)
        match = observed.get(event.match_id)
        lineup_key = (event.match_id, event_team.casefold(), player_id)
        lineup = lineup_by_id.get(lineup_key) or lineup_by_name.get((event.match_id, event_team.casefold(), player.casefold()))
        if key not in rows:
            rows[key] = {
                "match_id": event.match_id,
                "player_id": player_id,
                "player": player,
                "team": event_team,
                "opponent": _opponent_for(match, event_team, event),
                "date": _match_date(match, event),
                "competition": event.competition or "FIFA World Cup 2026",
                "position": (lineup.position if lineup else positions.get(lineup_key, "")) or "UNK",
                "started": starts.get(lineup_key, bool(lineup and lineup.starter)),
                "minutes": _round(minutes.get(lineup_key, 0.0), 2),
                "goals": 0.0,
                "assists": 0.0,
                "xg": 0.0,
                "xa": 0.0,
                "shots": 0.0,
                "shots_on_target": 0.0,
                "key_passes": 0.0,
                "progressive_passes": 0.0,
                "progressive_carries": 0.0,
                "duels_won": 0.0,
                "duels_lost": 0.0,
                "pressures": 0.0,
                "tackles": 0.0,
                "interceptions": 0.0,
                "aerials_won": 0.0,
                "aerials_lost": 0.0,
                "saves": 0.0,
                "goals_conceded": 0.0,
                "source": "observed_events_lineups",
                "source_confidence": event.source_confidence,
                "updated_at": updated,
            }
        event_sources[key].append(event.source_confidence)
        return rows[key]

    for event in events:
        player = _event_player(event)
        if player:
            row = row_for(event, player)
            if event.event_type in {MatchEventType.SHOT, MatchEventType.GOAL, MatchEventType.PENALTY}:
                row["shots"] += 1
                row["xg"] += event.xg or 0.0
                if event.is_goal or event.outcome.casefold() in {"goal", "saved", "saved to post"}:
                    row["shots_on_target"] += 1
                if event.is_goal:
                    row["goals"] += 1
            elif event.event_type == MatchEventType.KEY_PASS:
                row["key_passes"] += 1
            elif event.event_type == MatchEventType.PROGRESSIVE_PASS:
                row["progressive_passes"] += 1
            elif event.event_type == MatchEventType.PROGRESSIVE_CARRY:
                row["progressive_carries"] += 1
            elif event.event_type == MatchEventType.TACKLE:
                row["tackles"] += 1
                row["pressures"] += 1
            elif event.event_type == MatchEventType.INTERCEPTION:
                row["interceptions"] += 1
            elif event.event_type in {MatchEventType.DUEL, MatchEventType.AERIAL_DUEL}:
                won = event.outcome.casefold() in {"won", "success", "complete"}
                if event.event_type == MatchEventType.AERIAL_DUEL:
                    row["aerials_won" if won else "aerials_lost"] += 1
                else:
                    row["duels_won" if won else "duels_lost"] += 1
                row["pressures"] += 1
            elif event.event_type == MatchEventType.FOUL:
                row["pressures"] += 1
            elif event.event_type == MatchEventType.SAVE:
                row["saves"] += 1

        if event.related_player and event.event_type in {MatchEventType.SHOT, MatchEventType.GOAL, MatchEventType.PENALTY}:
            assister = row_for(event, event.related_player)
            assister["xa"] += event.xg or 0.0
            assister["key_passes"] += 1
            if event.is_goal:
                assister["assists"] += 1

    for key, row in rows.items():
        source_values = event_sources.get(key) or [0.75]
        row["source_confidence"] = _round(mean(source_values), 3)
        if row["position"].casefold() in {"gk", "goalkeeper"}:
            row["goals_conceded"] = _goals_against(observed.get(row["match_id"]), row["team"])
        if row["minutes"] == 0:
            row["minutes"] = 1.0

    return sorted((PlayerMatchStat(**row) for row in rows.values()), key=lambda item: (item.match_id, item.team, item.player))


def merge_player_match_stats(existing: list[PlayerMatchStat], derived: list[PlayerMatchStat]) -> list[PlayerMatchStat]:
    merged = {(row.match_id, row.player_id): row for row in existing}
    for row in derived:
        key = (row.match_id, row.player_id)
        current = merged.get(key)
        if current is None or row.source_confidence >= current.source_confidence:
            merged[key] = row
    return sorted(merged.values(), key=lambda item: (item.match_id, item.team, item.player))


def write_player_match_stats(rows: list[PlayerMatchStat], path: Path = MATCH_STATS_PATH) -> list[DataQualityIssue]:
    payloads = []
    for row in rows:
        payload = row.model_dump(mode="json")
        payloads.append({field: "" if payload.get(field) is None else payload.get(field, "") for field in MATCH_FIELDS})
    return safe_write_csv(path, payloads, MATCH_FIELDS).issues


def _cards_by_player(events: list[MatchEvent]) -> dict[tuple[str, str], float]:
    cards: dict[tuple[str, str], float] = defaultdict(float)
    for event in events:
        if event.event_type == MatchEventType.CARD and event.player:
            cards[(event.match_id, player_id_for(event.team, event.player))] += 1.0
    return cards


def _rating(stat: PlayerMatchStat, cards: float) -> float:
    rating = 6.0
    rating += stat.goals * 0.72
    rating += stat.assists * 0.45
    rating += stat.xg * 0.34
    rating += stat.xa * 0.28
    rating += stat.shots_on_target * 0.08
    rating += stat.key_passes * 0.10
    rating += (stat.progressive_passes + stat.progressive_carries) * 0.035
    rating += (stat.tackles + stat.interceptions + stat.duels_won + stat.aerials_won) * 0.055
    rating += stat.saves * 0.16
    rating -= cards * 0.18
    if stat.position.casefold() in {"gk", "goalkeeper"}:
        rating -= stat.goals_conceded * 0.10
    rating += min(stat.minutes, 90.0) / 90.0 * 0.12
    return round(_clamp(rating, 4.2, 9.8), 2)


def build_player_postmatch_signals(
    match_stats: list[PlayerMatchStat],
    events: list[MatchEvent],
    *,
    updated_at: datetime | None = None,
) -> list[PlayerPostmatchSignal]:
    updated = updated_at or datetime.now(timezone.utc)
    cards = _cards_by_player(events)
    output = []
    for stat in match_stats:
        if stat.source != "observed_events_lineups":
            continue
        player_cards = cards.get((stat.match_id, stat.player_id), 0.0)
        attacking = (stat.goals * 1.1) + (stat.xg * 0.75) + (stat.shots_on_target * 0.12)
        creative = (stat.assists * 0.9) + (stat.xa * 0.8) + (stat.key_passes * 0.15)
        defensive = (stat.tackles + stat.interceptions + stat.duels_won + stat.aerials_won) * 0.12
        goalkeeper = stat.saves * 0.25 - stat.goals_conceded * 0.15
        progressive = stat.progressive_passes + stat.progressive_carries
        quality = (
            "observed_events_confirmed_minutes"
            if stat.position != "UNK" or stat.started
            else "observed_events_estimated_minutes"
        )
        output.append(
            PlayerPostmatchSignal(
                match_id=stat.match_id,
                match_date=stat.date,
                player_id=stat.player_id,
                player=stat.player,
                team=stat.team,
                opponent=stat.opponent,
                position=stat.position,
                started=stat.started,
                minutes=stat.minutes,
                goals=stat.goals,
                assists=stat.assists,
                xg=_round(stat.xg),
                xa=_round(stat.xa),
                shots=stat.shots,
                shots_on_target=stat.shots_on_target,
                key_passes=stat.key_passes,
                progressive_actions=progressive,
                defensive_actions=stat.tackles + stat.interceptions + stat.duels_won + stat.aerials_won,
                pressures=stat.pressures,
                saves=stat.saves,
                goals_conceded=stat.goals_conceded,
                cards=player_cards,
                player_rating=_rating(stat, player_cards),
                attacking_impact=_round(attacking),
                creative_impact=_round(creative),
                defensive_impact=_round(defensive),
                goalkeeper_impact=_round(goalkeeper),
                discipline_risk=_round(_clamp(player_cards * 22 + stat.duels_lost * 2.5), 2),
                stamina_load=_round(_clamp(stat.minutes / 90.0 * 100.0), 2),
                data_quality=quality,
                source=stat.source,
                updated_at=updated,
            )
        )
    return sorted(output, key=lambda item: (item.match_id, item.team, -item.player_rating, item.player))


def write_player_postmatch_signals(
    signals: list[PlayerPostmatchSignal],
    path: Path = PLAYER_POSTMATCH_SIGNALS_PATH,
) -> list[DataQualityIssue]:
    rows = []
    for signal in signals:
        payload = signal.model_dump(mode="json")
        rows.append({field: "" if payload.get(field) is None else payload.get(field, "") for field in PLAYER_POSTMATCH_SIGNAL_FIELDS})
    return safe_write_csv(path, rows, PLAYER_POSTMATCH_SIGNAL_FIELDS).issues


def _baseline_team_features(path: Path = BASE_PLAYER_TEAM_FEATURES_PATH) -> dict[str, dict[str, float]]:
    output = {}
    if not path.exists():
        return output
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            team = row.get("team", "")
            if team:
                output[team] = {key: float(value) for key, value in row.items() if key != "team" and value not in {"", None}}
    return output


def build_live_player_team_features(
    signals: list[PlayerPostmatchSignal],
    *,
    baseline_path: Path = BASE_PLAYER_TEAM_FEATURES_PATH,
) -> list[dict[str, Any]]:
    baseline = _baseline_team_features(baseline_path)
    grouped: defaultdict[str, list[PlayerPostmatchSignal]] = defaultdict(list)
    for signal in signals:
        grouped[signal.team].append(signal)
    rows = []
    for team, team_rows in sorted(grouped.items()):
        match_count = max(len({row.match_id for row in team_rows}), 1)
        avg_rating = mean(row.player_rating for row in team_rows)
        total_minutes = max(sum(row.minutes for row in team_rows), 1.0)
        goals = sum(row.goals for row in team_rows)
        xg = sum(row.xg for row in team_rows)
        xa = sum(row.xa for row in team_rows)
        shots_on_target = sum(row.shots_on_target for row in team_rows)
        key_passes = sum(row.key_passes for row in team_rows)
        progressive = sum(row.progressive_actions for row in team_rows)
        defensive = sum(row.defensive_actions for row in team_rows)
        pressures = sum(row.pressures for row in team_rows)
        saves = sum(row.saves for row in team_rows)
        gk_impact = sum(row.goalkeeper_impact for row in team_rows)
        cards = sum(row.cards for row in team_rows)
        rating_score = _clamp(50 + (avg_rating - 6.0) * 16.0)
        live = {
            "recent_form": rating_score,
            "player_shooting_score": _clamp(45 + goals / match_count * 10 + xg / match_count * 9 + shots_on_target / match_count * 2.5),
            "player_chance_creation_score": _clamp(45 + xa / match_count * 12 + key_passes / match_count * 1.8),
            "player_passing_score": _clamp(50 + progressive / match_count * 0.9 + key_passes / match_count * 1.1),
            "player_progression_score": _clamp(48 + progressive / match_count * 2.0),
            "player_pressing_score": _clamp(48 + pressures / match_count * 1.7),
            "player_defensive_activity_score": _clamp(48 + defensive / match_count * 2.1),
            "player_goalkeeping_score": _clamp(50 + saves / match_count * 4.0 + gk_impact / match_count * 10.0),
            "player_keeper_sweeping_score": _clamp(50 + saves / match_count * 2.0),
            "player_keeper_diving_score": _clamp(50 + saves / match_count * 5.0),
            "player_set_piece_delivery_score": _clamp(48 + key_passes / match_count * 2.0),
            "player_early_goal_score": _clamp(50 + goals / match_count * 4.0),
            "player_late_goal_score": _clamp(50 + goals / match_count * 4.0),
            "player_discipline_score": _clamp(88 - cards / match_count * 12.0),
            "player_minutes_score": _clamp(total_minutes / (match_count * 990.0) * 100.0),
        }
        base = baseline.get(team, {})
        confidence = min(0.30, 0.10 + match_count * 0.05)
        row = {"team": team}
        for field in LIVE_TEAM_FEATURE_FIELDS:
            if field == "team":
                continue
            base_value = base.get(field, 70.0)
            row[field] = round((base_value * (1 - confidence)) + (live[field] * confidence), 2)
        rows.append(row)
    return rows


def write_live_player_team_features(
    rows: list[dict[str, Any]],
    path: Path = LIVE_PLAYER_TEAM_FEATURES_PATH,
) -> list[DataQualityIssue]:
    return safe_write_csv(path, rows, LIVE_TEAM_FEATURE_FIELDS).issues


def run_postmatch_player_update(
    *,
    events_path: Path = MATCH_EVENTS_NORMALIZED_PATH,
    lineups_path: Path = ACTUAL_LINEUPS_PATH,
    match_stats_path: Path = MATCH_STATS_PATH,
    season_stats_path: Path = SEASON_STATS_PATH,
    role_vectors_path: Path = ROLE_VECTORS_PATH,
    form_signals_path: Path = FORM_SIGNALS_PATH,
    postmatch_signals_path: Path = PLAYER_POSTMATCH_SIGNALS_PATH,
    live_team_features_path: Path = LIVE_PLAYER_TEAM_FEATURES_PATH,
) -> PostmatchPlayerUpdateResult:
    events, event_issues = load_normalized_events(events_path)
    lineups, lineup_issues = load_actual_lineups(lineups_path)
    existing_matches, match_issues = load_normalized_match_stats(match_stats_path)
    season, season_issues = load_normalized_season_stats(season_stats_path)
    derived = build_player_match_stats_from_events(events, lineups)
    merged = merge_player_match_stats(existing_matches, derived)
    postmatch_signals = build_player_postmatch_signals(derived, events)
    forms = build_form_signals(merged, season)
    vectors, vector_issues = build_role_vectors(season, forms)
    live_team_rows = build_live_player_team_features(postmatch_signals)
    write_issues = [
        *write_player_match_stats(merged, match_stats_path),
        *write_player_postmatch_signals(postmatch_signals, postmatch_signals_path),
        *write_derived_outputs(vectors, forms, role_vectors_path, form_signals_path),
        *write_live_player_team_features(live_team_rows, live_team_features_path),
    ]
    return PostmatchPlayerUpdateResult(
        event_rows=len(events),
        lineup_rows=len(lineups),
        derived_match_stats=len(derived),
        merged_match_stats=len(merged),
        player_postmatch_signals=len(postmatch_signals),
        player_form_signals=len(forms),
        player_role_vectors=len(vectors),
        live_team_feature_rows=len(live_team_rows),
        issues=[*event_issues, *lineup_issues, *match_issues, *season_issues, *vector_issues, *write_issues],
    )


__all__ = [
    "LIVE_PLAYER_TEAM_FEATURES_PATH",
    "PLAYER_POSTMATCH_SIGNALS_PATH",
    "PostmatchPlayerUpdateResult",
    "PlayerPostmatchSignal",
    "build_live_player_team_features",
    "build_player_match_stats_from_events",
    "build_player_postmatch_signals",
    "merge_player_match_stats",
    "run_postmatch_player_update",
    "write_live_player_team_features",
    "write_player_match_stats",
    "write_player_postmatch_signals",
]
