"""Permanent observed-match ledger and idempotent tournament lifecycle automation."""

from __future__ import annotations

import csv
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator

os.environ.setdefault("MPLCONFIGDIR", "/tmp/worldcup-matplotlib")

from app.calibration import run_prediction_calibration
from app.evaluation import evaluate_completed_match, write_completed_evaluations
from app.evaluation.schemas import CompletedMatch
from app.ingestion.lineup_ingestion import (
    CONFIRMED_LINEUPS_PATH,
    CsvLineupAdapter,
    build_lineup_delta_signals,
    ingest_lineups,
    write_actual_lineups,
    write_lineup_delta_signals,
)
from app.ingestion.event_data_ingestion import load_match_summary_signals
from app.ingestion.normalizers import safe_read_csv, safe_write_csv, validate_rows
from app.prediction_arena.api_service import settle_arena_match
from app.prediction_arena.prediction_runner import run_prediction_arena


ROOT = Path(__file__).resolve().parents[1]
FIXTURES_PATH = ROOT / "data" / "fixtures.csv"
LIVE_STATE_PATH = ROOT / "data" / "live_state.json"
OBSERVED_MATCHES_PATH = ROOT / "data" / "observed_matches.csv"
MANUAL_RESULTS_PATH = ROOT / "data" / "raw" / "live" / "manual_worldcup_results.csv"
PROVIDER_SNAPSHOT_PATH = ROOT / "data" / "raw" / "live" / "provider_matches_latest.json"
FIFA_SNAPSHOT_PATH = ROOT / "data" / "raw" / "live" / "fifa_matches_latest.json"
AUTOPILOT_STATUS_PATH = ROOT / "data" / "tournament_autopilot_status.json"
LIVE_TEAM_STATE_PATH = ROOT / "data" / "live_team_state.csv"
DEFAULT_PROVIDER_URL = "https://api.balldontlie.io/fifa/worldcup/v1"
DEFAULT_FIFA_API_URL = "https://api.fifa.com/api/v3/calendar/matches"
FIFA_WORLD_CUP_COMPETITION_ID = "17"
FIFA_WORLD_CUP_2026_SEASON_ID = "285023"
TEAM_ALIASES = {
    "bosnia-herzegovina": "Bosnia and Herzegovina",
    "bosnia and herzegovina": "Bosnia and Herzegovina",
    "south korea": "Korea Republic",
    "united states": "USA",
    "united states of america": "USA",
    "ivory coast": "Cote d'Ivoire",
    "côte d'ivoire": "Cote d'Ivoire",
    "cape verde": "Cabo Verde",
    "czech republic": "Czechia",
    "curacao": "Curacao",
    "curaçao": "Curacao",
    "dr congo": "Congo DR",
    "turkey": "Turkiye",
    "türkiye": "Turkiye",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("updated_at must include a timezone")
    return value


class ObservedMatch(StrictModel):
    match_id: str = Field(min_length=1)
    stage: str = ""
    group: str = ""
    kickoff_utc: datetime | None = None
    team_a: str = Field(min_length=1)
    team_b: str = Field(min_length=1)
    team_a_score: int = Field(ge=0, le=30)
    team_b_score: int = Field(ge=0, le=30)
    status: str = "final"
    provider_match_id: str = ""
    source: str = Field(min_length=1)
    source_url: str = ""
    source_confidence: float = Field(ge=0, le=1)
    updated_at: datetime

    _updated_at_aware = field_validator("updated_at")(_aware)


OBSERVED_MATCH_FIELDS = list(ObservedMatch.model_fields)


@dataclass
class AutopilotReport:
    observed_matches: int = 0
    newly_observed_match_ids: list[str] = field(default_factory=list)
    lineup_rows: int = 0
    lineup_delta_signals: int = 0
    arena_runs: list[str] = field(default_factory=list)
    arena_settlements: list[str] = field(default_factory=list)
    evaluations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "observed_matches": self.observed_matches,
            "newly_observed_match_ids": self.newly_observed_match_ids,
            "lineup_rows": self.lineup_rows,
            "lineup_delta_signals": self.lineup_delta_signals,
            "arena_runs": self.arena_runs,
            "arena_settlements": self.arena_settlements,
            "evaluations": self.evaluations,
            "warnings": self.warnings,
        }


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _plain(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _plain(value).casefold())


def _canonical_team(value: str) -> str:
    stripped = value.strip()
    key = stripped.casefold()
    return TEAM_ALIASES.get(key) or TEAM_ALIASES.get(_plain(key)) or stripped


def _fixture_rows(path: Path = FIXTURES_PATH) -> list[dict[str, str]]:
    return safe_read_csv(path).rows


def _fixture_for_teams(team_a: str, team_b: str, fixtures: list[dict[str, str]]) -> dict[str, str] | None:
    wanted = {_slug(team_a), _slug(team_b)}
    return next(
        (
            row for row in fixtures
            if {_slug(row.get("team_a", "")), _slug(row.get("team_b", ""))} == wanted
        ),
        None,
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _observed_row(model: ObservedMatch) -> dict[str, Any]:
    payload = model.model_dump(mode="json")
    return {field_name: "" if payload.get(field_name) is None else payload.get(field_name, "") for field_name in OBSERVED_MATCH_FIELDS}


def load_observed_matches(path: Path = OBSERVED_MATCHES_PATH) -> list[ObservedMatch]:
    read = safe_read_csv(path, OBSERVED_MATCH_FIELDS)
    rows = [{**row, "kickoff_utc": row.get("kickoff_utc") or None} for row in read.rows]
    return validate_rows(rows, ObservedMatch, file=path).valid_records


def upsert_observed_matches(
    records: list[ObservedMatch],
    path: Path = OBSERVED_MATCHES_PATH,
) -> tuple[list[ObservedMatch], list[str]]:
    """Persist final results without allowing a lower-confidence source to erase them."""
    existing = {row.match_id: row for row in load_observed_matches(path)}
    new_ids = []
    for record in records:
        current = existing.get(record.match_id)
        if current is None:
            existing[record.match_id] = record
            new_ids.append(record.match_id)
            continue
        if record.source_confidence > current.source_confidence or (
            record.source_confidence == current.source_confidence and record.updated_at > current.updated_at
        ):
            existing[record.match_id] = record
    ordered = sorted(existing.values(), key=lambda row: (row.kickoff_utc or row.updated_at, row.match_id))
    result = safe_write_csv(path, [_observed_row(row) for row in ordered], OBSERVED_MATCH_FIELDS)
    if not result.ok:
        raise ValueError("; ".join(issue.problem for issue in result.issues))
    return ordered, new_ids


def load_manual_results(path: Path = MANUAL_RESULTS_PATH) -> list[ObservedMatch]:
    rows = safe_read_csv(path, {"match_id", "team_a", "team_b", "team_a_score", "team_b_score", "source"}).rows
    fixtures = _fixture_rows()
    normalized = []
    for row in rows:
        fixture = next((item for item in fixtures if item.get("match_id") == row.get("match_id")), None)
        payload = {
            **row,
            "stage": row.get("stage") or (fixture or {}).get("stage", ""),
            "group": row.get("group") or (fixture or {}).get("group", ""),
            "kickoff_utc": row.get("kickoff_utc") or (fixture or {}).get("kickoff_utc") or None,
            "source_confidence": row.get("source_confidence") or 0.95,
            "updated_at": row.get("updated_at") or datetime.now(timezone.utc).isoformat(),
        }
        normalized.append(ObservedMatch.model_validate(payload))
    return normalized


def _object_name(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(next((value[key] for key in ("name", "full_name", "display_name", "team_name") if value.get(key)), ""))
    return ""


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    return next((row[key] for key in keys if row.get(key) is not None), None)


def provider_rows_to_observed(rows: list[dict[str, Any]]) -> list[ObservedMatch]:
    fixtures = _fixture_rows()
    output = []
    for row in rows:
        status = str(_first(row, ("status", "match_status", "state")) or "").casefold()
        if not any(token in status for token in ("finished", "complete", "final", "ft")):
            continue
        team_a = _canonical_team(_object_name(_first(row, ("home_team", "team_a", "home", "team1", "homeTeam"))))
        team_b = _canonical_team(_object_name(_first(row, ("away_team", "team_b", "away", "team2", "awayTeam"))))
        score_a = _first(row, ("home_score", "team_a_score", "home_goals", "score_home"))
        score_b = _first(row, ("away_score", "team_b_score", "away_goals", "score_away"))
        if not team_a or not team_b or score_a is None or score_b is None:
            continue
        fixture = _fixture_for_teams(team_a, team_b, fixtures) or {}
        output.append(
            ObservedMatch(
                match_id=str(fixture.get("match_id") or row.get("id") or f"{_slug(team_a)}-{_slug(team_b)}"),
                stage=fixture.get("stage", ""),
                group=fixture.get("group", ""),
                kickoff_utc=_parse_datetime(fixture.get("kickoff_utc") or row.get("start_time") or row.get("date")),
                team_a=fixture.get("team_a") or team_a,
                team_b=fixture.get("team_b") or team_b,
                team_a_score=int(score_a),
                team_b_score=int(score_b),
                status="final",
                provider_match_id=str(row.get("id") or ""),
                source="balldontlie_worldcup_api",
                source_url=DEFAULT_PROVIDER_URL,
                source_confidence=0.9,
                updated_at=datetime.now(timezone.utc),
            )
        )
    return output


def _localized_description(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    preferred = next(
        (
            item
            for item in value
            if isinstance(item, dict)
            and str(item.get("Locale", "")).casefold() in {"en-gb", "en", "en-us"}
        ),
        None,
    )
    item = preferred or next((item for item in value if isinstance(item, dict)), None)
    return str((item or {}).get("Description") or "")


def _fifa_team_name(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return _canonical_team(_localized_description(value.get("TeamName")) or value.get("ShortClubName") or "")


def _fifa_score(value: Any) -> int | None:
    if isinstance(value, dict):
        value = value.get("Score")
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_fifa_final(row: dict[str, Any]) -> bool:
    result_type = row.get("ResultType")
    score_a = _fifa_score(row.get("Home"))
    score_b = _fifa_score(row.get("Away"))
    return score_a is not None and score_b is not None and str(result_type) not in {"", "0", "None", "none"}


def fifa_row_to_current_match(row: dict[str, Any]) -> dict[str, Any]:
    team_a = _fifa_team_name(row.get("Home"))
    team_b = _fifa_team_name(row.get("Away"))
    score_a = _fifa_score(row.get("Home"))
    score_b = _fifa_score(row.get("Away"))
    match_status = str(row.get("MatchStatus") if row.get("MatchStatus") is not None else "")
    is_final = _is_fifa_final(row)
    is_live = score_a is not None and score_b is not None and not is_final and match_status not in {"", "0"}
    return {
        "match_id": str(row.get("MatchNumber") or row.get("IdMatch") or ""),
        "provider_match_id": str(row.get("IdMatch") or ""),
        "stage": _localized_description(row.get("StageName")),
        "group": _localized_description(row.get("GroupName")),
        "kickoff_utc": row.get("Date") or None,
        "team_a": team_a,
        "team_b": team_b,
        "team_a_score": score_a,
        "team_b_score": score_b,
        "status": "final" if is_final else "live" if is_live else "scheduled",
        "is_final": is_final,
        "is_live": is_live,
        "match_time": row.get("MatchTime") or "",
        "result_type": row.get("ResultType"),
        "source": "fifa_official_calendar_api",
        "source_url": "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/scores-fixtures",
    }


def fifa_rows_to_observed(rows: list[dict[str, Any]]) -> list[ObservedMatch]:
    output = []
    for row in rows:
        current = fifa_row_to_current_match(row)
        if not current["is_final"] or current["team_a_score"] is None or current["team_b_score"] is None:
            continue
        output.append(
            ObservedMatch(
                match_id=current["match_id"],
                stage=current["stage"].replace("First Stage", "Group"),
                group=current["group"].replace("Group ", ""),
                kickoff_utc=_parse_datetime(current["kickoff_utc"]),
                team_a=current["team_a"],
                team_b=current["team_b"],
                team_a_score=current["team_a_score"],
                team_b_score=current["team_b_score"],
                status="final",
                provider_match_id=current["provider_match_id"],
                source="fifa_official_calendar_api",
                source_url=current["source_url"],
                source_confidence=0.99,
                updated_at=datetime.now(timezone.utc),
            )
        )
    return output


def fetch_provider_observed_matches(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> tuple[list[ObservedMatch], str | None]:
    key = api_key or os.getenv("BALLDONTLIE_API_KEY", "").strip()
    if not key:
        return [], "BALLDONTLIE_API_KEY is not configured."
    url = (base_url or os.getenv("WORLD_CUP_API_BASE_URL") or DEFAULT_PROVIDER_URL).rstrip("/")
    try:
        response = requests.get(
            f"{url}/matches",
            headers={"Authorization": key},
            params={"seasons[]": 2026, "per_page": 200},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        PROVIDER_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROVIDER_SNAPSHOT_PATH.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n", encoding="utf-8")
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        return provider_rows_to_observed([row for row in rows if isinstance(row, dict)]), None
    except (requests.RequestException, ValueError, OSError) as exc:
        return [], str(exc)


def fetch_fifa_official_matches(
    *,
    base_url: str | None = None,
    from_date: str = "2026-06-11",
    to_date: str = "2026-07-20",
) -> tuple[list[ObservedMatch], list[dict[str, Any]], str | None]:
    """Fetch official FIFA calendar scores and return final observed rows plus a live snapshot."""
    url = base_url or os.getenv("FIFA_OFFICIAL_MATCHES_URL") or DEFAULT_FIFA_API_URL
    params = {
        "language": "en",
        "count": 500,
        "idCompetition": FIFA_WORLD_CUP_COMPETITION_ID,
        "idSeason": FIFA_WORLD_CUP_2026_SEASON_ID,
        "from": from_date,
        "to": to_date,
    }
    try:
        response = requests.get(
            url,
            params=params,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Origin": "https://www.fifa.com",
                "Referer": "https://www.fifa.com/",
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("Results", []) if isinstance(payload, dict) else []
        rows = [row for row in rows if isinstance(row, dict)]
        FIFA_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIFA_SNAPSHOT_PATH.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n", encoding="utf-8")
        current_matches = [fifa_row_to_current_match(row) for row in rows]
        return fifa_rows_to_observed(rows), current_matches, None
    except (requests.RequestException, ValueError, OSError) as exc:
        return [], [], str(exc)


def sync_live_state(
    records: list[ObservedMatch],
    path: Path = LIVE_STATE_PATH,
    current_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Publish the durable observed ledger into the app's existing live-state contract."""
    previous: dict[str, Any] = {}
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
    state = {
        **previous,
        "source": "data/observed_matches.csv",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "completed_matches": [
            {
                "match_id": row.match_id,
                "stage": row.stage,
                "group": row.group,
                "kickoff_utc": row.kickoff_utc.isoformat() if row.kickoff_utc else None,
                "team_a": row.team_a,
                "team_b": row.team_b,
                "team_a_score": row.team_a_score,
                "team_b_score": row.team_b_score,
                "status": row.status,
                "provider_match_id": row.provider_match_id or None,
                "source": row.source,
                "source_url": row.source_url or None,
                "updated_at": row.updated_at.isoformat(),
            }
            for row in records
        ],
    }
    if current_matches is not None:
        state["current_matches"] = current_matches
        state["current_matches_source"] = "fifa_official_calendar_api"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    sync_live_team_state(records)
    return state


def sync_live_team_state(
    records: list[ObservedMatch],
    path: Path = LIVE_TEAM_STATE_PATH,
) -> None:
    """Rebuild model-consumable tournament form, preferring observed event xG."""
    teams = [row.get("team", "") for row in safe_read_csv(ROOT / "data" / "teams.csv").rows if row.get("team")]
    summaries, _ = load_match_summary_signals()
    summary_by_match_team = {(row.match_id, row.team.casefold()): row for row in summaries}
    state: dict[str, dict[str, float]] = {
        team: {"gf": 0.0, "ga": 0.0, "xgf": 0.0, "xga": 0.0, "games": 0.0}
        for team in teams
    }
    for match in records:
        for team, opponent, goals_for, goals_against in (
            (match.team_a, match.team_b, match.team_a_score, match.team_b_score),
            (match.team_b, match.team_a, match.team_b_score, match.team_a_score),
        ):
            if team not in state:
                continue
            summary = summary_by_match_team.get((match.match_id, team.casefold()))
            opponent_summary = summary_by_match_team.get((match.match_id, opponent.casefold()))
            state[team]["gf"] += goals_for
            state[team]["ga"] += goals_against
            state[team]["xgf"] += summary.xg if summary else goals_for
            state[team]["xga"] += opponent_summary.xg if opponent_summary else goals_against
            state[team]["games"] += 1
    rows = []
    at = datetime.now(timezone.utc).isoformat()
    for team in sorted(state):
        row = state[team]
        games = max(row["games"], 1)
        goal_delta = (row["gf"] - row["ga"]) / games if row["games"] else 0.0
        rows.append(
            {
                "team": team,
                "posterior_strength_delta": round(goal_delta * 2.5, 3),
                "live_xg_for": round(row["xgf"] / games, 3) if row["games"] else "",
                "live_xg_against": round(row["xga"] / games, 3) if row["games"] else "",
                "injury_load": 0.0,
                "momentum": round(goal_delta, 3),
                "matches_played": int(row["games"]),
                "source": "observed_matches + match_summary_signals",
                "updated_at": at,
            }
        )
    fields = [
        "team",
        "posterior_strength_delta",
        "live_xg_for",
        "live_xg_against",
        "injury_load",
        "momentum",
        "matches_played",
        "source",
        "updated_at",
    ]
    result = safe_write_csv(path, rows, fields)
    if not result.ok:
        raise ValueError("; ".join(issue.problem for issue in result.issues))


def _result_label(match: ObservedMatch) -> str:
    if match.team_a_score > match.team_b_score:
        return match.team_a
    if match.team_b_score > match.team_a_score:
        return match.team_b
    return "Draw"


def _run_lineup_refresh(report: AutopilotReport) -> None:
    result = ingest_lineups(CsvLineupAdapter(CONFIRMED_LINEUPS_PATH, require_confirmed=True))
    signals, issues = build_lineup_delta_signals(result.records)
    write_actual_lineups(result.records)
    write_lineup_delta_signals(signals)
    report.lineup_rows = len(result.records)
    report.lineup_delta_signals = len(signals)
    report.warnings.extend(issue.problem for issue in [*result.issues, *issues] if issue.severity.value != "info")


def _run_completed_match_feedback(matches: list[ObservedMatch], report: AutopilotReport) -> None:
    for match in matches:
        try:
            settle_arena_match(
                match.match_id,
                f"{match.team_a_score}-{match.team_b_score}",
                _result_label(match),
            )
            report.arena_settlements.append(match.match_id)
        except (LookupError, ValueError) as exc:
            report.warnings.append(f"Arena settlement skipped for {match.match_id}: {exc}")
        try:
            completed = CompletedMatch(
                match_id=match.match_id,
                team_a=match.team_a,
                team_b=match.team_b,
                team_a_score=match.team_a_score,
                team_b_score=match.team_b_score,
                source=match.source,
            )
            write_completed_evaluations(evaluate_completed_match(completed))
            report.evaluations.append(match.match_id)
        except (LookupError, ValueError, OSError) as exc:
            report.warnings.append(f"Evaluation skipped for {match.match_id}: {exc}")


def _run_upcoming_predictions(report: AutopilotReport, now: datetime, hours_ahead: int) -> None:
    observed = {row.match_id for row in load_observed_matches()}
    for fixture in _fixture_rows():
        if not fixture.get("team_a") or not fixture.get("team_b") or fixture.get("match_id") in observed:
            continue
        kickoff = _parse_datetime(fixture.get("kickoff_utc"))
        if kickoff is None or not now <= kickoff <= now + timedelta(hours=hours_ahead):
            continue
        match_id = fixture["match_id"]
        lock = kickoff - now <= timedelta(minutes=30)
        try:
            run_prediction_arena(
                match_id,
                fixture["team_a"],
                fixture["team_b"],
                "group" if fixture.get("stage") == "Group" else "knockout",
                lock=lock,
                publish_card=True,
            )
            report.arena_runs.append(match_id)
        except (LookupError, ValueError, OSError) as exc:
            report.warnings.append(f"Arena run skipped for {match_id}: {exc}")


def run_tournament_autopilot(
    *,
    refresh_official: bool = False,
    refresh_provider: bool = False,
    run_arena: bool = False,
    settle_and_evaluate: bool = True,
    hours_ahead: int = 36,
    now: datetime | None = None,
) -> AutopilotReport:
    """Run an idempotent tournament update cycle suitable for cron or GitHub Actions."""
    at = now or datetime.now(timezone.utc)
    report = AutopilotReport()
    before = {row.match_id for row in load_observed_matches()}
    incoming = load_manual_results()
    current_matches = None
    if refresh_official:
        official, official_current, error = fetch_fifa_official_matches()
        incoming.extend(official)
        current_matches = official_current or None
        if error:
            report.warnings.append(f"FIFA official refresh skipped: {error}")
    if refresh_provider:
        provider, error = fetch_provider_observed_matches()
        incoming.extend(provider)
        if error:
            report.warnings.append(f"Provider refresh skipped: {error}")
    observed, new_ids = upsert_observed_matches(incoming)
    sync_live_state(observed, current_matches=current_matches)
    report.observed_matches = len(observed)
    report.newly_observed_match_ids = [match_id for match_id in new_ids if match_id not in before]
    _run_lineup_refresh(report)
    if settle_and_evaluate:
        _run_completed_match_feedback(observed, report)
        try:
            run_prediction_calibration()
        except (ValueError, OSError) as exc:
            report.warnings.append(f"Calibration refresh skipped: {exc}")
    if run_arena:
        _run_upcoming_predictions(report, at, hours_ahead)
    AUTOPILOT_STATUS_PATH.write_text(
        json.dumps({"updated_at": at.isoformat(), **report.as_dict()}, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "AUTOPILOT_STATUS_PATH",
    "FIFA_SNAPSHOT_PATH",
    "MANUAL_RESULTS_PATH",
    "OBSERVED_MATCHES_PATH",
    "ObservedMatch",
    "fetch_fifa_official_matches",
    "fetch_provider_observed_matches",
    "fifa_rows_to_observed",
    "load_observed_matches",
    "provider_rows_to_observed",
    "run_tournament_autopilot",
    "sync_live_state",
    "sync_live_team_state",
    "upsert_observed_matches",
]
