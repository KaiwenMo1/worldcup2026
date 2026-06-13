from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
import csv
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", "/tmp/worldcup-matplotlib")
sys.path.append(str(ROOT / "scripts"))

from app.intelligence import get_intelligence_index, local_answer, optional_llm_answer  # noqa: E402
from app.ai_forecast import (  # noqa: E402
    build_match_reasoning,
    build_match_story,
    build_player_matchup_intelligence,
    build_tournament_reasoning,
    live_match_board,
)
from app.future_data import (  # noqa: E402
    EvaluateMatchRequest,
    ManagerSkillApplyRequest,
    RefreshRequest,
    apply_manager_skill_review,
    enrich_forecast_with_lineups,
    evaluate_match as evaluate_future_match,
    get_analyst_evaluation,
    get_injury_status,
    get_lineup_delta,
    get_manager_evaluation,
    get_manager_evidence,
    get_match_evaluation,
    get_model_evaluation,
    get_player_availability,
    get_player_role_vector,
    get_role_depth,
    refine_manager_skills_dry_run,
    refresh_actual_lineups,
    refresh_event_data,
    refresh_injury_news,
    refresh_player_stats,
    refresh_tactical_evidence,
)
from app.tournament_autopilot import load_observed_matches, run_tournament_autopilot  # noqa: E402
from app.prediction_arena.api_service import (  # noqa: E402
    get_arena_calibration,
    get_arena_leaderboard,
    get_arena_match,
    lock_arena_match,
    publish_arena_card,
    run_arena_match,
    settle_arena_match,
)
from app.tactics.analyst_journal import (  # noqa: E402
    AnalystJournalError,
    JournalConflictError,
    JournalNotFoundError,
    create_postgame_review,
    create_prediction_log,
    load_prediction_logs,
    summarize_analyst_profile,
)
from app.tactics.schemas import (  # noqa: E402
    PostgameReviewCreate,
    PredictionLogCreate,
    TacticalBriefRequest,
    TacticalMatchupRequest,
)
from app.tactics.tactical_brief import (  # noqa: E402
    build_matchup_report,
    build_tactical_brief,
    get_team_manager_overview,
    list_manager_catalog,
)
from app.tactics.data_coverage import team_data_coverage  # noqa: E402
from predict_worldcup import (  # noqa: E402
    MODEL_PATH,
    Standing,
    Team,
    load_groups,
    load_model,
    load_teams,
    match_probabilities,
    model_expected_goals,
    expected_goals,
    model_feature_drivers,
    model_features,
    scoreline_distribution,
    select_knockout_teams,
    poisson,
)
from penalty_model import (  # noqa: E402
    PENALTY_KICKS_PATH,
    PENALTY_MODEL_PATH,
    load_penalty_model,
    predict_penalty_matchup,
)
from xg_model import (  # noqa: E402
    SHOT_EVENTS_PATH,
    XG_MODEL_PATH,
    XG_TEAM_ZONES_PATH,
    load_xg_model,
    predict_shot_xg,
    shot_geometry,
)

load_dotenv(ROOT / ".env")

STATIC_DIR = ROOT / "app" / "static"
LIVE_STATE_PATH = ROOT / "data" / "live_state.json"
PLAYERS_PATH = ROOT / "data" / "player_candidates.csv"
SQUADS_PATH = ROOT / "data" / "worldcup_squads.csv"
PLAYER_MATCH_STATS_PATH = ROOT / "data" / "player_match_stats.csv"
PLAYER_MATCH_TEAM_FEATURES_PATH = ROOT / "data" / "player_match_team_features.csv"
LINEUP_STATUS_PATH = ROOT / "data" / "lineup_sync_status.json"
ODDS_PATH = ROOT / "data" / "bookmaker_odds.csv"
VENUES_PATH = ROOT / "data" / "venues.csv"
FIXTURES_PATH = ROOT / "data" / "fixtures.csv"
AVAILABILITY_PATH = ROOT / "data" / "player_availability.csv"
CONFIRMED_LINEUPS_PATH = ROOT / "data" / "confirmed_lineups.csv"
MARKET_SIGNALS_PATH = ROOT / "data" / "market_signals.csv"
TACTICAL_PROFILES_PATH = ROOT / "data" / "tactical_profiles.csv"
SET_PIECE_PROFILES_PATH = ROOT / "data" / "set_piece_profiles.csv"
GOALKEEPER_PROFILES_PATH = ROOT / "data" / "goalkeeper_profiles.csv"
REFEREE_PROFILES_PATH = ROOT / "data" / "referee_profiles.csv"
WEATHER_EFFECTS_PATH = ROOT / "data" / "weather_effects.csv"
LIVE_TEAM_STATE_PATH = ROOT / "data" / "live_team_state.csv"
FREEZE_FRAME_SIGNALS_PATH = ROOT / "data" / "freeze_frame_signals.csv"
ODDS_API_HOST = "https://api.the-odds-api.com"
BOOKMAKER_ODDS_FIELDNAMES = [
    "market",
    "event",
    "team_a",
    "team_b",
    "selection",
    "american_odds",
    "decimal_odds",
    "bookmaker",
    "start_time",
    "notes",
]

app = FastAPI(title="World Cup 2026 Predictor")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

MODEL_CACHE: dict[str, Any] = {"mtime": None, "bundle": None}
XG_SIGNAL_CACHE: dict[str, Any] = {"mtime": None, "signals": {}}
FIXTURE_CACHE: dict[str, Any] = {"mtime": None, "fixtures": []}
WEATHER_CONTEXT_CACHE: dict[str, dict[str, Any]] = {}
CSV_CACHE: dict[str, dict[str, Any]] = {}

R32_SLOTS = [
    {"id": 73, "a": ("second", "A"), "b": ("second", "B"), "venue": "Los Angeles"},
    {"id": 74, "a": ("winner", "E"), "b": ("third", ("A", "B", "C", "D", "F")), "venue": "Boston"},
    {"id": 75, "a": ("winner", "F"), "b": ("second", "C"), "venue": "Monterrey"},
    {"id": 76, "a": ("winner", "C"), "b": ("second", "F"), "venue": "Houston"},
    {"id": 77, "a": ("winner", "I"), "b": ("third", ("C", "D", "F", "G", "H")), "venue": "New York New Jersey"},
    {"id": 78, "a": ("second", "E"), "b": ("second", "I"), "venue": "Dallas"},
    {"id": 79, "a": ("winner", "A"), "b": ("third", ("C", "E", "F", "H", "I")), "venue": "Mexico City"},
    {"id": 80, "a": ("winner", "L"), "b": ("third", ("E", "H", "I", "J", "K")), "venue": "Atlanta"},
    {"id": 81, "a": ("winner", "D"), "b": ("third", ("B", "E", "F", "I", "J")), "venue": "San Francisco Bay Area"},
    {"id": 82, "a": ("winner", "G"), "b": ("third", ("A", "E", "H", "I", "J")), "venue": "Seattle"},
    {"id": 83, "a": ("second", "K"), "b": ("second", "L"), "venue": "Toronto"},
    {"id": 84, "a": ("winner", "H"), "b": ("second", "J"), "venue": "Los Angeles"},
    {"id": 85, "a": ("winner", "B"), "b": ("third", ("E", "F", "G", "I", "J")), "venue": "Vancouver"},
    {"id": 86, "a": ("winner", "J"), "b": ("second", "H"), "venue": "Miami"},
    {"id": 87, "a": ("winner", "K"), "b": ("third", ("D", "E", "I", "J", "L")), "venue": "Kansas City"},
    {"id": 88, "a": ("second", "D"), "b": ("second", "G"), "venue": "Dallas"},
]

KNOCKOUT_PATH = [
    ("Round of 16", [(89, 74, 77), (90, 73, 75), (91, 76, 78), (92, 79, 80), (93, 83, 84), (94, 81, 82), (95, 86, 88), (96, 85, 87)]),
    ("Quarterfinals", [(97, 89, 90), (98, 93, 94), (99, 91, 92), (100, 95, 96)]),
    ("Semifinals", [(101, 97, 98), (102, 99, 100)]),
]

BRONZE_MATCH = (103, 101, 102)
FINAL_MATCH = (104, 101, 102)

HOST_COUNTRY_BY_TEAM = {"Canada": "Canada", "Mexico": "Mexico", "USA": "USA"}
VENUE_TIMEZONES = {
    "Atlanta": "America/New_York",
    "Boston": "America/New_York",
    "Dallas": "America/Chicago",
    "Guadalajara": "America/Mexico_City",
    "Houston": "America/Chicago",
    "Kansas City": "America/Chicago",
    "Los Angeles": "America/Los_Angeles",
    "Mexico City": "America/Mexico_City",
    "Miami": "America/New_York",
    "Monterrey": "America/Monterrey",
    "New York New Jersey": "America/New_York",
    "Philadelphia": "America/New_York",
    "San Francisco Bay Area": "America/Los_Angeles",
    "Seattle": "America/Los_Angeles",
    "Toronto": "America/Toronto",
    "Vancouver": "America/Vancouver",
}
CONFEDERATION_TRAVEL_LOAD = {
    "CONCACAF": 24.0,
    "CONMEBOL": 42.0,
    "UEFA": 50.0,
    "CAF": 58.0,
    "AFC": 62.0,
    "OFC": 68.0,
}
FAN_BASE_INDEX = {
    "USA": 1.35,
    "Mexico": 1.50,
    "Canada": 1.20,
    "Argentina": 1.12,
    "Brazil": 1.10,
    "England": 0.94,
    "Portugal": 0.90,
    "France": 0.88,
    "Germany": 0.86,
    "Spain": 0.84,
    "Colombia": 0.84,
    "Morocco": 0.82,
    "Japan": 0.80,
    "Korea Republic": 0.76,
    "Croatia": 0.74,
}

FLAG_CODE_BY_TEAM = {
    "Algeria": "dz",
    "Argentina": "ar",
    "Australia": "au",
    "Austria": "at",
    "Belgium": "be",
    "Bosnia and Herzegovina": "ba",
    "Brazil": "br",
    "Cabo Verde": "cv",
    "Canada": "ca",
    "Colombia": "co",
    "Congo DR": "cd",
    "Cote d'Ivoire": "ci",
    "Croatia": "hr",
    "Curacao": "cw",
    "Czechia": "cz",
    "Ecuador": "ec",
    "Egypt": "eg",
    "England": "gb-eng",
    "France": "fr",
    "Germany": "de",
    "Ghana": "gh",
    "Haiti": "ht",
    "IR Iran": "ir",
    "Iraq": "iq",
    "Japan": "jp",
    "Jordan": "jo",
    "Korea Republic": "kr",
    "Mexico": "mx",
    "Morocco": "ma",
    "Netherlands": "nl",
    "New Zealand": "nz",
    "Norway": "no",
    "Panama": "pa",
    "Paraguay": "py",
    "Portugal": "pt",
    "Qatar": "qa",
    "Saudi Arabia": "sa",
    "Scotland": "gb-sct",
    "Senegal": "sn",
    "South Africa": "za",
    "Spain": "es",
    "Sweden": "se",
    "Switzerland": "ch",
    "Tunisia": "tn",
    "Turkiye": "tr",
    "USA": "us",
    "Uruguay": "uy",
    "Uzbekistan": "uz",
}


class SimulationRequest(BaseModel):
    sims: int = Field(default=250, ge=1, le=20000)
    seed: int = 26
    use_model: bool = True
    weather: str = "normal"
    travel: int = Field(default=20, ge=0, le=100)
    fatigue: int = Field(default=20, ge=0, le=100)
    home_advantage: float = Field(default=1.0, ge=0.0, le=2.0)
    venue: str | None = None


class MatchRequest(BaseModel):
    team_a: str
    team_b: str
    use_model: bool = True
    top_scores: int = Field(default=8, ge=1, le=20)
    weather: str = "normal"
    travel: int = Field(default=20, ge=0, le=100)
    fatigue: int = Field(default=20, ge=0, le=100)
    home_advantage: float = Field(default=1.0, ge=0.0, le=2.0)
    venue: str | None = None


class AiMatchRequest(BaseModel):
    team_a: str = "France"
    team_b: str = "Brazil"
    match_id: str | None = None
    use_model: bool = True
    use_llm: bool = False


class AiTournamentRequest(BaseModel):
    sims: int = Field(default=250, ge=1, le=5000)
    seed: int = 26
    use_model: bool = True


class PredictionArenaRunRequest(BaseModel):
    match_id: str = Field(min_length=1, max_length=120)
    team_a: str
    team_b: str
    stage: str = Field(default="group", pattern=r"^(group|knockout)$")
    lock: bool = False
    publish_card: bool = False


class PredictionArenaMatchRequest(BaseModel):
    match_id: str = Field(min_length=1, max_length=120)


class PredictionArenaSettleRequest(BaseModel):
    match_id: str = Field(min_length=1, max_length=120)
    actual_score: str = Field(pattern=r"^\d{1,2}-\d{1,2}$")
    regular_time_result: str = Field(min_length=1, max_length=120)
    qualification_result: str | None = Field(default=None, max_length=120)


class TournamentAutopilotRequest(BaseModel):
    refresh_provider: bool = True
    run_arena: bool = False
    settle_and_evaluate: bool = True
    hours_ahead: int = Field(default=36, ge=1, le=168)


class LiveMatchUpdate(BaseModel):
    team_a: str
    team_b: str
    team_a_score: int = Field(ge=0, le=20)
    team_b_score: int = Field(ge=0, le=20)


class EliminationUpdate(BaseModel):
    team: str
    eliminated: bool = True


class BettingEdgesRequest(BaseModel):
    bankroll: float = Field(default=1000.0, ge=1.0, le=1_000_000.0)
    kelly_fraction: float = Field(default=0.25, ge=0.0, le=1.0)
    max_stake_pct: float = Field(default=2.0, ge=0.0, le=10.0)
    min_edge_pct: float = Field(default=0.0, ge=-100.0, le=100.0)
    sims: int = Field(default=250, ge=1, le=5000)
    seed: int = 26
    use_model: bool = True
    weather: str = "normal"
    travel: int = Field(default=20, ge=0, le=100)
    fatigue: int = Field(default=20, ge=0, le=100)
    home_advantage: float = Field(default=1.0, ge=0.0, le=2.0)
    venue: str | None = None


class OddsSnapshotRequest(BaseModel):
    sport_key: str | None = None
    regions: str | None = None
    bookmakers: str | None = None


class AnalystBriefRequest(BaseModel):
    team_a: str = "France"
    team_b: str = "Brazil"
    use_model: bool = True
    refresh_odds: bool = False
    sims: int = Field(default=250, ge=1, le=5000)
    weather: str = "normal"
    travel: int = Field(default=20, ge=0, le=100)
    fatigue: int = Field(default=20, ge=0, le=100)
    home_advantage: float = Field(default=1.0, ge=0.0, le=2.0)
    venue: str | None = None


class IntelligenceRequest(BaseModel):
    question: str = Field(min_length=3, max_length=800)
    top_k: int = Field(default=6, ge=1, le=10)
    use_llm: bool = True
    use_model: bool = True
    weather: str = "normal"
    travel: int = Field(default=20, ge=0, le=100)
    fatigue: int = Field(default=20, ge=0, le=100)
    home_advantage: float = Field(default=1.0, ge=0.0, le=2.0)
    venue: str | None = None


class XGShotRequest(BaseModel):
    team: str = "France"
    player: str = "Kylian Mbappe"
    shot_x: float = Field(default=108.0, ge=0.0, le=120.0)
    shot_y: float = Field(default=40.0, ge=0.0, le=80.0)
    minute: int = Field(default=60, ge=1, le=130)
    body_part: str = "Right Foot"
    assist_type: str = "Through Ball"
    defender_pressure: str = "Medium"
    game_state: str = "Drawing"
    shot_type: str = "Open Play"


class PenaltyMatchupRequest(BaseModel):
    kicker: str
    goalkeeper: str
    kicker_foot: str = "Right"
    kicker_position: str = "FW"
    pressure_score: float = Field(default=78.0, ge=0.0, le=100.0)
    score_state: str = "Drawing"
    knockout_round: str = "Final"
    kick_order: int = Field(default=1, ge=1, le=12)


def request_context(
    request: SimulationRequest | MatchRequest | BettingEdgesRequest | IntelligenceRequest | AnalystBriefRequest,
) -> dict[str, Any]:
    context = {
        "weather": request.weather,
        "travel": request.travel,
        "fatigue": request.fatigue,
        "home_advantage": request.home_advantage,
    }
    venue = getattr(request, "venue", None)
    if venue:
        context["venue"] = venue
    if request.weather == "auto" and venue:
        context.update(weather_context_for_venue(venue))
    return context


def context_for_fixture(context: dict[str, Any], venue: str | None = None) -> dict[str, Any]:
    if context.get("weather") != "auto" or not venue:
        return context
    fixture_context = dict(context)
    fixture_context.update(weather_context_for_venue(venue))
    fixture_context["venue"] = venue
    return fixture_context


def team_payload(team: Team) -> dict[str, Any]:
    code = FLAG_CODE_BY_TEAM.get(team.name, "un")
    return {
        "name": team.name,
        "flag": code.upper(),
        "flag_code": code,
        "flag_image": f"https://flagcdn.com/w80/{code}.png",
        "rank": team.rank,
        "confederation": team.confederation,
        "host": team.host,
        "squad_rating": round(team.squad_rating, 1),
        "model_factors": {
            "set_piece_attack": team.set_piece_attack,
            "set_piece_defense": team.set_piece_defense,
            "penalties": team.penalty_strength,
            "discipline": team.discipline,
            "tactical_flexibility": team.tactical_flexibility,
            "injury_resilience": team.injury_resilience,
            "pressing": team.pressing_intensity,
            "transition": team.transition_speed,
            "big_match": team.big_match_composure,
            "roster_value": team.roster_value_score,
            "projected_xi": team.projected_xi_score,
            "bench_value": team.bench_value_score,
            "squad_experience": team.squad_experience,
            "squad_balance": team.squad_balance,
            "squad_availability": team.squad_availability,
            "formation_fit": team.formation_fit,
            "lineup_continuity": team.lineup_continuity,
            "lineup_confidence": team.lineup_confidence,
            "observed_lineups_count": team.observed_lineups_count,
            "player_shooting": team.player_shooting_score,
            "player_chance_creation": team.player_chance_creation_score,
            "player_passing": team.player_passing_score,
            "player_progression": team.player_progression_score,
            "player_pressing": team.player_pressing_score,
            "player_defensive_activity": team.player_defensive_activity_score,
            "player_goalkeeping": team.player_goalkeeping_score,
            "player_keeper_sweeping": team.player_keeper_sweeping_score,
            "player_keeper_diving": team.player_keeper_diving_score,
            "player_set_piece_delivery": team.player_set_piece_delivery_score,
            "player_early_goals": team.player_early_goal_score,
            "player_late_goals": team.player_late_goal_score,
            "player_discipline": team.player_discipline_score,
            "player_minutes": team.player_minutes_score,
        },
    }


def load_live_state() -> dict[str, Any]:
    if not LIVE_STATE_PATH.exists():
        return {"source": "manual", "updated_at": None, "eliminated_teams": [], "completed_matches": []}
    with LIVE_STATE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_live_state(state: dict[str, Any]) -> None:
    LIVE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LIVE_STATE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)


def sync_live_team_state_from_results(state: dict[str, Any]) -> None:
    teams = load_teams()
    goals_for: Counter[str] = Counter()
    goals_against: Counter[str] = Counter()
    matches: Counter[str] = Counter()
    for match in state.get("completed_matches", []):
        team_a = match.get("team_a")
        team_b = match.get("team_b")
        if team_a not in teams or team_b not in teams:
            continue
        score_a = int(match.get("team_a_score", 0))
        score_b = int(match.get("team_b_score", 0))
        goals_for[team_a] += score_a
        goals_against[team_a] += score_b
        goals_for[team_b] += score_b
        goals_against[team_b] += score_a
        matches[team_a] += 1
        matches[team_b] += 1

    columns = [
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
    updated_at = state.get("updated_at") or datetime.now(timezone.utc).isoformat()
    rows = []
    for team in sorted(teams):
        games = matches[team]
        goal_delta = (goals_for[team] - goals_against[team]) / games if games else 0.0
        rows.append(
            {
                "team": team,
                "posterior_strength_delta": round(goal_delta * 2.5, 3),
                "live_xg_for": "",
                "live_xg_against": "",
                "injury_load": 0.0,
                "momentum": round(goal_delta, 3),
                "matches_played": int(games),
                "source": "live_state.json",
                "updated_at": updated_at,
            }
        )
    LIVE_TEAM_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LIVE_TEAM_STATE_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    CSV_CACHE.pop(str(LIVE_TEAM_STATE_PATH), None)


def load_cached_model(path: Path = MODEL_PATH) -> Any:
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    if MODEL_CACHE["mtime"] != mtime:
        MODEL_CACHE["bundle"] = load_model(path)
        MODEL_CACHE["mtime"] = mtime
    return MODEL_CACHE["bundle"]


def load_venues() -> dict[str, dict[str, Any]]:
    if not VENUES_PATH.exists():
        return {}
    venues = {}
    with VENUES_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            venue = row["venue"]
            venues[venue] = {
                "venue": venue,
                "city": row["city"],
                "country": row["country"],
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "altitude_m": float(row["altitude_m"]),
            }
    return venues


def load_fixtures() -> list[dict[str, Any]]:
    if not FIXTURES_PATH.exists():
        return []
    mtime = FIXTURES_PATH.stat().st_mtime
    if FIXTURE_CACHE["mtime"] == mtime:
        return FIXTURE_CACHE["fixtures"]

    fixtures = []
    with FIXTURES_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            parsed = dict(row)
            parsed["match_id"] = int(parsed["match_id"])
            fixtures.append(parsed)
    fixtures.sort(key=lambda fixture: fixture["match_id"])
    FIXTURE_CACHE["mtime"] = mtime
    FIXTURE_CACHE["fixtures"] = fixtures
    return fixtures


def fixture_by_id(match_id: int) -> dict[str, Any] | None:
    return next((fixture for fixture in load_fixtures() if fixture["match_id"] == match_id), None)


def fixture_for_team_pair(team_a: str, team_b: str) -> dict[str, Any] | None:
    pair = {team_a, team_b}
    return next(
        (
            fixture
            for fixture in load_fixtures()
            if fixture.get("team_a") and fixture.get("team_b") and {fixture["team_a"], fixture["team_b"]} == pair
        ),
        None,
    )


def group_fixtures(group: str, teams: list[Team]) -> list[dict[str, Any]]:
    team_names = {team.name for team in teams}
    fixtures = [
        fixture
        for fixture in load_fixtures()
        if fixture.get("stage") == "Group"
        and fixture.get("group") == group
        and fixture.get("team_a") in team_names
        and fixture.get("team_b") in team_names
    ]
    return sorted(fixtures, key=lambda fixture: fixture["match_id"]) if len(fixtures) == 6 else []


def parse_fixture_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def fixture_label(fixture: dict[str, Any] | None) -> dict[str, Any] | None:
    if not fixture:
        return None
    return {
        "id": fixture.get("match_id"),
        "stage": fixture.get("stage"),
        "group": fixture.get("group") or None,
        "venue": fixture.get("venue") or None,
        "kickoff_local": fixture.get("kickoff_local") or None,
        "kickoff_utc": fixture.get("kickoff_utc") or None,
        "venue_source": fixture.get("venue_source") or "unknown",
    }


def classify_weather(current: dict[str, Any], venue: dict[str, Any]) -> str:
    temperature = safe_float(current.get("temperature_2m"))
    precipitation = safe_float(current.get("precipitation"))
    wind_speed = safe_float(current.get("wind_speed_10m"))
    altitude = safe_float(venue.get("altitude_m")) or 0.0
    if precipitation is not None and precipitation >= 0.8:
        return "rain"
    if temperature is not None and temperature >= 30:
        return "heat"
    if temperature is not None and temperature <= 3:
        return "cold"
    if altitude >= 1400:
        return "altitude"
    if wind_speed is not None and wind_speed >= 30:
        return "rain"
    return "normal"


def typical_weather_for_fixture(venue: dict[str, Any], kickoff_local: str | None = None) -> dict[str, Any]:
    local = parse_fixture_datetime(kickoff_local)
    hour = local.hour if local else 15
    month = local.month if local else 6
    venue_name = venue["venue"]
    hot_venues = {"Atlanta", "Dallas", "Houston", "Kansas City", "Miami", "Monterrey"}
    weather = "normal"
    if venue["altitude_m"] >= 1400:
        weather = "altitude"
    elif month in {6, 7} and 12 <= hour <= 19 and venue_name in hot_venues:
        weather = "heat"
    elif venue_name in {"Seattle", "Vancouver"} and month in {6, 7}:
        weather = "normal"
    return {
        "weather": weather,
        "weather_source": "venue-climatology",
        "venue_weather": {
            "venue": venue,
            "current": {},
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "note": "Forecast horizon unavailable; using kickoff month/hour and venue climate proxy.",
        },
    }


def weather_context_for_fixture(venue_name: str | None, kickoff_local: str | None = None, kickoff_utc: str | None = None) -> dict[str, Any]:
    if not venue_name:
        return {"weather": "normal", "weather_source": "venue-not-found"}
    cache_key = f"fixture::{venue_name}::{kickoff_local or kickoff_utc or 'current'}"
    if cache_key in WEATHER_CONTEXT_CACHE:
        return WEATHER_CONTEXT_CACHE[cache_key]

    venues = load_venues()
    venue = venues.get(venue_name)
    if not venue:
        return {"weather": "normal", "weather_source": "venue-not-found"}

    local = parse_fixture_datetime(kickoff_local)
    kickoff = parse_fixture_datetime(kickoff_utc)
    if not kickoff and local:
        kickoff = local.astimezone(timezone.utc)
    if not local and kickoff:
        timezone_name = VENUE_TIMEZONES.get(venue_name, "UTC")
        local = kickoff.astimezone(ZoneInfo(timezone_name))

    if not local or not kickoff:
        context = weather_context_for_venue(venue_name)
        WEATHER_CONTEXT_CACHE[cache_key] = context
        return context

    days_until = (kickoff - datetime.now(timezone.utc)).total_seconds() / 86400
    if days_until < -1 or days_until > 16:
        context = typical_weather_for_fixture(venue, local.isoformat())
        WEATHER_CONTEXT_CACHE[cache_key] = context
        return context

    params = {
        "latitude": venue["latitude"],
        "longitude": venue["longitude"],
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
        "start_date": local.date().isoformat(),
        "end_date": local.date().isoformat(),
        "timezone": "auto",
    }
    try:
        response = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=8)
        response.raise_for_status()
        payload = response.json()
        hourly = payload.get("hourly", {})
        times = hourly.get("time") or []
        target = local.replace(tzinfo=None)
        if not times:
            raise ValueError("Open-Meteo returned no hourly times")
        index = min(range(len(times)), key=lambda idx: abs((datetime.fromisoformat(times[idx]) - target).total_seconds()))
        current = {
            "time": times[index],
            "temperature_2m": hourly.get("temperature_2m", [None])[index],
            "relative_humidity_2m": hourly.get("relative_humidity_2m", [None])[index],
            "precipitation": hourly.get("precipitation", [None])[index],
            "wind_speed_10m": hourly.get("wind_speed_10m", [None])[index],
        }
        context = {
            "weather": classify_weather(current, venue),
            "weather_source": "open-meteo-hourly",
            "venue_weather": {
                "venue": venue,
                "current": current,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "kickoff_local": local.isoformat(),
            },
        }
    except (requests.RequestException, ValueError, IndexError) as exc:
        context = typical_weather_for_fixture(venue, local.isoformat())
        context["weather_source"] = "open-meteo-hourly-failed"
        context["weather_error"] = str(exc)

    WEATHER_CONTEXT_CACHE[cache_key] = context
    return context


def weather_context_for_venue(venue_name: str) -> dict[str, Any]:
    if venue_name in WEATHER_CONTEXT_CACHE:
        return WEATHER_CONTEXT_CACHE[venue_name]
    venues = load_venues()
    venue = venues.get(venue_name)
    if not venue:
        return {"weather": "normal", "weather_source": "venue-not-found"}

    params = {
        "latitude": venue["latitude"],
        "longitude": venue["longitude"],
        "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
        "timezone": "auto",
    }
    try:
        response = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=8)
        response.raise_for_status()
    except requests.RequestException as exc:
        fallback = {
            "weather": "altitude" if venue["altitude_m"] >= 1400 else "normal",
            "weather_source": "open-meteo-failed",
            "weather_error": str(exc),
            "venue_weather": {"venue": venue},
        }
        WEATHER_CONTEXT_CACHE[venue_name] = fallback
        return fallback

    payload = response.json()
    current = payload.get("current", {})
    weather = classify_weather(current, venue)
    context = {
        "weather": weather,
        "weather_source": "open-meteo",
        "venue_weather": {
            "venue": venue,
            "current": current,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    WEATHER_CONTEXT_CACHE[venue_name] = context
    return context


def venue_weather_payload(venue_name: str) -> dict[str, Any]:
    context = weather_context_for_venue(venue_name)
    detail = context.get("venue_weather", {})
    return {
        **context,
        "source": context.get("weather_source"),
        "venue": detail.get("venue"),
        "current": detail.get("current", {}),
        "fetched_at": detail.get("fetched_at"),
    }


def haversine_km(first: dict[str, Any], second: dict[str, Any]) -> float:
    radius_km = 6371.0
    lat1 = math.radians(float(first["latitude"]))
    lon1 = math.radians(float(first["longitude"]))
    lat2 = math.radians(float(second["latitude"]))
    lon2 = math.radians(float(second["longitude"]))
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 2 * radius_km * math.asin(min(1.0, math.sqrt(value)))


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def venue_distance_km(from_venue: str | None, to_venue: str | None) -> float:
    if not from_venue or not to_venue or from_venue == to_venue:
        return 0.0
    venues = load_venues()
    if from_venue not in venues or to_venue not in venues:
        return 0.0
    return haversine_km(venues[from_venue], venues[to_venue])


def team_support_score(team: Team, venue: dict[str, Any] | None) -> float:
    score = FAN_BASE_INDEX.get(team.name, 0.45)
    if not venue:
        return score

    host_country = HOST_COUNTRY_BY_TEAM.get(team.name)
    if host_country and host_country == venue["country"]:
        score += 1.20
    elif host_country:
        score += 0.35

    if team.confederation == "CONCACAF":
        score += 0.25
    if venue["country"] == "USA" and team.name in {"Mexico", "Colombia", "Argentina", "Brazil", "England", "Portugal"}:
        score += 0.18
    if venue["country"] == "Mexico" and team.name in {"USA", "Argentina", "Brazil", "Colombia"}:
        score += 0.12
    if venue["country"] == "Canada" and team.name in {"USA", "Mexico", "England", "France"}:
        score += 0.10
    return score


def initial_travel_load(team: Team, venue: dict[str, Any] | None) -> float:
    if venue and HOST_COUNTRY_BY_TEAM.get(team.name) == venue["country"]:
        return 8.0
    if team.host:
        return 22.0
    return CONFEDERATION_TRAVEL_LOAD.get(team.confederation, 50.0)


def team_travel_load(team: Team, venue_name: str | None, route_state: dict[str, dict[str, Any]]) -> float:
    state = route_state.get(team.name, {})
    if state.get("last_venue"):
        distance = venue_distance_km(state.get("last_venue"), venue_name)
        return clamp(8 + (distance / 45), 0, 100)
    venue = load_venues().get(venue_name or "")
    return initial_travel_load(team, venue)


def team_rest_days(team: Team, kickoff: datetime | None, route_state: dict[str, dict[str, Any]]) -> float | None:
    previous = parse_fixture_datetime(route_state.get(team.name, {}).get("last_kickoff"))
    if not previous or not kickoff:
        return None
    return max(0.0, (kickoff - previous).total_seconds() / 86400)


def team_fatigue_load(team: Team, travel_load: float, rest_days: float | None) -> float:
    rest_penalty = 0.0 if rest_days is None else max(0.0, 5.0 - rest_days) * 12.0
    lineup_confidence = team.lineup_confidence or 55.0
    lineup_uncertainty = max(0.0, 82.0 - lineup_confidence) * 0.10
    depth_relief = max(0.0, ((team.bench + team.injury_resilience) / 2) - 75.0) * 0.18
    return clamp(12.0 + (travel_load * 0.34) + rest_penalty + lineup_uncertainty - depth_relief, 0, 100)


def automatic_fixture_context(
    context: dict[str, Any],
    fixture: dict[str, Any] | None,
    team_a: Team,
    team_b: Team,
    route_state: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    route_state = route_state if route_state is not None else {}
    fixture_context = dict(context)
    venue_name = (fixture or {}).get("venue") or context.get("venue")
    venue = load_venues().get(venue_name or "")
    kickoff = parse_fixture_datetime((fixture or {}).get("kickoff_utc"))

    if venue_name:
        fixture_context["venue"] = venue_name
    if context.get("weather") == "auto" and venue_name:
        fixture_context.update(
            weather_context_for_fixture(
                venue_name,
                (fixture or {}).get("kickoff_local"),
                (fixture or {}).get("kickoff_utc"),
            )
        )

    travel_a = team_travel_load(team_a, venue_name, route_state)
    travel_b = team_travel_load(team_b, venue_name, route_state)
    rest_a = team_rest_days(team_a, kickoff, route_state)
    rest_b = team_rest_days(team_b, kickoff, route_state)
    fatigue_a = team_fatigue_load(team_a, travel_a, rest_a)
    fatigue_b = team_fatigue_load(team_b, travel_b, rest_b)
    support_a = team_support_score(team_a, venue)
    support_b = team_support_score(team_b, venue)

    fixture_context.update(
        {
            "auto_fixture_context": True,
            "match_id": (fixture or {}).get("match_id"),
            "fixture": fixture_label(fixture),
            "team_travel": {team_a.name: round(travel_a, 1), team_b.name: round(travel_b, 1)},
            "team_fatigue": {team_a.name: round(fatigue_a, 1), team_b.name: round(fatigue_b, 1)},
            "rest_days": {
                team_a.name: round(rest_a, 2) if rest_a is not None else None,
                team_b.name: round(rest_b, 2) if rest_b is not None else None,
            },
            "fan_edges": {
                team_a.name: round(clamp(support_a - support_b, -1.8, 1.8), 2),
                team_b.name: round(clamp(support_b - support_a, -1.8, 1.8), 2),
            },
            "support_scores": {team_a.name: round(support_a, 2), team_b.name: round(support_b, 2)},
        }
    )
    return fixture_context


def update_route_state(route_state: dict[str, dict[str, Any]], fixture: dict[str, Any] | None, *teams: Team) -> None:
    if not fixture:
        return
    venue = fixture.get("venue")
    kickoff = fixture.get("kickoff_utc")
    if not venue or not kickoff:
        return
    for team in teams:
        route_state[team.name] = {
            "last_venue": venue,
            "last_kickoff": kickoff,
            "last_match_id": fixture.get("match_id"),
        }


def compact_fixture_context(context: dict[str, Any], team_a: Team, team_b: Team) -> dict[str, Any]:
    return {
        "fixture": context.get("fixture"),
        "weather": context.get("weather"),
        "weather_source": context.get("weather_source"),
        "team_travel": {
            team_a.name: context.get("team_travel", {}).get(team_a.name),
            team_b.name: context.get("team_travel", {}).get(team_b.name),
        },
        "team_fatigue": {
            team_a.name: context.get("team_fatigue", {}).get(team_a.name),
            team_b.name: context.get("team_fatigue", {}).get(team_b.name),
        },
        "rest_days": {
            team_a.name: context.get("rest_days", {}).get(team_a.name),
            team_b.name: context.get("rest_days", {}).get(team_b.name),
        },
        "fan_edges": {
            team_a.name: context.get("fan_edges", {}).get(team_a.name),
            team_b.name: context.get("fan_edges", {}).get(team_b.name),
        },
    }


def matchup_context(context: dict[str, Any], team_a: Team, team_b: Team) -> dict[str, Any]:
    fixture = None
    if context.get("venue"):
        fixture = {
            "match_id": None,
            "stage": "Match Lab",
            "group": "",
            "venue": context.get("venue"),
            "venue_source": "selected-match-venue",
            "kickoff_local": None,
            "kickoff_utc": None,
        }
    else:
        fixture = fixture_for_team_pair(team_a.name, team_b.name)
    return automatic_fixture_context(context, fixture, team_a, team_b, {}) if fixture else context


def load_player_candidates() -> dict[str, list[dict[str, Any]]]:
    players: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not PLAYERS_PATH.exists():
        return players

    with PLAYERS_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            team = row["team"]
            players[team].append(
                {
                    "team": team,
                    "player": row["player"],
                    "position": row["position"],
                    "scoring_weight": float(row["scoring_weight"]),
                    "starter": row["starter"] == "1",
                    "penalty_taker": row["penalty_taker"] == "1",
                    "flag": FLAG_CODE_BY_TEAM.get(team, "un").upper(),
                    "flag_code": FLAG_CODE_BY_TEAM.get(team, "un"),
                    "flag_image": f"https://flagcdn.com/w80/{FLAG_CODE_BY_TEAM.get(team, 'un')}.png",
                }
            )
    return players


def load_squads(team: str | None = None) -> list[dict[str, Any]]:
    if not SQUADS_PATH.exists():
        return []
    rows = []
    with SQUADS_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if team and row["team"] != team:
                continue
            rows.append(
                {
                    **row,
                    "number": int(row["number"]) if row["number"] else None,
                    "age": int(row["age"]) if row["age"] else None,
                    "caps": int(row["caps"]),
                    "international_goals": int(row["international_goals"]),
                    "market_value_eur": float(row["market_value_eur"]),
                    "projected_starter": row["projected_starter"] == "1",
                    "observed_start_rate": float(row.get("observed_start_rate") or 0),
                    "lineup_confidence": float(row.get("lineup_confidence") or 0),
                    "availability": float(row["availability"]),
                }
            )
    return rows


def load_player_match_stats(team: str | None = None) -> list[dict[str, Any]]:
    if not PLAYER_MATCH_STATS_PATH.exists():
        return []
    rows = []
    numeric_fields = {
        "projected_starter",
        "availability",
        "season_minutes",
        "appearances",
        "starts",
        "weak_foot_usage_pct",
        "goals_per90",
        "assists_per90",
        "xg_per90",
        "xa_per90",
        "shots_per90",
        "shots_on_target_per90",
        "touches_att_pen_area_per90",
        "key_passes_per90",
        "passes_attempted_per90",
        "pass_completion_pct",
        "progressive_passes_per90",
        "progressive_carries_per90",
        "successful_dribbles_per90",
        "dribble_success_pct",
        "crosses_per90",
        "cross_completion_pct",
        "through_balls_per90",
        "set_piece_xa_per90",
        "pressures_per90",
        "pressure_success_pct",
        "tackles_interceptions_per90",
        "tackle_success_pct",
        "blocks_clearances_per90",
        "aerial_win_pct",
        "ball_recoveries_per90",
        "fouls_committed_per90",
        "cards_per90",
        "offsides_per90",
        "goals_0_15_share",
        "goals_16_30_share",
        "goals_31_45_share",
        "goals_46_60_share",
        "goals_61_75_share",
        "goals_76_90_share",
        "saves_per90",
        "save_pct",
        "post_shot_xg_prevented_per90",
        "keeper_claims_per90",
        "keeper_sweeper_actions_per90",
        "keeper_dives_per90",
        "keeper_long_pass_completion_pct",
        "penalty_taken_count",
        "penalty_goal_pct",
        "penalty_left_pct",
        "penalty_center_pct",
        "penalty_right_pct",
        "penalty_saved_pct",
        "penalty_miss_pct",
        "keeper_penalty_faced",
        "keeper_penalty_save_pct",
        "keeper_penalty_dive_left_pct",
        "keeper_penalty_dive_center_pct",
        "keeper_penalty_dive_right_pct",
    }
    with PLAYER_MATCH_STATS_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if team and row["team"] != team:
                continue
            parsed = dict(row)
            for field in numeric_fields:
                parsed[field] = float(parsed[field]) if parsed.get(field) not in {"", None} else 0.0
            rows.append(parsed)
    return rows


def load_player_match_team_features(team: str | None = None) -> list[dict[str, Any]]:
    if not PLAYER_MATCH_TEAM_FEATURES_PATH.exists():
        return []
    rows = []
    with PLAYER_MATCH_TEAM_FEATURES_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if team and row["team"] != team:
                continue
            rows.append(
                {
                    key: float(value) if key != "team" and value != "" else value
                    for key, value in row.items()
                }
            )
    return rows


def compact_player_trait(player: dict[str, Any]) -> dict[str, Any]:
    scoring_window = {
        "0-15": player["goals_0_15_share"],
        "16-30": player["goals_16_30_share"],
        "31-45": player["goals_31_45_share"],
        "46-60": player["goals_46_60_share"],
        "61-75": player["goals_61_75_share"],
        "76-90": player["goals_76_90_share"],
    }
    likely_window = max(scoring_window.items(), key=lambda item: item[1])[0]
    return {
        "team": player["team"],
        "player": player["player"],
        "position": player["position"],
        "detailed_position": player["detailed_position"],
        "club": player["club"],
        "preferred_foot": player.get("preferred_foot", ""),
        "weak_foot_usage_pct": player["weak_foot_usage_pct"],
        "tactical_role": player.get("tactical_role", ""),
        "formation_role": player.get("formation_role", ""),
        "tactic_profile": player.get("tactic_profile", ""),
        "projected_starter": bool(int(player["projected_starter"])),
        "season_minutes": int(player["season_minutes"]),
        "goals_per90": player["goals_per90"],
        "assists_per90": player["assists_per90"],
        "xg_per90": player["xg_per90"],
        "xa_per90": player["xa_per90"],
        "shots_per90": player["shots_per90"],
        "shots_on_target_per90": player["shots_on_target_per90"],
        "touches_att_pen_area_per90": player["touches_att_pen_area_per90"],
        "key_passes_per90": player["key_passes_per90"],
        "passes_attempted_per90": player["passes_attempted_per90"],
        "pass_completion_pct": player["pass_completion_pct"],
        "progressive_passes_per90": player["progressive_passes_per90"],
        "progressive_carries_per90": player["progressive_carries_per90"],
        "successful_dribbles_per90": player["successful_dribbles_per90"],
        "dribble_success_pct": player["dribble_success_pct"],
        "crosses_per90": player["crosses_per90"],
        "cross_completion_pct": player["cross_completion_pct"],
        "through_balls_per90": player["through_balls_per90"],
        "set_piece_xa_per90": player["set_piece_xa_per90"],
        "pressures_per90": player["pressures_per90"],
        "pressure_success_pct": player["pressure_success_pct"],
        "tackles_interceptions_per90": player["tackles_interceptions_per90"],
        "tackle_success_pct": player["tackle_success_pct"],
        "blocks_clearances_per90": player["blocks_clearances_per90"],
        "aerial_win_pct": player["aerial_win_pct"],
        "ball_recoveries_per90": player["ball_recoveries_per90"],
        "fouls_committed_per90": player["fouls_committed_per90"],
        "cards_per90": player["cards_per90"],
        "offsides_per90": player["offsides_per90"],
        "likely_scoring_window": likely_window,
        "late_goal_share": player["goals_76_90_share"],
        "save_pct": player["save_pct"],
        "saves_per90": player["saves_per90"],
        "post_shot_xg_prevented_per90": player["post_shot_xg_prevented_per90"],
        "keeper_claims_per90": player["keeper_claims_per90"],
        "keeper_dives_per90": player["keeper_dives_per90"],
        "keeper_sweeper_actions_per90": player["keeper_sweeper_actions_per90"],
        "keeper_long_pass_completion_pct": player["keeper_long_pass_completion_pct"],
        "penalty_taken_count": int(player["penalty_taken_count"]),
        "penalty_goal_pct": player["penalty_goal_pct"],
        "penalty_preferred_placement": player.get("penalty_preferred_placement", ""),
        "penalty_left_pct": player["penalty_left_pct"],
        "penalty_center_pct": player["penalty_center_pct"],
        "penalty_right_pct": player["penalty_right_pct"],
        "penalty_saved_pct": player["penalty_saved_pct"],
        "penalty_miss_pct": player["penalty_miss_pct"],
        "keeper_penalty_faced": int(player["keeper_penalty_faced"]),
        "keeper_penalty_save_pct": player["keeper_penalty_save_pct"],
        "keeper_penalty_dive_preference": player.get("keeper_penalty_dive_preference", ""),
        "keeper_penalty_dive_left_pct": player["keeper_penalty_dive_left_pct"],
        "keeper_penalty_dive_center_pct": player["keeper_penalty_dive_center_pct"],
        "keeper_penalty_dive_right_pct": player["keeper_penalty_dive_right_pct"],
        "source": player["source"],
        "updated_at": player["updated_at"],
    }


def pick_scorer(team_name: str, candidates: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    team_players = candidates.get(team_name)
    if not team_players:
        return {
            "team": team_name,
            "player": f"{team_name} scorer",
            "position": "FW",
            "flag": FLAG_CODE_BY_TEAM.get(team_name, "un").upper(),
            "flag_code": FLAG_CODE_BY_TEAM.get(team_name, "un"),
            "flag_image": f"https://flagcdn.com/w80/{FLAG_CODE_BY_TEAM.get(team_name, 'un')}.png",
        }

    weights = []
    for player in team_players:
        weight = player["scoring_weight"]
        if player["starter"]:
            weight *= 1.15
        if player["penalty_taker"]:
            weight *= 1.08
        weights.append(weight)
    return random.choices(team_players, weights=weights, k=1)[0]


def completed_match_lookup(state: dict[str, Any]) -> dict[frozenset[str], dict[str, Any]]:
    matches = {}
    for match in state.get("completed_matches", []):
        team_a = match.get("team_a")
        team_b = match.get("team_b")
        if team_a and team_b:
            matches[frozenset((team_a, team_b))] = match
    return matches


def resolve_match_score(
    team_a: Team,
    team_b: Team,
    completed: dict[frozenset[str], dict[str, Any]],
    bundle: Any,
    context: dict[str, Any],
    knockout: bool = False,
) -> tuple[int, int, bool]:
    locked = completed.get(frozenset((team_a.name, team_b.name)))
    if locked:
        if locked["team_a"] == team_a.name:
            return int(locked["team_a_score"]), int(locked["team_b_score"]), True
        return int(locked["team_b_score"]), int(locked["team_a_score"]), True
    goals_a, goals_b = play_context_match(team_a, team_b, bundle, context, knockout)
    return goals_a, goals_b, False


def context_expected_goals(
    team: Team,
    opponent: Team,
    bundle: Any,
    context: dict[str, Any],
    knockout: bool = False,
) -> float:
    if bundle:
        lambda_a, lambda_b = model_expected_goals(team, opponent, bundle, knockout)
        base = lambda_a
    else:
        base = expected_goals(team, opponent, knockout)

    weather = context.get("weather", "normal")
    weather_factor = {
        "normal": 1.0,
        "heat": 0.93,
        "rain": 0.90,
        "cold": 0.96,
        "altitude": 0.92,
    }.get(weather, 1.0)
    weather_row = next((row for row in load_csv_rows(WEATHER_EFFECTS_PATH) if row.get("weather") == weather), {})
    if weather_row:
        weather_factor = csv_float(weather_row, "goal_multiplier", weather_factor)

    team_travel = context.get("team_travel") or {}
    team_fatigue = context.get("team_fatigue") or {}
    fan_edges = context.get("fan_edges") or {}
    travel = float(team_travel.get(team.name, context.get("travel", 20)))
    fatigue = float(team_fatigue.get(team.name, context.get("fatigue", 20)))
    home_advantage = float(context.get("home_advantage", 1.0))
    fan_edge = float(fan_edges.get(team.name, 0.0))
    resilience = ((team.fitness + team.bench + team.injury_resilience) - 230) / 100
    weather_resilience = (team.fitness - opponent.fitness) / 500
    set_piece_edge = (team.set_piece_attack - opponent.set_piece_defense) / 100
    transition_edge = (team.transition_speed - opponent.pressing_intensity) / 100
    tactical_edge = (team.tactical_flexibility - opponent.tactical_flexibility) / 100
    discipline_edge = (team.discipline - opponent.discipline) / 100
    pressure_edge = (team.big_match_composure - opponent.big_match_composure) / 100
    player_attack_edge = (
        (team.player_shooting_score + team.player_chance_creation_score + team.player_progression_score + team.player_set_piece_delivery_score) / 4
        - ((opponent.player_defensive_activity_score + opponent.player_goalkeeping_score) / 2)
    ) / 100
    player_control_edge = ((team.player_passing_score + team.player_pressing_score) - (opponent.player_passing_score + opponent.player_pressing_score)) / 200
    player_timing_edge = ((team.player_early_goal_score + team.player_late_goal_score) - 140) / 100
    player_minutes_edge = (team.player_minutes_score - opponent.player_minutes_score) / 100
    opponent_discipline_vulnerability = (70 - opponent.player_discipline_score) / 100
    xg_zone_edge = xg_forecast_edge(team.name, opponent.name)
    pressing_heat_drag = 0.0
    if weather == "heat":
        pressing_heat_drag = max(0.0, (team.pressing_intensity - 80) / 100) * 0.08
    weather_set_piece_boost = 0.05 * set_piece_edge if weather in {"rain", "cold"} else 0.0
    fatigue_factor = 1 - (fatigue * 0.0018) + (resilience * fatigue * 0.0009)
    travel_factor = 1 - (travel * 0.0012) + (team.fitness - 80) * 0.001
    manual_host_boost = 0.10 * home_advantage if team.host and not context.get("auto_fixture_context") else 0.0
    fixture_crowd_boost = 0.055 * fan_edge
    lineup_uncertainty_drag = max(0.0, 72.0 - (team.lineup_confidence or 55.0)) * 0.0015
    advanced_signal = advanced_matchup_signals(team, opponent, context, knockout)

    adjusted = base * weather_factor * fatigue_factor * travel_factor
    adjusted += (
        weather_resilience
        + weather_set_piece_boost
        + (0.06 * transition_edge)
        + (0.04 * tactical_edge)
        + (0.03 * discipline_edge)
        + (0.05 * pressure_edge if knockout else 0.0)
        + (0.10 * player_attack_edge)
        + (0.04 * player_control_edge)
        + (0.03 * player_timing_edge)
        + (0.03 * player_minutes_edge)
        + (0.025 * opponent_discipline_vulnerability)
        + (0.08 * xg_zone_edge)
        + manual_host_boost
        + fixture_crowd_boost
        + advanced_signal["xg_delta"]
        - pressing_heat_drag
        - lineup_uncertainty_drag
    )
    return max(0.12, min(4.2, adjusted))


def load_xg_team_signals() -> dict[str, dict[str, Any]]:
    if not XG_TEAM_ZONES_PATH.exists():
        return {}
    mtime = XG_TEAM_ZONES_PATH.stat().st_mtime
    if XG_SIGNAL_CACHE["mtime"] == mtime:
        return XG_SIGNAL_CACHE["signals"]

    grouped: dict[str, dict[str, float]] = defaultdict(lambda: {
        "shots": 0.0,
        "predicted_goals": 0.0,
        "actual_goals": 0.0,
        "high_quality_shots": 0.0,
        "best_avg_xg": 0.0,
    })
    with XG_TEAM_ZONES_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            team = row.get("team", "")
            if not team:
                continue
            shots = float(row.get("shots") or 0)
            predicted = float(row.get("predicted_goals") or 0)
            actual = float(row.get("actual_goals") or 0)
            avg_xg = float(row.get("avg_xg") or 0)
            signal = grouped[team]
            signal["shots"] += shots
            signal["predicted_goals"] += predicted
            signal["actual_goals"] += actual
            signal["best_avg_xg"] = max(signal["best_avg_xg"], avg_xg)
            if avg_xg >= 0.15:
                signal["high_quality_shots"] += shots

    output = {}
    for team, raw in grouped.items():
        shots = max(raw["shots"], 1.0)
        avg_xg = raw["predicted_goals"] / shots
        finishing_delta = (raw["actual_goals"] - raw["predicted_goals"]) / shots
        high_quality_share = raw["high_quality_shots"] / shots
        attack_index = ((avg_xg - 0.12) * 1.15) + ((high_quality_share - 0.30) * 0.25) + (finishing_delta * 0.18)
        output[team] = {
            "shots": int(raw["shots"]),
            "predicted_goals": round(raw["predicted_goals"], 3),
            "actual_goals": int(raw["actual_goals"]),
            "avg_xg": round(avg_xg, 3),
            "high_quality_share": round(high_quality_share, 3),
            "best_avg_xg": round(raw["best_avg_xg"], 3),
            "finishing_delta": round(raw["actual_goals"] - raw["predicted_goals"], 3),
            "attack_index": round(attack_index, 4),
        }
    XG_SIGNAL_CACHE["mtime"] = mtime
    XG_SIGNAL_CACHE["signals"] = output
    return output


def xg_forecast_edge(team: str, opponent: str) -> float:
    signals = load_xg_team_signals()
    team_signal = signals.get(team)
    opponent_signal = signals.get(opponent)
    if not team_signal or not opponent_signal:
        return 0.0
    edge = float(team_signal["attack_index"]) - float(opponent_signal["attack_index"])
    return max(-0.24, min(0.24, edge))


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    cache_key = str(path)
    mtime = path.stat().st_mtime
    cached = CSV_CACHE.get(cache_key)
    if cached and cached["mtime"] == mtime:
        return cached["rows"]
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    CSV_CACHE[cache_key] = {"mtime": mtime, "rows": rows}
    return rows


def csv_float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key)
    if value in {"", None}:
        return default
    try:
        return float(str(value).replace("+", ""))
    except ValueError:
        return default


def csv_bool(row: dict[str, Any], key: str) -> bool:
    return str(row.get(key, "")).strip().lower() in {"1", "true", "yes", "confirmed"}


def team_match_rows(path: Path, team: str, match_id: int | str | None = None) -> list[dict[str, str]]:
    rows = [row for row in load_csv_rows(path) if row.get("team") == team]
    if match_id not in {None, ""}:
        exact = [row for row in rows if str(row.get("match_id", "")).strip() == str(match_id)]
        if exact:
            return exact
    generic = [row for row in rows if not str(row.get("match_id", "")).strip()]
    return generic or rows


def team_profile_row(path: Path, team: str) -> dict[str, str]:
    return next((row for row in load_csv_rows(path) if row.get("team") == team), {})


def signal_quality_label(score: float) -> str:
    if score >= 78:
        return "Strong"
    if score >= 55:
        return "Usable"
    return "Starter"


def availability_signal(team: Team, match_id: int | str | None = None) -> dict[str, Any]:
    rows = team_match_rows(AVAILABILITY_PATH, team.name, match_id)
    if not rows:
        injury_load = max(0.0, 1.0 - (team.squad_availability / 100))
        return {
            "label": "Availability",
            "xg_delta": round(-0.12 * injury_load, 4),
            "quality": "Team aggregate",
            "availability_index": round(1 - injury_load, 3),
            "injury_load": round(injury_load, 3),
            "unavailable_key_players": [],
            "detail": "Using team aggregate availability until player availability rows are synced.",
        }

    status_weight = {
        "available": 1.0,
        "probable": 0.9,
        "limited": 0.72,
        "questionable": 0.60,
        "doubtful": 0.42,
        "unavailable": 0.0,
        "injured": 0.0,
        "out": 0.0,
        "suspended": 0.0,
    }
    total_weight = 0.0
    available_weight = 0.0
    unavailable = []
    provider_rows = 0
    for row in rows:
        source = (row.get("source") or "").lower()
        provider_rows += int(source not in {"squad-projection", "projection", ""})
        impact = csv_float(row, "impact_score", 50.0)
        status = (row.get("status") or "available").strip().lower()
        availability = csv_float(row, "availability", status_weight.get(status, 0.0 if status else 1.0))
        minutes = csv_float(row, "minutes_limit", 90.0)
        availability = min(availability, clamp(minutes / 90, 0, 1))
        availability = clamp(availability, 0, 1)
        total_weight += impact
        available_weight += impact * availability
        if availability < 0.75:
            unavailable.append(
                {
                    "player": row.get("player"),
                    "status": status,
                    "impact": round(impact, 1),
                    "availability": round(availability, 2),
                }
            )

    availability_index = available_weight / max(total_weight, 1.0)
    injury_load = 1 - availability_index
    quality = "Provider" if provider_rows else "Projection"
    return {
        "label": "Availability",
        "xg_delta": round(clamp(-0.17 * injury_load, -0.16, 0.0), 4),
        "quality": quality,
        "availability_index": round(availability_index, 3),
        "injury_load": round(injury_load, 3),
        "unavailable_key_players": sorted(unavailable, key=lambda item: item["impact"], reverse=True)[:5],
        "detail": f"{team.name} player availability index {availability_index:.2f}.",
    }


def lineup_signal(team: Team, match_id: int | str | None = None) -> dict[str, Any]:
    rows = team_match_rows(CONFIRMED_LINEUPS_PATH, team.name, match_id)
    if not rows:
        confidence = team.lineup_confidence or 55.0
        delta = clamp((confidence - 68) * 0.0014, -0.045, 0.04)
        return {
            "label": "Confirmed XI",
            "xg_delta": round(delta, 4),
            "quality": "Team aggregate",
            "starter_count": 0,
            "confidence": round(confidence, 1),
            "detail": f"Using team lineup confidence {confidence:.1f}%.",
        }

    starters = [row for row in rows if csv_bool(row, "starter")]
    confirmed = any(csv_bool(row, "confirmed") for row in rows)
    avg_confidence = sum(csv_float(row, "confidence", 55.0) for row in rows) / max(len(rows), 1)
    starter_count = len(starters)
    starter_shape = clamp((starter_count - 9.5) / 3.0, -1, 1)
    confidence_shape = clamp((avg_confidence - 66) / 34, -1, 1)
    delta = (0.022 * starter_shape) + (0.038 * confidence_shape)
    quality = "Confirmed" if confirmed else "Projected"
    return {
        "label": "Confirmed XI",
        "xg_delta": round(clamp(delta, -0.06, 0.06), 4),
        "quality": quality,
        "starter_count": starter_count,
        "confidence": round(avg_confidence, 1),
        "formation": next((row.get("formation") for row in rows if row.get("formation")), None),
        "detail": f"{starter_count} starters; lineup confidence {avg_confidence:.1f}%.",
    }


def market_rows_for_pair(team_a: str, team_b: str) -> list[dict[str, str]]:
    pair = {team_a, team_b}
    return [
        row
        for row in load_csv_rows(MARKET_SIGNALS_PATH)
        if row.get("team_a") and row.get("team_b") and {row["team_a"], row["team_b"]} == pair
    ]


def market_signal(team: Team, opponent: Team) -> dict[str, Any]:
    rows = market_rows_for_pair(team.name, opponent.name)
    if not rows:
        return {
            "label": "Market probability",
            "xg_delta": 0.0,
            "quality": "Needs odds",
            "market_probability": None,
            "detail": "No match odds snapshot for this pair yet.",
        }

    team_probs = []
    opponent_probs = []
    movements = []
    example_rows = 0
    for row in rows:
        if row.get("team_a") == team.name:
            team_probs.append(csv_float(row, "market_probability_a"))
            opponent_probs.append(csv_float(row, "market_probability_b"))
            movements.append(csv_float(row, "line_movement_a"))
        else:
            team_probs.append(csv_float(row, "market_probability_b"))
            opponent_probs.append(csv_float(row, "market_probability_a"))
            movements.append(csv_float(row, "line_movement_b"))
        notes = (row.get("notes") or "").lower()
        example_rows += int("example" in notes)

    team_probability = sum(team_probs) / max(len(team_probs), 1)
    opponent_probability = sum(opponent_probs) / max(len(opponent_probs), 1)
    movement = sum(movements) / max(len(movements), 1)
    impact_scale = 0.35 if example_rows == len(rows) else 1.0
    edge = team_probability - opponent_probability
    delta = impact_scale * ((0.10 * edge) + (0.045 * movement))
    quality = "Example odds" if impact_scale < 1 else "Market"
    return {
        "label": "Market probability",
        "xg_delta": round(clamp(delta, -0.08, 0.08), 4),
        "quality": quality,
        "market_probability": round(team_probability, 4),
        "opponent_market_probability": round(opponent_probability, 4),
        "line_movement": round(movement, 4),
        "detail": f"Market no-vig probability {team_probability:.1%} vs {opponent_probability:.1%}.",
    }


def tactical_signal(team: Team, opponent: Team) -> dict[str, Any]:
    profile = team_profile_row(TACTICAL_PROFILES_PATH, team.name)
    opponent_profile = team_profile_row(TACTICAL_PROFILES_PATH, opponent.name)
    if not profile or not opponent_profile:
        return {"label": "Tactical matchup", "xg_delta": 0.0, "quality": "Needs profile", "detail": "No tactical profile rows yet."}

    pressing = csv_float(profile, "pressing", team.pressing_intensity)
    build_up = csv_float(profile, "build_up", team.player_passing_score)
    transition = csv_float(profile, "transition", team.transition_speed)
    width = csv_float(profile, "width", 70.0)
    opponent_build_up = csv_float(opponent_profile, "build_up", opponent.player_passing_score)
    opponent_line = csv_float(opponent_profile, "defensive_line", opponent.pressing_intensity)
    opponent_width = csv_float(opponent_profile, "width", 70.0)

    press_edge = clamp((pressing - opponent_build_up) / 100, -0.45, 0.45)
    transition_edge = clamp((transition - opponent_line) / 100, -0.45, 0.45)
    width_edge = clamp((width - opponent_width) / 100, -0.35, 0.35)
    formation_edge = clamp((team.formation_fit - opponent.formation_fit) / 100, -0.35, 0.35)
    raw = (0.34 * press_edge) + (0.34 * transition_edge) + (0.14 * width_edge) + (0.18 * formation_edge)
    return {
        "label": "Tactical matchup",
        "xg_delta": round(clamp(0.12 * raw, -0.075, 0.075), 4),
        "quality": "Derived profile",
        "formation": profile.get("formation"),
        "press_edge": round(press_edge, 3),
        "transition_edge": round(transition_edge, 3),
        "detail": f"{profile.get('formation', 'profile')} vs {opponent_profile.get('formation', 'profile')}: press {press_edge:+.2f}, transition {transition_edge:+.2f}.",
    }


def weather_effect_signal(team: Team, opponent: Team, context: dict[str, Any]) -> dict[str, Any]:
    weather = context.get("weather", "normal")
    row = next((item for item in load_csv_rows(WEATHER_EFFECTS_PATH) if item.get("weather") == weather), {})
    if not row:
        return {"label": "Weather backtest", "xg_delta": 0.0, "quality": "Built-in", "detail": f"No learned weather row for {weather}."}

    pressing_penalty = csv_float(row, "pressing_penalty")
    set_piece_bonus = csv_float(row, "set_piece_bonus")
    keeper_handling = csv_float(row, "keeper_handling_penalty")
    pressing_drag = pressing_penalty * max(0.0, team.pressing_intensity - 78) / 100
    set_piece_edge = clamp((team.set_piece_attack - opponent.set_piece_defense) / 100, -0.4, 0.4)
    keeper_bonus = keeper_handling * max(0.0, 82 - opponent.player_goalkeeping_score) / 100
    delta = (-pressing_drag) + (set_piece_bonus * set_piece_edge) + keeper_bonus
    return {
        "label": "Weather backtest",
        "xg_delta": round(clamp(delta, -0.055, 0.045), 4),
        "quality": row.get("source") or "Starter prior",
        "goal_multiplier": csv_float(row, "goal_multiplier", 1.0),
        "detail": f"{weather} profile: pressing {pressing_penalty:.2f}, set-piece {set_piece_bonus:.2f}.",
    }


def set_piece_signal(team: Team, opponent: Team, context: dict[str, Any]) -> dict[str, Any]:
    profile = team_profile_row(SET_PIECE_PROFILES_PATH, team.name)
    opponent_profile = team_profile_row(SET_PIECE_PROFILES_PATH, opponent.name)
    if not profile or not opponent_profile:
        return {"label": "Set pieces", "xg_delta": 0.0, "quality": "Needs profile", "detail": "No set-piece profile rows yet."}

    attack = (
        csv_float(profile, "corner_xg") * 650
        + csv_float(profile, "free_kick_xg") * 420
        + csv_float(profile, "aerial_threat") * 0.26
        + csv_float(profile, "delivery_quality") * 0.34
    )
    opponent_resistance = 100 - csv_float(opponent_profile, "set_piece_concede_risk", 20.0)
    edge = clamp((attack - opponent_resistance) / 100, -0.55, 0.55)
    weather_bonus = 1.15 if context.get("weather") in {"rain", "cold"} else 1.0
    delta = 0.082 * edge * weather_bonus
    return {
        "label": "Set pieces",
        "xg_delta": round(clamp(delta, -0.07, 0.07), 4),
        "quality": "Derived profile",
        "set_piece_edge": round(edge, 3),
        "detail": f"Dead-ball edge {edge:+.2f}; weather multiplier {weather_bonus:.2f}.",
    }


def goalkeeper_signal(team: Team, opponent: Team) -> dict[str, Any]:
    profile = team_profile_row(GOALKEEPER_PROFILES_PATH, opponent.name)
    if profile:
        save_pct = csv_float(profile, "save_pct", opponent.player_goalkeeping_score / 100)
        prevented = csv_float(profile, "post_shot_xg_prevented_per90")
        attack = (team.player_shooting_score * 0.65) + (team.player_chance_creation_score * 0.35)
        keeper_score = (save_pct * 100 * 0.70) + ((70 + prevented * 80) * 0.30)
        edge = clamp((attack - keeper_score) / 100, -0.5, 0.5)
        return {
            "label": "Post-shot GK",
            "xg_delta": round(clamp(0.09 * edge, -0.06, 0.06), 4),
            "quality": profile.get("source") or "Provider",
            "keeper": profile.get("keeper"),
            "save_pct": round(save_pct, 3),
            "post_shot_xg_prevented_per90": round(prevented, 3),
            "attacking_shot_quality": round(attack, 1),
            "opponent_keeper_score": round(keeper_score, 1),
            "detail": f"Shot quality {attack:.1f} vs {opponent.name} keeper profile {keeper_score:.1f}.",
        }

    opponent_keeper = (
        opponent.player_goalkeeping_score * 0.72
        + opponent.player_keeper_sweeping_score * 0.14
        + opponent.player_keeper_diving_score * 0.14
    )
    attack = (team.player_shooting_score * 0.65) + (team.player_chance_creation_score * 0.35)
    edge = clamp((attack - opponent_keeper) / 100, -0.5, 0.5)
    return {
        "label": "Post-shot GK",
        "xg_delta": round(clamp(0.09 * edge, -0.055, 0.055), 4),
        "quality": "Player traits",
        "attacking_shot_quality": round(attack, 1),
        "opponent_keeper_score": round(opponent_keeper, 1),
        "detail": f"Shot quality {attack:.1f} vs opponent GK {opponent_keeper:.1f}.",
    }


def freeze_frame_signal(team: Team, opponent: Team) -> dict[str, Any]:
    profile = team_profile_row(FREEZE_FRAME_SIGNALS_PATH, team.name)
    opponent_profile = team_profile_row(FREEZE_FRAME_SIGNALS_PATH, opponent.name)
    if not profile or not opponent_profile:
        return {"label": "360 freeze-frame", "xg_delta": 0.0, "quality": "Needs event data", "detail": "No 360/freeze-frame proxy rows yet."}

    attack_lanes = (csv_float(profile, "box_density_attack") * 0.42) + (csv_float(profile, "shot_lane_quality") * 0.58)
    defensive_shape = (csv_float(opponent_profile, "defensive_compactness") * 0.55) + (csv_float(opponent_profile, "keeper_positioning") * 0.45)
    edge = clamp((attack_lanes - defensive_shape) / 100, -0.55, 0.55)
    return {
        "label": "360 freeze-frame",
        "xg_delta": round(clamp(0.065 * edge, -0.05, 0.05), 4),
        "quality": "xG proxy",
        "lane_edge": round(edge, 3),
        "detail": f"Shot-lane edge {edge:+.2f} from zone/freeze-frame proxy.",
    }


def referee_signal(team: Team, opponent: Team, context: dict[str, Any]) -> dict[str, Any]:
    referee_name = context.get("referee") or "Average referee"
    rows = load_csv_rows(REFEREE_PROFILES_PATH)
    profile = next((row for row in rows if row.get("referee") == referee_name), None) or next((row for row in rows if row.get("referee") == "Average referee"), {})
    if not profile:
        return {"label": "Referee tendencies", "xg_delta": 0.0, "quality": "Neutral", "detail": "No referee profile rows yet."}

    strictness = clamp((csv_float(profile, "cards_per_match", 4.2) - 4.2) / 2.8, -1, 1)
    penalty_rate = csv_float(profile, "penalties_per_match", 0.28)
    discipline_edge = clamp((team.discipline - opponent.discipline) / 100, -0.35, 0.35)
    box_pressure_edge = clamp((team.player_chance_creation_score + team.set_piece_attack - opponent.player_defensive_activity_score - opponent.set_piece_defense) / 200, -0.45, 0.45)
    delta = (0.028 * strictness * discipline_edge) + (0.035 * (penalty_rate - 0.28) * box_pressure_edge)
    return {
        "label": "Referee tendencies",
        "xg_delta": round(clamp(delta, -0.035, 0.035), 4),
        "quality": profile.get("source") or "Starter prior",
        "referee": profile.get("referee", referee_name),
        "detail": f"{profile.get('referee', referee_name)}: {csv_float(profile, 'cards_per_match', 4.2):.1f} cards/match.",
    }


def live_bayesian_signal(team: Team) -> dict[str, Any]:
    row = team_profile_row(LIVE_TEAM_STATE_PATH, team.name)
    if not row:
        return {"label": "Live Bayesian update", "xg_delta": 0.0, "quality": "No live rows", "detail": "No live team posterior row yet."}

    posterior = csv_float(row, "posterior_strength_delta")
    momentum = csv_float(row, "momentum")
    live_xg_for = csv_float(row, "live_xg_for")
    live_xg_against = csv_float(row, "live_xg_against")
    injury_load = csv_float(row, "injury_load")
    live_xg_edge = (live_xg_for - live_xg_against) * 0.018 if live_xg_for or live_xg_against else 0.0
    delta = (posterior * 0.018) + (momentum * 0.018) + live_xg_edge - (injury_load * 0.09)
    return {
        "label": "Live Bayesian update",
        "xg_delta": round(clamp(delta, -0.075, 0.075), 4),
        "quality": row.get("source") or "Live state",
        "posterior_strength_delta": round(posterior, 3),
        "matches_played": int(csv_float(row, "matches_played")),
        "detail": f"Posterior delta {posterior:+.2f}; tournament momentum {momentum:+.2f}.",
    }


def advanced_matchup_signals(team: Team, opponent: Team, context: dict[str, Any], knockout: bool = False) -> dict[str, Any]:
    match_id = context.get("match_id") or (context.get("fixture") or {}).get("id")
    signals = [
        availability_signal(team, match_id),
        lineup_signal(team, match_id),
        market_signal(team, opponent),
        tactical_signal(team, opponent),
        weather_effect_signal(team, opponent, context),
        set_piece_signal(team, opponent, context),
        goalkeeper_signal(team, opponent),
        freeze_frame_signal(team, opponent),
        referee_signal(team, opponent, context),
        live_bayesian_signal(team),
    ]
    if knockout:
        pressure_delta = clamp((team.big_match_composure - opponent.big_match_composure) / 100 * 0.035, -0.025, 0.025)
        signals.append(
            {
                "label": "Knockout pressure",
                "xg_delta": round(pressure_delta, 4),
                "quality": "Team trait",
                "detail": f"Big-match composure edge {team.big_match_composure - opponent.big_match_composure:+.1f}.",
            }
        )

    total_delta = clamp(sum(float(signal.get("xg_delta", 0.0)) for signal in signals), -0.28, 0.28)
    active_sources = sum(1 for signal in signals if signal.get("quality") not in {"Needs odds", "Needs profile", "Needs event data", "No live rows"})
    quality_score = 38 + active_sources * 5.2
    if any(signal.get("quality") in {"Provider", "Confirmed", "Market"} for signal in signals):
        quality_score += 10
    top_signals = sorted(signals, key=lambda signal: abs(float(signal.get("xg_delta", 0.0))), reverse=True)[:5]
    return {
        "team": team.name,
        "opponent": opponent.name,
        "xg_delta": round(total_delta, 4),
        "quality": {
            "score": round(clamp(quality_score, 0, 100), 1),
            "label": signal_quality_label(quality_score),
            "active_sources": active_sources,
            "source_files": [
                str(AVAILABILITY_PATH),
                str(CONFIRMED_LINEUPS_PATH),
                str(MARKET_SIGNALS_PATH),
                str(TACTICAL_PROFILES_PATH),
                str(SET_PIECE_PROFILES_PATH),
                str(GOALKEEPER_PROFILES_PATH),
                str(REFEREE_PROFILES_PATH),
                str(WEATHER_EFFECTS_PATH),
                str(LIVE_TEAM_STATE_PATH),
                str(FREEZE_FRAME_SIGNALS_PATH),
            ],
        },
        "signals": signals,
        "top_signals": top_signals,
    }


def advanced_signal_pair(team_a: Team, team_b: Team, context: dict[str, Any], knockout: bool = False) -> dict[str, Any]:
    signal_a = advanced_matchup_signals(team_a, team_b, context, knockout)
    signal_b = advanced_matchup_signals(team_b, team_a, context, knockout)
    return {
        "team_a": signal_a,
        "team_b": signal_b,
        "edge_xg": round(signal_a["xg_delta"] - signal_b["xg_delta"], 4),
        "quality": {
            "score": round((signal_a["quality"]["score"] + signal_b["quality"]["score"]) / 2, 1),
            "label": signal_quality_label((signal_a["quality"]["score"] + signal_b["quality"]["score"]) / 2),
        },
    }


def poisson_result_probabilities(lambda_a: float, lambda_b: float, max_goals: int = 9) -> dict[str, float]:
    win_a = 0.0
    draw = 0.0
    win_b = 0.0
    for goals_a in range(max_goals + 1):
        probability_a = (2.718281828 ** -lambda_a) * (lambda_a**goals_a) / factorial(goals_a)
        for goals_b in range(max_goals + 1):
            probability = probability_a * ((2.718281828 ** -lambda_b) * (lambda_b**goals_b) / factorial(goals_b))
            if goals_a > goals_b:
                win_a += probability
            elif goals_b > goals_a:
                win_b += probability
            else:
                draw += probability
    total = win_a + draw + win_b
    return {"team_a_win": win_a / total, "draw": draw / total, "team_b_win": win_b / total}


def factorial(value: int) -> int:
    result = 1
    for number in range(2, value + 1):
        result *= number
    return result


def blended_context_probabilities(team_a: Team, team_b: Team, bundle: Any, context: dict[str, Any], knockout: bool = False) -> dict[str, float]:
    scorelines = context_score_distribution(team_a, team_b, bundle, context, knockout)
    return aggregate_scoreline_probabilities(scorelines)


def aggregate_scoreline_probabilities(scorelines: list[tuple[int, int, float]]) -> dict[str, float]:
    return {
        "team_a_win": sum(probability for goals_a, goals_b, probability in scorelines if goals_a > goals_b),
        "draw": sum(probability for goals_a, goals_b, probability in scorelines if goals_a == goals_b),
        "team_b_win": sum(probability for goals_a, goals_b, probability in scorelines if goals_b > goals_a),
    }


def base_expected_goal_pair(team_a: Team, team_b: Team, bundle: Any, knockout: bool = False) -> tuple[float, float]:
    if bundle:
        return model_expected_goals(team_a, team_b, bundle, knockout)
    return expected_goals(team_a, team_b, knockout), expected_goals(team_b, team_a, knockout)


def forecast_data_quality(team_a: Team, team_b: Team, context: dict[str, Any]) -> dict[str, Any]:
    fixture = context.get("fixture") or {}
    venue_source = fixture.get("venue_source") or "none"
    weather_source = context.get("weather_source") or "manual"
    lineup_confidence = ((team_a.lineup_confidence or 55.0) + (team_b.lineup_confidence or 55.0)) / 2
    advanced_quality = advanced_signal_pair(team_a, team_b, context)["quality"]
    score = 40
    if venue_source == "published-schedule":
        score += 20
    if weather_source in {"open-meteo", "open-meteo-hourly"}:
        score += 18
    elif "failed" in str(weather_source):
        score += 4
    elif weather_source == "venue-climatology":
        score += 8
    score += min(22, lineup_confidence / 5)
    score += min(14, advanced_quality["score"] / 7)
    if score >= 78:
        label = "Strong"
    elif score >= 58:
        label = "Medium"
    else:
        label = "Starter"
    return {
        "label": label,
        "score": round(min(100, score), 1),
        "venue_source": venue_source,
        "weather_source": weather_source,
        "avg_lineup_confidence": round(lineup_confidence, 1),
        "advanced_signal_quality": advanced_quality,
    }


def forecast_stack_payload(
    team_a: Team,
    team_b: Team,
    bundle: Any,
    context: dict[str, Any],
    lambda_a: float,
    lambda_b: float,
) -> dict[str, Any]:
    base_a, base_b = base_expected_goal_pair(team_a, team_b, bundle)
    xg_signals = load_xg_team_signals()
    team_a_xg = xg_signals.get(team_a.name)
    team_b_xg = xg_signals.get(team_b.name)
    xg_delta_a = 0.08 * xg_forecast_edge(team_a.name, team_b.name)
    xg_delta_b = 0.08 * xg_forecast_edge(team_b.name, team_a.name)
    context_delta_a = lambda_a - base_a
    context_delta_b = lambda_b - base_b
    player_attack_a = (team_a.player_shooting_score + team_a.player_chance_creation_score + team_a.player_progression_score) / 3
    player_attack_b = (team_b.player_shooting_score + team_b.player_chance_creation_score + team_b.player_progression_score) / 3
    player_without_ball_a = (team_a.player_defensive_activity_score + team_a.player_goalkeeping_score) / 2
    player_without_ball_b = (team_b.player_defensive_activity_score + team_b.player_goalkeeping_score) / 2
    squad_gap = (team_a.projected_xi_score + team_a.squad_availability + team_a.lineup_continuity) - (
        team_b.projected_xi_score + team_b.squad_availability + team_b.lineup_continuity
    )
    penalty_gap = team_a.penalty_strength - team_b.penalty_strength
    advanced = advanced_signal_pair(team_a, team_b, context)
    advanced_a = advanced["team_a"]
    advanced_b = advanced["team_b"]

    def signal_for(payload: dict[str, Any], label: str) -> dict[str, Any]:
        return next((signal for signal in payload.get("signals", []) if signal.get("label") == label), {})

    availability_a = signal_for(advanced_a, "Availability")
    availability_b = signal_for(advanced_b, "Availability")
    lineup_a = signal_for(advanced_a, "Confirmed XI")
    lineup_b = signal_for(advanced_b, "Confirmed XI")
    market_a = signal_for(advanced_a, "Market probability")
    market_b = signal_for(advanced_b, "Market probability")
    live_a = signal_for(advanced_a, "Live Bayesian update")
    live_b = signal_for(advanced_b, "Live Bayesian update")
    tactical_labels = {"Tactical matchup", "Set pieces", "Post-shot GK", "360 freeze-frame", "Referee tendencies", "Weather backtest"}
    tactical_delta_a = sum(float(signal.get("xg_delta", 0.0)) for signal in advanced_a.get("signals", []) if signal.get("label") in tactical_labels)
    tactical_delta_b = sum(float(signal.get("xg_delta", 0.0)) for signal in advanced_b.get("signals", []) if signal.get("label") in tactical_labels)
    availability_delta_a = float(availability_a.get("xg_delta", 0.0)) + float(lineup_a.get("xg_delta", 0.0))
    availability_delta_b = float(availability_b.get("xg_delta", 0.0)) + float(lineup_b.get("xg_delta", 0.0))
    market_live_delta_a = float(market_a.get("xg_delta", 0.0)) + float(live_a.get("xg_delta", 0.0))
    market_live_delta_b = float(market_b.get("xg_delta", 0.0)) + float(live_b.get("xg_delta", 0.0))
    context_is_active = (
        context.get("weather", "normal") != "normal"
        or float(context.get("travel", 20)) != 20
        or float(context.get("fatigue", 20)) != 20
        or float(context.get("home_advantage", 1.0)) != 1.0
        or context.get("team_travel")
        or context.get("team_fatigue")
        or context.get("fan_edges")
        or context.get("venue")
    )
    context_summary = compact_fixture_context(context, team_a, team_b)
    quality = forecast_data_quality(team_a, team_b, context)
    return {
        "summary": "The forecast is integrated: historical ensemble first, then current squad/player, xG-zone, weather/travel, and shootout signals adjust the score distribution.",
        "context": context_summary,
        "data_quality": quality,
        "expected_goals": {
            "base": {"team_a": round(base_a, 2), "team_b": round(base_b, 2)},
            "integrated": {"team_a": round(lambda_a, 2), "team_b": round(lambda_b, 2)},
            "context_delta": {"team_a": round(context_delta_a, 2), "team_b": round(context_delta_b, 2)},
        },
        "modules": [
            {
                "label": "Historical ensemble",
                "status": "Active",
                "impact": 100,
                "quality": "Trained" if bundle else "Baseline",
                "detail": "RF + Dixon-Coles + Elo create the base result probabilities and exact-score shape." if bundle else "Baseline strength model is active because the ensemble toggle is off.",
            },
            {
                "label": "Current squad and player traits",
                "status": "Active",
                "impact": round(min(100.0, 35 + abs(squad_gap) * 1.8), 1),
                "quality": f"Lineup {quality['avg_lineup_confidence']}%",
                "detail": f"{team_a.name} player attack {player_attack_a:.1f}, off-ball/GK {player_without_ball_a:.1f}; {team_b.name} player attack {player_attack_b:.1f}, off-ball/GK {player_without_ball_b:.1f}.",
            },
            {
                "label": "Availability and confirmed XI",
                "status": "Active",
                "impact": round(min(100.0, 25 + abs(availability_delta_a - availability_delta_b) * 520), 1),
                "quality": f"{advanced['quality']['label']} signals",
                "detail": f"XI/availability xG: {team_a.name} {availability_delta_a:+.2f}, {team_b.name} {availability_delta_b:+.2f}.",
            },
            {
                "label": "Market and live Bayesian",
                "status": "Active" if market_a.get("market_probability") or market_b.get("market_probability") or live_a.get("matches_played") or live_b.get("matches_played") else "Waiting for live data",
                "impact": round(min(100.0, 20 + abs(market_live_delta_a - market_live_delta_b) * 650), 1),
                "quality": f"{market_a.get('quality', 'Needs odds')} / {live_a.get('quality', 'Live state')}",
                "detail": f"Market/live xG: {team_a.name} {market_live_delta_a:+.2f}, {team_b.name} {market_live_delta_b:+.2f}.",
            },
            {
                "label": "Tactical game model",
                "status": "Active",
                "impact": round(min(100.0, 25 + abs(tactical_delta_a - tactical_delta_b) * 520), 1),
                "quality": "Tactics, set pieces, GK, referee",
                "detail": f"Tactical/context xG: {team_a.name} {tactical_delta_a:+.2f}, {team_b.name} {tactical_delta_b:+.2f}.",
            },
            {
                "label": "xG danger zones",
                "status": "Active" if team_a_xg and team_b_xg else "Context only",
                "impact": round(min(100.0, 25 + abs(xg_delta_a - xg_delta_b) * 900), 1) if team_a_xg and team_b_xg else 0,
                "quality": "Synced" if team_a_xg and team_b_xg else "Needs data",
                "detail": (
                    f"xG-zone adjustment: {team_a.name} {xg_delta_a:+.2f} xG, {team_b.name} {xg_delta_b:+.2f} xG."
                    if team_a_xg and team_b_xg
                    else "Train or sync xG team zones to activate the shot-quality adjustment."
                ),
            },
            {
                "label": "Weather, travel, venue",
                "status": "Active" if context_is_active else "Neutral",
                "impact": round(min(100.0, 25 + abs(context_delta_a - xg_delta_a) * 180 + abs(context_delta_b - xg_delta_b) * 180), 1),
                "quality": f"{quality['label']} context",
                "detail": f"Scenario moved expected goals by {context_delta_a:+.2f} / {context_delta_b:+.2f}. Weather {context.get('weather', 'normal')}; fixture source {quality['venue_source']}.",
            },
            {
                "label": "Shootout layer",
                "status": "Knockout fallback",
                "impact": round(min(100.0, 25 + abs(penalty_gap) * 2.0), 1),
                "quality": "Team aggregate",
                "detail": f"Used after knockout draws. Aggregate penalty edge: {team_a.name} {team_a.penalty_strength:.1f}, {team_b.name} {team_b.penalty_strength:.1f}.",
            },
            {
                "label": "RAG analyst",
                "status": "Reasoning layer",
                "impact": 0,
                "quality": "Explainability",
                "detail": "RAG explains the forecast with local evidence and tool traces; it does not overwrite model probabilities.",
            },
        ],
    }


def normalized_scorelines(scorelines: list[tuple[int, int, float]]) -> list[tuple[int, int, float]]:
    total = sum(probability for _, _, probability in scorelines)
    return [(goals_a, goals_b, probability / total) for goals_a, goals_b, probability in scorelines]


def context_score_distribution(
    team_a: Team,
    team_b: Team,
    bundle: Any,
    context: dict[str, Any],
    knockout: bool = False,
    max_goals: int = 9,
) -> list[tuple[int, int, float]]:
    lambda_a = context_expected_goals(team_a, team_b, bundle, context, knockout)
    lambda_b = context_expected_goals(team_b, team_a, bundle, context, knockout)
    scenario = normalized_scorelines(scorelines_from_lambdas(lambda_a, lambda_b, max_goals))
    if not bundle:
        return scenario

    model = scoreline_distribution(team_a, team_b, max_goals=max_goals, knockout=knockout, bundle=bundle)
    scenario_by_score = {(goals_a, goals_b): probability for goals_a, goals_b, probability in scenario}
    blended = [
        (goals_a, goals_b, (0.68 * probability) + (0.32 * scenario_by_score.get((goals_a, goals_b), 0.0)))
        for goals_a, goals_b, probability in model
    ]
    return normalized_scorelines(blended)


def sample_outcome(probabilities: dict[str, float]) -> str:
    value = random.random()
    if value < probabilities["team_a_win"]:
        return "team_a_win"
    if value < probabilities["team_a_win"] + probabilities["draw"]:
        return "draw"
    return "team_b_win"


def align_score_to_outcome(goals_a: int, goals_b: int, outcome: str) -> tuple[int, int]:
    if outcome == "team_a_win" and goals_a <= goals_b:
        return goals_b + 1, goals_b
    if outcome == "team_b_win" and goals_b <= goals_a:
        return goals_a, goals_a + 1
    if outcome == "draw" and goals_a != goals_b:
        draw_goals = round((goals_a + goals_b) / 2)
        return draw_goals, draw_goals
    return goals_a, goals_b


def play_context_match(team_a: Team, team_b: Team, bundle: Any, context: dict[str, Any], knockout: bool = False) -> tuple[int, int]:
    value = random.random()
    cumulative = 0.0
    scorelines = context_score_distribution(team_a, team_b, bundle, context, knockout)
    for goals_a, goals_b, probability in scorelines:
        cumulative += probability
        if value <= cumulative:
            return goals_a, goals_b
    return scorelines[-1][0], scorelines[-1][1]


def play_group_detail(
    group: str,
    teams: list[Team],
    eliminated: set[str],
    completed: dict[frozenset[str], dict[str, Any]],
    bundle: Any,
    context: dict[str, Any],
    route_state: dict[str, dict[str, Any]],
) -> tuple[list[Standing], list[dict[str, Any]]]:
    table = {team.name: Standing(team) for team in teams}
    matches = []
    team_by_name = {team.name: team for team in teams}
    scheduled = group_fixtures(group, teams)
    if scheduled:
        fixture_pairs = [
            (fixture, team_by_name[fixture["team_a"]], team_by_name[fixture["team_b"]])
            for fixture in scheduled
        ]
    else:
        fixture_pairs = [
            (None, team_a, team_b)
            for idx, team_a in enumerate(teams)
            for team_b in teams[idx + 1 :]
        ]

    for fixture, team_a, team_b in fixture_pairs:
        fixture_context = automatic_fixture_context(context, fixture, team_a, team_b, route_state) if fixture else context
        goals_a, goals_b, locked = resolve_match_score(team_a, team_b, completed, bundle, fixture_context)
        row_a = table[team_a.name]
        row_b = table[team_b.name]
        row_a.goals_for += goals_a
        row_a.goals_against += goals_b
        row_b.goals_for += goals_b
        row_b.goals_against += goals_a
        if goals_a > goals_b:
            row_a.points += 3
            row_a.wins += 1
        elif goals_b > goals_a:
            row_b.points += 3
            row_b.wins += 1
        else:
            row_a.points += 1
            row_b.points += 1
        matches.append(match_payload(team_a, team_b, goals_a, goals_b, locked, fixture, fixture_context))
        update_route_state(route_state, fixture, team_a, team_b)

    ranked = sorted(
        table.values(),
        key=lambda standing: (
            standing.team.name not in eliminated,
            *standing.sort_key(),
        ),
        reverse=True,
    )
    return ranked, matches


def match_payload(
    team_a: Team,
    team_b: Team,
    goals_a: int,
    goals_b: int,
    locked: bool = False,
    fixture: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if goals_a > goals_b:
        winner = team_a.name
    elif goals_b > goals_a:
        winner = team_b.name
    else:
        winner = None
    payload = {
        "team_a": team_payload(team_a),
        "team_b": team_payload(team_b),
        "score_a": goals_a,
        "score_b": goals_b,
        "winner": winner,
        "locked": locked,
    }
    if fixture:
        payload["id"] = fixture.get("match_id")
        payload["fixture"] = fixture_label(fixture)
        payload["venue"] = fixture.get("venue")
        payload["kickoff_local"] = fixture.get("kickoff_local")
    if context:
        payload["venue"] = context.get("venue") or payload.get("venue")
        payload["weather"] = context.get("weather")
        payload["weather_source"] = context.get("weather_source")
        payload["context_summary"] = compact_fixture_context(context, team_a, team_b)
    return payload


def standing_payload(row: Standing) -> dict[str, Any]:
    return {
        "team": team_payload(row.team),
        "points": row.points,
        "goals_for": row.goals_for,
        "goals_against": row.goals_against,
        "goal_difference": row.goal_difference,
        "wins": row.wins,
    }


def play_knockout_match(
    match_id: int,
    team_a: Team,
    team_b: Team,
    bundle: Any,
    context: dict[str, Any],
    fixture: dict[str, Any] | None = None,
    venue: str | None = None,
    route_state: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    route_state = route_state if route_state is not None else {}
    fixture = fixture or fixture_by_id(match_id)
    if fixture and venue and not fixture.get("venue"):
        fixture = {**fixture, "venue": venue}
    fixture_context = automatic_fixture_context(context, fixture, team_a, team_b, route_state) if fixture else context_for_fixture(context, venue)
    goals_a, goals_b = play_context_match(team_a, team_b, bundle, fixture_context, knockout=True)
    if goals_a == goals_b:
        penalty_edge = ((team_a.penalty_strength + team_a.big_match_composure) - (team_b.penalty_strength + team_b.big_match_composure)) / 100
        probability_a = 1 / (1 + pow(2.718281828, -((team_a.strength - team_b.strength) * 1.8 + penalty_edge)))
        winner = team_a if random.random() < probability_a else team_b
        penalty_winner = winner.name
    else:
        winner = team_a if goals_a > goals_b else team_b
        penalty_winner = None
    loser = team_b if winner == team_a else team_a
    match = match_payload(team_a, team_b, goals_a, goals_b, False, fixture, fixture_context)
    match["id"] = match_id
    match["winner"] = winner.name
    match["winner_team"] = team_payload(winner)
    match["loser_team"] = team_payload(loser)
    match["penalty_winner"] = penalty_winner
    match["venue"] = fixture_context.get("venue") or venue
    match["weather"] = fixture_context.get("weather")
    match["weather_source"] = fixture_context.get("weather_source")
    update_route_state(route_state, fixture, team_a, team_b)
    return match


def third_place_candidates(group_tables: dict[str, list[Standing]], eliminated: set[str]) -> list[tuple[str, Standing]]:
    candidates = []
    for group, table in group_tables.items():
        if len(table) > 2 and table[2].team.name not in eliminated:
            candidates.append((group, table[2]))
    return sorted(candidates, key=lambda item: item[1].sort_key(), reverse=True)[:8]


def choose_third_for_slot(
    allowed_groups: tuple[str, ...],
    available: dict[str, Standing],
    remaining_slots: list[tuple[str, ...]],
) -> tuple[str, Standing]:
    eligible = [(group, row) for group, row in available.items() if group in allowed_groups]
    if not eligible:
        group, row = next(iter(available.items()))
        return group, row

    def future_fit(group: str) -> int:
        return sum(1 for slot in remaining_slots if group in slot)

    return sorted(eligible, key=lambda item: (future_fit(item[0]), item[1].sort_key()))[0]


def slot_team(
    slot: tuple[str, Any],
    group_tables: dict[str, list[Standing]],
    third_available: dict[str, Standing],
    remaining_third_slots: list[tuple[str, ...]],
) -> Team:
    kind, value = slot
    if kind == "winner":
        return group_tables[value][0].team
    if kind == "second":
        return group_tables[value][1].team
    group, row = choose_third_for_slot(value, third_available, remaining_third_slots)
    third_available.pop(group)
    return row.team


def play_official_knockout_detail(
    group_tables: dict[str, list[Standing]],
    bundle: Any,
    context: dict[str, Any],
    eliminated: set[str],
    route_state: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    third_available = dict(third_place_candidates(group_tables, eliminated))
    third_slots = [slot["b"][1] for slot in R32_SLOTS if slot["b"][0] == "third"]
    matches_by_id: dict[int, dict[str, Any]] = {}
    winners_by_id: dict[int, Team] = {}
    losers_by_id: dict[int, Team] = {}
    r32_matches = []

    for slot in R32_SLOTS:
        if slot["a"][0] == "third":
            third_slots = third_slots[1:]
        if slot["b"][0] == "third":
            remaining_after_this = third_slots[1:]
        else:
            remaining_after_this = third_slots
        team_a = slot_team(slot["a"], group_tables, third_available, remaining_after_this)
        team_b = slot_team(slot["b"], group_tables, third_available, remaining_after_this)
        if slot["b"][0] == "third":
            third_slots = third_slots[1:]
        match = play_knockout_match(slot["id"], team_a, team_b, bundle, context, fixture_by_id(slot["id"]), slot["venue"], route_state)
        matches_by_id[slot["id"]] = match
        winners_by_id[slot["id"]] = team_a if match["winner"] == team_a.name else team_b
        losers_by_id[slot["id"]] = team_b if match["winner"] == team_a.name else team_a
        r32_matches.append(match)

    rounds = [{"name": "Round of 32", "matches": r32_matches}]
    for round_name, match_specs in KNOCKOUT_PATH:
        round_matches = []
        for match_id, source_a, source_b in match_specs:
            team_a = winners_by_id[source_a]
            team_b = winners_by_id[source_b]
            match = play_knockout_match(match_id, team_a, team_b, bundle, context, fixture_by_id(match_id), route_state=route_state)
            matches_by_id[match_id] = match
            winners_by_id[match_id] = team_a if match["winner"] == team_a.name else team_b
            losers_by_id[match_id] = team_b if match["winner"] == team_a.name else team_a
            round_matches.append(match)
        rounds.append({"name": round_name, "matches": round_matches})

    bronze_id, bronze_a_source, bronze_b_source = BRONZE_MATCH
    bronze = play_knockout_match(
        bronze_id,
        losers_by_id[bronze_a_source],
        losers_by_id[bronze_b_source],
        bundle,
        context,
        fixture_by_id(bronze_id),
        route_state=route_state,
    )
    matches_by_id[bronze_id] = bronze
    rounds.append({"name": "Bronze Final", "matches": [bronze]})

    final_id, final_a_source, final_b_source = FINAL_MATCH
    final = play_knockout_match(
        final_id,
        winners_by_id[final_a_source],
        winners_by_id[final_b_source],
        bundle,
        context,
        fixture_by_id(final_id),
        route_state=route_state,
    )
    matches_by_id[final_id] = final
    rounds.append({"name": "Final", "matches": [final]})

    return {"rounds": rounds, "champion": matches_by_id[104]["winner_team"], "format": "FIFA match-number bracket"}


def simulate_detail_core(
    teams: dict[str, Team],
    groups: dict[str, list[Team]],
    state: dict[str, Any],
    bundle: Any,
    seed: int,
    context: dict[str, Any],
) -> dict[str, Any]:
    random.seed(seed)
    eliminated = set(state.get("eliminated_teams", []))
    completed = completed_match_lookup(state)
    route_state: dict[str, dict[str, Any]] = {}

    group_tables = {}
    group_matches = {}
    for group, group_teams in groups.items():
        table, matches = play_group_detail(group, group_teams, eliminated, completed, bundle, context, route_state)
        group_tables[group] = table
        group_matches[group] = matches

    if sum(1 for table in group_tables.values() for row in table[:3] if row.team.name not in eliminated) < 32:
        raise HTTPException(status_code=409, detail="Not enough active teams remain to simulate.")
    knockout = play_official_knockout_detail(group_tables, bundle, context, eliminated, route_state)
    return {
        "model": "RF + Dixon-Coles + Elo" if bundle else "Poisson baseline",
        "context": context,
        "fixture_source": str(FIXTURES_PATH),
        "live_state": state,
        "groups": {
            group: {
                "standings": [standing_payload(row) for row in table],
                "matches": group_matches[group],
            }
            for group, table in group_tables.items()
        },
        "bracket": knockout,
    }


def simulate_detail(seed: int, use_model: bool) -> dict[str, Any]:
    teams = load_teams()
    groups = load_groups(teams)
    state = load_live_state()
    bundle = load_cached_model() if use_model else None
    return simulate_detail_core(teams, groups, state, bundle, seed, {"weather": "normal", "travel": 20, "fatigue": 20, "home_advantage": 1.0})


def binomial_ci_pct(count: float, sims: int, z: float = 1.96) -> tuple[float, float]:
    if sims <= 0:
        return 0.0, 0.0
    probability = count / sims
    margin = z * math.sqrt(max(0.0, probability * (1 - probability) / sims))
    return round(max(0.0, 100 * (probability - margin)), 1), round(min(100.0, 100 * (probability + margin)), 1)


def run_many(sims: int, seed: int, use_model: bool, context: dict[str, Any]) -> dict[str, Any]:
    random.seed(seed)
    teams = load_teams()
    groups = load_groups(teams)
    state = load_live_state()
    bundle = load_cached_model() if use_model else None
    player_candidates = load_player_candidates()
    scorer_totals: Counter[str] = Counter()
    golden_boots: Counter[str] = Counter()
    scorer_meta: dict[str, dict[str, Any]] = {}
    counters = {
        "round_of_32": Counter(),
        "round_of_16": Counter(),
        "quarterfinals": Counter(),
        "semifinals": Counter(),
        "finalists": Counter(),
        "champion": Counter(),
    }

    for sim_idx in range(sims):
        detail = simulate_detail_core(teams, groups, state, bundle, seed + sim_idx, context)
        simulation_scorers: Counter[str] = Counter()
        collect_scorers(detail, player_candidates, scorer_totals, simulation_scorers, scorer_meta)
        if simulation_scorers:
            top_goals = max(simulation_scorers.values())
            leaders = [key for key, goals in simulation_scorers.items() if goals == top_goals]
            for key in leaders:
                golden_boots[key] += 1 / len(leaders)
        for match in detail["bracket"]["rounds"][0]["matches"]:
            counters["round_of_32"][match["team_a"]["name"]] += 1
            counters["round_of_32"][match["team_b"]["name"]] += 1
        stage_key_by_name = {
            "Round of 16": "round_of_16",
            "Quarterfinals": "quarterfinals",
            "Semifinals": "semifinals",
            "Final": "finalists",
        }
        for round_data in detail["bracket"]["rounds"][1:]:
            key = stage_key_by_name.get(round_data["name"])
            if not key:
                continue
            for match in round_data["matches"]:
                counters[key][match["team_a"]["name"]] += 1
                counters[key][match["team_b"]["name"]] += 1
        counters["champion"][detail["bracket"]["champion"]["name"]] += 1

    table = []
    for team in teams.values():
        win_ci_low, win_ci_high = binomial_ci_pct(counters["champion"][team.name], sims)
        final_ci_low, final_ci_high = binomial_ci_pct(counters["finalists"][team.name], sims)
        table.append(
            {
                **team_payload(team),
                "r32_pct": round(100 * counters["round_of_32"][team.name] / sims, 1),
                "r16_pct": round(100 * counters["round_of_16"][team.name] / sims, 1),
                "qf_pct": round(100 * counters["quarterfinals"][team.name] / sims, 1),
                "sf_pct": round(100 * counters["semifinals"][team.name] / sims, 1),
                "final_pct": round(100 * counters["finalists"][team.name] / sims, 1),
                "final_ci_low": final_ci_low,
                "final_ci_high": final_ci_high,
                "win_pct": round(100 * counters["champion"][team.name] / sims, 1),
                "win_ci_low": win_ci_low,
                "win_ci_high": win_ci_high,
            }
        )
    return {
        "model": "RF + Dixon-Coles + Elo" if bundle else "Poisson baseline",
        "sims": sims,
        "odds": sorted(table, key=lambda row: row["win_pct"], reverse=True),
        "top_scorers": top_scorer_payload(scorer_totals, golden_boots, scorer_meta, sims),
    }


def collect_scorers(
    detail: dict[str, Any],
    candidates: dict[str, list[dict[str, Any]]],
    totals: Counter[str],
    simulation_totals: Counter[str],
    meta: dict[str, dict[str, Any]],
) -> None:
    matches = []
    for group in detail["groups"].values():
        matches.extend(group["matches"])
    for round_data in detail["bracket"]["rounds"]:
        matches.extend(round_data["matches"])

    for match in matches:
        for side in ("team_a", "team_b"):
            team = match[side]["name"]
            score_key = "score_a" if side == "team_a" else "score_b"
            for _ in range(match[score_key]):
                scorer = pick_scorer(team, candidates)
                key = f"{scorer['team']}::{scorer['player']}"
                totals[key] += 1
                simulation_totals[key] += 1
                meta[key] = scorer


def top_scorer_payload(
    totals: Counter[str],
    golden_boots: Counter[str],
    meta: dict[str, dict[str, Any]],
    sims: int,
) -> list[dict[str, Any]]:
    rows = []
    for key, goals in totals.most_common(18):
        player = meta[key]
        rows.append(
            {
                "player": player["player"],
                "team": player["team"],
                "flag": player["flag"],
                "flag_code": player.get("flag_code"),
                "flag_image": player.get("flag_image"),
                "position": player["position"],
                "avg_goals": round(goals / sims, 2),
                "golden_boot_pct": round(100 * golden_boots[key] / sims, 1),
            }
        )
    return rows


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "ai.html")


@app.get("/ai")
def ai_matchroom() -> FileResponse:
    return FileResponse(STATIC_DIR / "ai.html")


@app.get("/arena")
def prediction_arena_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "arena.html")


@app.get("/dashboard")
def research_dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/model-lab")
def model_lab() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/teams")
def api_teams() -> dict[str, Any]:
    teams = load_teams()
    state = load_live_state()
    eliminated = set(state.get("eliminated_teams", []))
    return {
        "teams": [
            {**team_payload(team), "status": "eliminated" if team.name in eliminated else "active"}
            for team in sorted(teams.values(), key=lambda team: team.rank)
        ]
    }


@app.get("/api/groups")
def api_groups() -> dict[str, Any]:
    teams = load_teams()
    groups = load_groups(teams)
    return {
        "groups": {
            group: [team_payload(team) for team in group_teams]
            for group, group_teams in groups.items()
        }
    }


@app.get("/api/venues")
def api_venues() -> dict[str, Any]:
    venues = sorted(load_venues().values(), key=lambda row: row["venue"])
    return {
        "venues": venues,
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [venue["longitude"], venue["latitude"]],
                    },
                    "properties": venue,
                }
                for venue in venues
            ],
        },
    }


@app.get("/api/fixtures")
def api_fixtures() -> dict[str, Any]:
    fixtures = load_fixtures()
    published = sum(1 for fixture in fixtures if fixture.get("venue_source") == "published-schedule")
    return {
        "fixtures": fixtures,
        "matches": len(fixtures),
        "published_schedule_rows": published,
        "placeholder_rows": len(fixtures) - published,
        "source": str(FIXTURES_PATH),
        "note": "Fixture venues and local kickoffs are applied per match; live results can still override predicted outcomes during the tournament.",
    }


@app.get("/api/venue-weather")
def api_venue_weather(venue: str) -> dict[str, Any]:
    return venue_weather_payload(venue)


@app.get("/api/advanced-signals")
def api_advanced_signals(team_a: str, team_b: str, match_id: int | None = None) -> dict[str, Any]:
    teams = load_teams()
    if team_a not in teams or team_b not in teams:
        raise HTTPException(status_code=404, detail="Unknown team")
    first = teams[team_a]
    second = teams[team_b]
    fixture = fixture_by_id(match_id) if match_id else fixture_for_team_pair(team_a, team_b)
    context = {"weather": "auto", "travel": 20, "fatigue": 20, "home_advantage": 1.0}
    context = automatic_fixture_context(context, fixture, first, second, {}) if fixture else context
    return {
        "team_a": team_payload(first),
        "team_b": team_payload(second),
        "context": compact_fixture_context(context, first, second),
        "advanced_signals": advanced_signal_pair(first, second, context),
        "source_files": {
            "availability": str(AVAILABILITY_PATH),
            "confirmed_lineups": str(CONFIRMED_LINEUPS_PATH),
            "market_signals": str(MARKET_SIGNALS_PATH),
            "tactical_profiles": str(TACTICAL_PROFILES_PATH),
            "set_piece_profiles": str(SET_PIECE_PROFILES_PATH),
            "goalkeeper_profiles": str(GOALKEEPER_PROFILES_PATH),
            "referees": str(REFEREE_PROFILES_PATH),
            "weather_effects": str(WEATHER_EFFECTS_PATH),
            "live_team_state": str(LIVE_TEAM_STATE_PATH),
            "freeze_frame": str(FREEZE_FRAME_SIGNALS_PATH),
        },
    }


def compact_forecast_for_agent(forecast: dict[str, Any] | None) -> dict[str, Any] | None:
    if not forecast:
        return None
    return {
        "team_a": forecast["team_a"]["name"],
        "team_b": forecast["team_b"]["name"],
        "expected_score": forecast["expected_score"],
        "probabilities": forecast["score_aggregate_probabilities"],
        "confidence": forecast["confidence"],
        "score_insights": forecast["score_insights"],
        "model_drivers": (forecast.get("shap_drivers", {}).get("drivers") or forecast.get("model_drivers", []))[:5],
        "scenario_drivers": forecast.get("scenario_drivers", []),
        "advanced_signals": forecast.get("advanced_signals", {}),
        "model_metadata": forecast.get("model_metadata", {}),
    }


def intelligence_followups(entities: dict[str, list[str]]) -> list[str]:
    teams = entities.get("teams", [])
    venues = entities.get("venues", [])
    if len(teams) >= 2:
        return [
            f"What could make {teams[1]} upset {teams[0]}?",
            f"Show the strongest model drivers for {teams[0]} vs {teams[1]}",
            f"How would heat or altitude change {teams[0]} vs {teams[1]}?",
        ]
    if teams:
        return [
            f"Who are the likely scorers for {teams[0]}?",
            f"What are {teams[0]}'s strongest and weakest model features?",
            f"Which group opponent is most dangerous for {teams[0]}?",
        ]
    if venues:
        return [
            f"Which teams are best suited to {venues[0]}?",
            f"How does weather at {venues[0]} affect expected goals?",
            "Compare all host venues by altitude",
        ]
    return [
        "Why does the model favor France over Brazil?",
        "Which teams are underrated by the model?",
        "How does live state change the tournament forecast?",
    ]


@app.get("/api/intelligence/status")
def api_intelligence_status() -> dict[str, Any]:
    return get_intelligence_index(ROOT).status()


@app.post("/api/intelligence")
def api_intelligence(request: IntelligenceRequest) -> dict[str, Any]:
    index = get_intelligence_index(ROOT)
    index.ensure_ready()
    entities = index.identify_entities(request.question)
    routed_tools = index.route(request.question, entities)
    trace = [
        {
            "step": "route",
            "status": "complete",
            "detail": f"Selected {', '.join(routed_tools)}",
        }
    ]

    preferred_tags = [*entities["teams"], *entities["venues"]]
    evidence = index.retrieve(request.question, request.top_k, preferred_tags)
    trace.append(
        {
            "step": "retrieve_knowledge",
            "status": "complete",
            "detail": f"Retrieved {len(evidence)} evidence chunks from the local project index",
        }
    )

    snapshots = []
    if "team_profile" in routed_tools:
        snapshots = [index.team_snapshot(team) for team in entities["teams"][:2]]
        trace.append(
            {
                "step": "team_profile",
                "status": "complete",
                "detail": f"Loaded profiles for {', '.join(entities['teams'][:2])}",
            }
        )

    head_to_head = None
    forecast = None
    if len(entities["teams"]) >= 2:
        team_a, team_b = entities["teams"][:2]
        if "head_to_head" in routed_tools:
            head_to_head = index.head_to_head(team_a, team_b)
            trace.append(
                {
                    "step": "head_to_head",
                    "status": "complete",
                    "detail": f"Found {head_to_head['matches']} historical meetings",
                }
            )
        if "match_forecast" in routed_tools:
            forecast = api_match(
                MatchRequest(
                    team_a=team_a,
                    team_b=team_b,
                    use_model=request.use_model,
                    top_scores=5,
                    weather=request.weather,
                    travel=request.travel,
                    fatigue=request.fatigue,
                    home_advantage=request.home_advantage,
                    venue=request.venue,
                )
            )
            trace.append(
                {
                    "step": "match_forecast",
                    "status": "complete",
                    "detail": f"Ran the current prediction model for {team_a} vs {team_b}",
                }
            )

    live_state = load_live_state() if "live_state" in routed_tools else None
    if live_state is not None:
        trace.append(
            {
                "step": "live_state",
                "status": "complete",
                "detail": f"Loaded {len(live_state.get('completed_matches', []))} completed matches",
            }
        )

    shortlist = None
    if "team_shortlist" in routed_tools:
        shortlist = index.team_shortlist(request.question)
        trace.append(
            {
                "step": "team_shortlist",
                "status": "complete",
                "detail": f"Ranked {len(shortlist['teams'])} teams for the {shortlist['mode']} screen",
            }
        )

    venue_weather = None
    venue_name = entities["venues"][0] if entities["venues"] else request.venue
    if "venue_weather" in routed_tools and venue_name:
        venue_weather = venue_weather_payload(venue_name)
        trace.append(
            {
                "step": "venue_weather",
                "status": "complete",
                "detail": f"Loaded weather context for {venue_name}",
            }
        )

    specialized_context: dict[str, Any] = {}
    if entities["teams"] and "player_stats" in routed_tools:
        specialized_context["player_stats"] = [get_role_depth(team) for team in entities["teams"][:2]]
        trace.append(
            {
                "step": "player_stats",
                "status": "complete",
                "detail": f"Loaded tactical role depth for {', '.join(entities['teams'][:2])}",
            }
        )
    if entities["teams"] and "injury_news" in routed_tools:
        specialized_context["injury_news"] = [get_injury_status(team) for team in entities["teams"][:2]]
        trace.append(
            {
                "step": "injury_news",
                "status": "complete",
                "detail": f"Loaded current availability signals for {', '.join(entities['teams'][:2])}",
            }
        )
    if entities["teams"] and "manager_evidence" in routed_tools:
        specialized_context["manager_evidence"] = [
            get_team_manager_overview(team) for team in entities["teams"][:2]
        ]
        trace.append(
            {
                "step": "manager_evidence",
                "status": "complete",
                "detail": f"Loaded manager plans for {', '.join(entities['teams'][:2])}",
            }
        )
    if entities["teams"] and "lineup_delta" in routed_tools:
        specialized_context["lineup_delta"] = [get_lineup_delta(team) for team in entities["teams"][:2]]
        trace.append(
            {
                "step": "lineup_delta",
                "status": "complete",
                "detail": f"Loaded confirmed-vs-projected lineup deltas for {', '.join(entities['teams'][:2])}",
            }
        )
    if "postmatch_evaluation" in routed_tools:
        specialized_context["postmatch_evaluation"] = get_model_evaluation()
        trace.append(
            {
                "step": "postmatch_evaluation",
                "status": "complete",
                "detail": "Loaded transparent model evaluation history",
            }
        )

    local = local_answer(
        request.question,
        snapshots,
        head_to_head,
        forecast,
        live_state,
        venue_weather,
        shortlist,
        evidence,
    )
    agent_context = {
        "forecast": compact_forecast_for_agent(forecast),
        "team_profiles": snapshots,
        "head_to_head": head_to_head,
        "live_state": live_state,
        "venue_weather": venue_weather,
        "team_shortlist": shortlist,
        "specialized_context": specialized_context,
        "evidence": evidence,
    }
    llm_answer = optional_llm_answer(request.question, agent_context) if request.use_llm else None
    trace.append(
        {
            "step": "synthesize",
            "status": "complete",
            "detail": "Used configured LLM" if llm_answer else "Used deterministic local synthesis",
        }
    )
    return {
        "answer": llm_answer or local,
        "mode": "llm-assisted-agentic-rag" if llm_answer else "local-agentic-rag",
        "entities": entities,
        "routed_tools": routed_tools,
        "trace": trace,
        "evidence": evidence,
        "forecast": compact_forecast_for_agent(forecast),
        "head_to_head": head_to_head,
        "team_shortlist": shortlist,
        "venue_weather": venue_weather,
        "specialized_context": specialized_context,
        "suggested_followups": intelligence_followups(entities),
        "disclaimer": "Forecasts are probabilistic model outputs, not facts or guaranteed outcomes.",
    }


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    model_exists = MODEL_PATH.exists()
    bundle = load_cached_model() if model_exists else None
    return {
        "model_exists": model_exists,
        "model_path": str(MODEL_PATH),
        "model": model_metadata_payload(bundle),
        "live_state": load_live_state(),
        "intelligence": get_intelligence_index(ROOT).status(),
        "fixtures": {
            "path": str(FIXTURES_PATH),
            "matches": len(load_fixtures()),
        },
    }


@app.get("/api/model-report")
def api_model_report() -> dict[str, Any]:
    bundle = load_cached_model()
    if not bundle:
        return {"available": False, "metadata": model_metadata_payload(None), "report": None}
    return {
        "available": bool(bundle.model.get("model_report")),
        "metadata": model_metadata_payload(bundle),
        "report": bundle.model.get("model_report"),
    }


@app.get("/api/xg/status")
def api_xg_status() -> dict[str, Any]:
    bundle = load_xg_model()
    return {
        "available": bool(bundle),
        "model_path": str(XG_MODEL_PATH),
        "shots_path": str(SHOT_EVENTS_PATH),
        "zones_path": str(XG_TEAM_ZONES_PATH),
        "metrics": bundle.get("metrics") if bundle else None,
        "trained_at": bundle.get("trained_at") if bundle else None,
        "training_source": bundle.get("training_source") if bundle else [],
        "note": bundle.get("note") if bundle else "Run scripts/xg_model.py to train the shot-level expected-goals model.",
    }


@app.post("/api/xg/predict")
def api_xg_predict(request: XGShotRequest) -> dict[str, Any]:
    bundle = load_xg_model()
    if not bundle:
        raise HTTPException(status_code=404, detail="Run scripts/xg_model.py before using the xG lab.")
    distance, angle = shot_geometry(request.shot_x, request.shot_y)
    shot = {
        "team": request.team,
        "player": request.player,
        "shot_x": request.shot_x,
        "shot_y": request.shot_y,
        "minute": request.minute,
        "distance_m": distance,
        "angle_degrees": angle,
        "body_part": request.body_part,
        "assist_type": request.assist_type,
        "defender_pressure": request.defender_pressure,
        "game_state": request.game_state,
        "shot_type": request.shot_type,
    }
    xg = predict_shot_xg(bundle, shot)
    return {
        "xg": round(xg, 4),
        "xg_pct": round(xg * 100, 1),
        "shot": {**shot, "distance_m": round(distance, 2), "angle_degrees": round(angle, 2)},
        "model": api_xg_status(),
    }


@app.get("/api/xg/danger")
def api_xg_danger(team: str | None = None) -> dict[str, Any]:
    rows = []
    if XG_TEAM_ZONES_PATH.exists():
        with XG_TEAM_ZONES_PATH.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if team and row["team"] != team:
                    continue
                rows.append(
                    {
                        "team": row["team"],
                        "x_zone": row["x_zone"],
                        "y_zone": row["y_zone"],
                        "shots": int(row["shots"]),
                        "actual_goals": int(row["actual_goals"]),
                        "predicted_goals": float(row["predicted_goals"]),
                        "avg_xg": float(row["avg_xg"]),
                        "goal_rate": float(row["goal_rate"]),
                        "xg_minus_goals": float(row["xg_minus_goals"]),
                    }
                )
    return {
        "team": team,
        "zones": sorted(rows, key=lambda row: (row["avg_xg"], row["shots"]), reverse=True),
        "source": str(XG_TEAM_ZONES_PATH),
        "message": "Predicted shots are compared with actual goals by zone to locate dangerous positions.",
    }


@app.get("/api/penalties/status")
def api_penalty_status() -> dict[str, Any]:
    bundle = load_penalty_model()
    return {
        "available": bool(bundle),
        "model_path": str(PENALTY_MODEL_PATH),
        "kicks_path": str(PENALTY_KICKS_PATH),
        "metrics": bundle.get("metrics") if bundle else None,
        "trained_at": bundle.get("trained_at") if bundle else None,
        "training_source": bundle.get("training_source") if bundle else [],
        "note": bundle.get("note") if bundle else "Run scripts/penalty_model.py to train the shootout models.",
    }


@app.get("/api/penalties/options")
def api_penalty_options() -> dict[str, Any]:
    players = load_squads()
    traits_by_player = {
        (row["team"], normalize_name_key(row["player"])): compact_player_trait(row)
        for row in load_player_match_stats()
    }
    kickers = [
        {
            "player": player["player"],
            "team": player["team"],
            "position": player["position"],
            "starter": player["projected_starter"],
            "market_value_eur": player["market_value_eur"],
            "normal_time": traits_by_player.get((player["team"], normalize_name_key(player["player"]))),
            "flag": FLAG_CODE_BY_TEAM.get(player["team"], "un").upper(),
            "flag_code": FLAG_CODE_BY_TEAM.get(player["team"], "un"),
            "flag_image": f"https://flagcdn.com/w80/{FLAG_CODE_BY_TEAM.get(player['team'], 'un')}.png",
        }
        for player in players
        if player["position"] != "GK"
    ]
    keepers = [
        {
            "player": player["player"],
            "team": player["team"],
            "position": player["position"],
            "starter": player["projected_starter"],
            "market_value_eur": player["market_value_eur"],
            "normal_time": traits_by_player.get((player["team"], normalize_name_key(player["player"]))),
            "flag": FLAG_CODE_BY_TEAM.get(player["team"], "un").upper(),
            "flag_code": FLAG_CODE_BY_TEAM.get(player["team"], "un"),
            "flag_image": f"https://flagcdn.com/w80/{FLAG_CODE_BY_TEAM.get(player['team'], 'un')}.png",
        }
        for player in players
        if player["position"] == "GK"
    ]
    key = lambda row: (not row["starter"], -row["market_value_eur"], row["player"])
    return {"kickers": sorted(kickers, key=key), "keepers": sorted(keepers, key=key)}


@app.post("/api/penalties/matchup")
def api_penalty_matchup(request: PenaltyMatchupRequest) -> dict[str, Any]:
    bundle = load_penalty_model()
    if not bundle:
        raise HTTPException(status_code=404, detail="Run scripts/penalty_model.py before using the shootout lab.")
    payload = predict_penalty_matchup(
        bundle,
        {
            "kicker": request.kicker,
            "goalkeeper": request.goalkeeper,
            "kicker_foot": request.kicker_foot,
            "kicker_position": request.kicker_position,
            "pressure_score": request.pressure_score,
            "score_state": request.score_state,
            "knockout_round": request.knockout_round,
            "kick_order": request.kick_order,
        },
    )
    return {
        "kicker": request.kicker,
        "goalkeeper": request.goalkeeper,
        "matchup": payload,
        "model": api_penalty_status(),
    }


@app.get("/api/squads")
def api_squads(team: str | None = None) -> dict[str, Any]:
    teams = load_teams()
    if team and team not in teams:
        raise HTTPException(status_code=404, detail="Unknown team")
    players = load_squads(team)
    player_stats = load_player_match_stats(team)
    stats_by_player = {
        (row["team"], normalize_name_key(row["player"])): row
        for row in player_stats
    }
    availability_by_player = {
        (row.get("team", ""), normalize_name_key(row.get("player", ""))): row
        for row in load_csv_rows(AVAILABILITY_PATH)
        if row.get("team") and row.get("player")
    }
    for player in players:
        traits = stats_by_player.get((player["team"], normalize_name_key(player["player"])))
        if traits:
            player["normal_time"] = compact_player_trait(traits)
        availability = availability_by_player.get((player["team"], normalize_name_key(player["player"])))
        if availability:
            player["advanced_availability"] = {
                "status": availability.get("status"),
                "minutes_limit": csv_float(availability, "minutes_limit", 90.0),
                "impact_score": csv_float(availability, "impact_score", 50.0),
                "source": availability.get("source"),
                "updated_at": availability.get("updated_at"),
            }
    summaries = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for player in players:
        grouped[player["team"]].append(player)
    for team_name, squad in grouped.items():
        starters = [player for player in squad if player["projected_starter"]]
        summaries.append(
            {
                **team_payload(teams[team_name]),
                "players": len(squad),
                "roster_slots_open": max(0, 26 - len(squad)),
                "formation": squad[0]["projected_formation"] if squad else None,
                "lineup_source": squad[0].get("projection_method") if squad else None,
                "lineup_updated_at": squad[0].get("lineup_updated_at") if squad else None,
                "lineup_confidence": round(teams[team_name].lineup_confidence, 1),
                "lineup_continuity": round(teams[team_name].lineup_continuity, 1),
                "observed_lineups_count": int(teams[team_name].observed_lineups_count),
                "unavailable_players": sum(player["availability"] < 1 for player in squad),
                "market_value_eur": sum(player["market_value_eur"] for player in squad),
                "projected_xi_value_eur": sum(player["market_value_eur"] for player in starters),
                "market_value_coverage": round(
                    100 * sum(player["market_value_eur"] > 0 for player in squad) / max(len(squad), 1),
                    1,
                ),
                "fetched_at": squad[0]["fetched_at"] if squad else None,
            }
        )
    return {
        "source": "Structured final-squad list citing association announcements; optional Transfermarkt value enrichment",
        "projection_note": "Observed recent lineups are used when available; otherwise the XI and formation are positional projections.",
        "normal_time_note": "Normal-time player stats are estimated from squad profile by default and can be replaced with a provider seasonal stats CSV.",
        "summaries": sorted(summaries, key=lambda row: row["market_value_eur"], reverse=True),
        "players": players,
        "normal_time": {
            "team_features": load_player_match_team_features(team),
            "players": [compact_player_trait(row) for row in player_stats],
            "source": str(PLAYER_MATCH_STATS_PATH),
        },
    }


@app.get("/api/player-match-stats")
def api_player_match_stats(team: str | None = None) -> dict[str, Any]:
    teams = load_teams()
    if team and team not in teams:
        raise HTTPException(status_code=404, detail="Unknown team")
    player_rows = load_player_match_stats(team)
    return {
        "source": str(PLAYER_MATCH_STATS_PATH),
        "team_features_source": str(PLAYER_MATCH_TEAM_FEATURES_PATH),
        "team_features": load_player_match_team_features(team),
        "players": player_rows,
        "message": "Normal-time seasonal-style player characteristics. Starter estimates can be replaced with provider stats via scripts/sync_player_match_stats.py --provider-stats.",
    }


@app.get("/api/lineup-status")
def api_lineup_status() -> dict[str, Any]:
    load_dotenv(ROOT / ".env", override=False)
    if not LINEUP_STATUS_PATH.exists():
        return {
            "configured": bool(os.getenv("SPORTMONKS_API_TOKEN")),
            "source": "projection-only",
            "teams_with_lineups": 0,
            "message": "Run scripts/sync_lineups.py after configuring SPORTMONKS_API_TOKEN.",
        }
    return {
        "configured": bool(os.getenv("SPORTMONKS_API_TOKEN")),
        **json.loads(LINEUP_STATUS_PATH.read_text(encoding="utf-8")),
    }


@app.post("/api/refresh-lineups")
def api_refresh_lineups() -> dict[str, Any]:
    sync_result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync_lineups.py"), "--optional"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=360,
        check=False,
    )
    if sync_result.returncode:
        raise HTTPException(status_code=502, detail=sync_result.stderr.strip() or sync_result.stdout.strip())
    rebuild_result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync_squads.py"), "--from-existing"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if rebuild_result.returncode:
        raise HTTPException(status_code=500, detail=rebuild_result.stderr.strip() or rebuild_result.stdout.strip())
    actual = refresh_actual_lineups()
    return {
        "message": sync_result.stdout.strip().splitlines()[-1] if sync_result.stdout.strip() else "Lineups refreshed.",
        "lineup_status": api_lineup_status(),
        "actual_lineups": actual,
    }


def _future_api_error(exc: ValueError | LookupError) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, LookupError) else 400, detail=str(exc))


@app.post("/api/refresh-player-stats")
def api_refresh_player_stats(request: RefreshRequest) -> dict[str, Any]:
    try:
        return refresh_player_stats(request)
    except ValueError as exc:
        raise _future_api_error(exc) from exc


@app.get("/api/player-role-vector/{player_id}")
def api_player_role_vector(player_id: str) -> dict[str, Any]:
    return get_player_role_vector(player_id)


@app.get("/api/team-role-depth/{team}")
def api_team_role_depth(team: str) -> dict[str, Any]:
    return get_role_depth(team)


@app.get("/api/player-availability/{player_id}")
def api_player_availability(player_id: str) -> dict[str, Any]:
    return get_player_availability(player_id)


@app.post("/api/refresh-injury-news")
def api_refresh_injury_news(request: RefreshRequest) -> dict[str, Any]:
    try:
        return refresh_injury_news(request)
    except ValueError as exc:
        raise _future_api_error(exc) from exc


@app.get("/api/injury-status")
def api_injury_status(team: str | None = None, match_id: str | None = None) -> dict[str, Any]:
    return get_injury_status(team, match_id)


@app.post("/api/refresh-tactical-evidence")
def api_refresh_tactical_evidence(request: RefreshRequest) -> dict[str, Any]:
    try:
        return refresh_tactical_evidence(request)
    except ValueError as exc:
        raise _future_api_error(exc) from exc


@app.get("/api/manager-evidence/{manager_id}")
def api_manager_evidence(manager_id: str) -> dict[str, Any]:
    return get_manager_evidence(manager_id)


@app.post("/api/manager-skill/refine-dry-run")
def api_manager_skill_refine_dry_run(request: ManagerSkillApplyRequest) -> dict[str, Any]:
    return refine_manager_skills_dry_run(request.manager_id)


@app.post("/api/manager-skill/apply-update")
def api_manager_skill_apply_update(request: ManagerSkillApplyRequest) -> dict[str, Any]:
    try:
        return apply_manager_skill_review(request)
    except ValueError as exc:
        raise _future_api_error(exc) from exc


@app.get("/api/lineup-delta")
def api_lineup_delta(team: str | None = None, match_id: str | None = None) -> dict[str, Any]:
    return get_lineup_delta(team, match_id)


@app.post("/api/refresh-event-data")
def api_refresh_event_data(request: RefreshRequest) -> dict[str, Any]:
    try:
        return refresh_event_data(request)
    except ValueError as exc:
        raise _future_api_error(exc) from exc


@app.post("/api/evaluate-match")
def api_evaluate_match(request: EvaluateMatchRequest) -> dict[str, Any]:
    try:
        return evaluate_future_match(request)
    except (ValueError, LookupError) as exc:
        raise _future_api_error(exc) from exc


@app.get("/api/evaluation/match/{match_id}")
def api_match_evaluation(match_id: str) -> dict[str, Any]:
    return get_match_evaluation(match_id)


@app.get("/api/evaluation/manager/{manager_id}")
def api_manager_evaluation(manager_id: str) -> dict[str, Any]:
    return get_manager_evaluation(manager_id)


@app.get("/api/evaluation/analyst/{analyst}")
def api_analyst_evaluation(analyst: str) -> dict[str, Any]:
    return get_analyst_evaluation(analyst)


@app.get("/api/evaluation/model")
def api_model_evaluation() -> dict[str, Any]:
    return get_model_evaluation()


@app.post("/api/tournament-autopilot/run")
def api_tournament_autopilot(request: TournamentAutopilotRequest) -> dict[str, Any]:
    return run_tournament_autopilot(
        refresh_provider=request.refresh_provider,
        run_arena=request.run_arena,
        settle_and_evaluate=request.settle_and_evaluate,
        hours_ahead=request.hours_ahead,
    ).as_dict()


@app.get("/api/observed-matches")
def api_observed_matches() -> dict[str, Any]:
    rows = load_observed_matches()
    return {"matches": [row.model_dump(mode="json") for row in rows], "count": len(rows)}


def _arena_http_error(exc: ValueError | LookupError) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, LookupError) else 400, detail=str(exc))


@app.post("/api/prediction-arena/run")
def api_prediction_arena_run(request: PredictionArenaRunRequest) -> dict[str, Any]:
    try:
        return run_arena_match(
            request.match_id,
            request.team_a,
            request.team_b,
            request.stage,
            lock=request.lock,
            publish_card=request.publish_card,
        )
    except (ValueError, LookupError) as exc:
        raise _arena_http_error(exc) from exc


@app.get("/api/prediction-arena/match/{match_id}")
def api_prediction_arena_match(match_id: str) -> dict[str, Any]:
    return get_arena_match(match_id)


@app.post("/api/prediction-arena/lock")
def api_prediction_arena_lock(request: PredictionArenaMatchRequest) -> dict[str, Any]:
    try:
        return lock_arena_match(request.match_id)
    except (ValueError, LookupError) as exc:
        raise _arena_http_error(exc) from exc


@app.post("/api/prediction-arena/publish-card")
def api_prediction_arena_publish_card(request: PredictionArenaMatchRequest) -> dict[str, Any]:
    try:
        return publish_arena_card(request.match_id)
    except (ValueError, LookupError) as exc:
        raise _arena_http_error(exc) from exc


@app.post("/api/prediction-arena/settle")
def api_prediction_arena_settle(request: PredictionArenaSettleRequest) -> dict[str, Any]:
    try:
        return settle_arena_match(
            request.match_id,
            request.actual_score,
            request.regular_time_result,
            request.qualification_result,
        )
    except (ValueError, LookupError) as exc:
        raise _arena_http_error(exc) from exc


@app.get("/api/prediction-arena/leaderboard")
def api_prediction_arena_leaderboard() -> dict[str, Any]:
    return get_arena_leaderboard()


@app.get("/api/prediction-arena/calibration")
def api_prediction_arena_calibration() -> dict[str, Any]:
    return get_arena_calibration()


@app.get("/api/live-state")
def api_live_state() -> dict[str, Any]:
    return {"live_state": load_live_state()}


@app.get("/api/tactics/managers")
def api_tactics_managers() -> dict[str, Any]:
    return list_manager_catalog()


@app.get("/api/tactics/manager/{team}")
def api_tactics_manager(team: str) -> dict[str, Any]:
    return get_team_manager_overview(team)


@app.get("/api/tactics/coverage/{team}")
def api_tactics_coverage(team: str) -> dict[str, Any]:
    return team_data_coverage(team).model_dump(mode="json")


@app.post("/api/tactics/matchups")
def api_tactics_matchups(request: TacticalMatchupRequest) -> dict[str, Any]:
    return build_matchup_report(request.team_a, request.team_b, request.match_id, request.top_n)


@app.post("/api/tactics/brief")
def api_tactics_brief(request: TacticalBriefRequest) -> dict[str, Any]:
    forecast = None
    try:
        forecast = api_match(
            MatchRequest(
                team_a=request.team_a,
                team_b=request.team_b,
                use_model=request.use_model,
                top_scores=request.top_scores,
                weather=request.weather,
                travel=request.travel,
                fatigue=request.fatigue,
                home_advantage=request.home_advantage,
                venue=request.venue,
            )
        )
    except HTTPException as exc:
        if exc.status_code != 404:
            raise

    return build_tactical_brief(
        request.team_a,
        request.team_b,
        match_id=request.match_id,
        forecast=forecast,
        match_context_a=request.match_context_a,
        match_context_b=request.match_context_b,
        top_matchups=request.top_matchups,
    ).model_dump(mode="json")


@app.post("/api/tactics/brief-with-lineups")
def api_tactics_brief_with_lineups(request: TacticalBriefRequest) -> dict[str, Any]:
    brief = api_tactics_brief(request)
    return {
        **brief,
        "lineup_delta": {
            request.team_a: get_lineup_delta(request.team_a, request.match_id),
            request.team_b: get_lineup_delta(request.team_b, request.match_id),
        },
    }


def _journal_http_error(exc: AnalystJournalError) -> HTTPException:
    if isinstance(exc, JournalNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, JournalConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@app.post("/api/analyst/log")
def api_analyst_log(request: PredictionLogCreate) -> dict[str, Any]:
    try:
        log = create_prediction_log(request)
    except AnalystJournalError as exc:
        raise _journal_http_error(exc) from exc
    return {"prediction_log": log.model_dump(mode="json"), "append_only": True}


@app.get("/api/analyst/logs")
def api_analyst_logs(analyst: str | None = None, limit: int = 100) -> dict[str, Any]:
    if not 1 <= limit <= 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
    try:
        logs = load_prediction_logs(analyst, limit=limit)
    except AnalystJournalError as exc:
        raise _journal_http_error(exc) from exc
    return {
        "logs": [log.model_dump(mode="json") for log in logs],
        "count": len(logs),
        "analyst": analyst,
        "append_only": True,
    }


@app.post("/api/analyst/postgame-review")
def api_analyst_postgame_review(request: PostgameReviewCreate) -> dict[str, Any]:
    try:
        review = create_postgame_review(request)
    except AnalystJournalError as exc:
        raise _journal_http_error(exc) from exc
    return {"postgame_review": review.model_dump(mode="json"), "original_prediction_unchanged": True}


@app.get("/api/analyst/profile/{analyst}")
def api_analyst_profile(analyst: str) -> dict[str, Any]:
    try:
        profile = summarize_analyst_profile(analyst)
    except AnalystJournalError as exc:
        raise _journal_http_error(exc) from exc
    return profile.model_dump(mode="json")


@app.post("/api/simulate")
def api_simulate(request: SimulationRequest) -> dict[str, Any]:
    context = request_context(request)
    teams = load_teams()
    groups = load_groups(teams)
    state = load_live_state()
    bundle = load_cached_model() if request.use_model else None
    bracket = simulate_detail_core(teams, groups, state, bundle, request.seed, context)
    odds = run_many(request.sims, request.seed, request.use_model, context)
    return {"bracket": bracket, "odds": odds}


@app.post("/api/match")
def api_match(request: MatchRequest) -> dict[str, Any]:
    teams = load_teams()
    if request.team_a not in teams or request.team_b not in teams:
        raise HTTPException(status_code=404, detail="Unknown team")
    bundle = load_cached_model() if request.use_model else None
    team_a = teams[request.team_a]
    team_b = teams[request.team_b]
    context = matchup_context(request_context(request), team_a, team_b)
    score_distribution = context_score_distribution(team_a, team_b, bundle, context, max_goals=10)
    probabilities = aggregate_scoreline_probabilities(score_distribution)
    scores = score_distribution[: request.top_scores]
    score_matrix = score_matrix_from_scorelines(score_distribution, max_goals=6)
    score_aggregates = score_matrix["aggregates"]
    lambda_a = sum(goals_a * probability for goals_a, _, probability in score_distribution)
    lambda_b = sum(goals_b * probability for _, goals_b, probability in score_distribution)
    return {
        "team_a": team_payload(team_a),
        "team_b": team_payload(team_b),
        "expected_score": {"team_a": round(lambda_a, 2), "team_b": round(lambda_b, 2)},
        "probabilities": {key: round(value * 100, 1) for key, value in probabilities.items()},
        "score_aggregate_probabilities": score_aggregates,
        "score_matrix": score_matrix["cells"],
        "forecast_stack": forecast_stack_payload(team_a, team_b, bundle, context, lambda_a, lambda_b),
        "advanced_signals": advanced_signal_pair(team_a, team_b, context),
        "confidence": confidence_payload(score_aggregates, team_a, team_b),
        "score_insights": score_insight_payload(score_matrix["cells"]),
        "model_drivers": model_feature_drivers(team_a, team_b, bundle, top_n=6),
        "shap_drivers": shap_driver_payload(team_a, team_b, bundle, score_aggregates, top_n=6),
        "scenario_drivers": scenario_driver_payload(team_a, team_b, context),
        "model_metadata": model_metadata_payload(bundle),
        "scorelines": [
            {"team_a_score": a, "team_b_score": b, "probability": round(probability * 100, 1)}
            for a, b, probability in scores
        ],
    }


@app.post("/api/match-with-lineups")
def api_match_with_lineups(request: MatchRequest, match_id: str | None = None) -> dict[str, Any]:
    forecast = api_match(request)
    return enrich_forecast_with_lineups(forecast, request.team_a, request.team_b, match_id)


@app.get("/api/ai/status")
def api_ai_status() -> dict[str, Any]:
    catalog = list_manager_catalog()
    board = live_match_board(load_live_state())
    return {
        "manager_profiles": catalog["count"],
        "manager_skills": catalog["skills_count"],
        "manager_profiles_without_skill": max(0, catalog["count"] - catalog["skills_count"]),
        "manager_curation": catalog["curation"],
        "intelligence": get_intelligence_index(ROOT).status(),
        "live": {
            "source": board["source"],
            "updated_at": board["updated_at"],
            "completed_count": board["completed_count"],
            "awaiting_result_count": board["awaiting_result_count"],
        },
        "reasoning_boundary": (
            "AI explanations combine deterministic forecasts, transparent tactical rules, player comparisons, "
            "and retrieved local evidence. They do not alter the underlying probabilities."
        ),
    }


@app.get("/api/ai/live-board")
def api_ai_live_board() -> dict[str, Any]:
    return live_match_board(load_live_state())


@app.get("/api/ai/match-stories")
def api_ai_match_stories(limit: int = 6, offset: int = 0, use_model: bool = True) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 8))
    safe_offset = max(0, offset)
    live_state = load_live_state()
    board = live_match_board(live_state, limit=104)
    fixtures = board["upcoming"][safe_offset:safe_offset + safe_limit]
    stories = []
    warnings = []
    for fixture in fixtures:
        try:
            forecast = api_match(
                MatchRequest(
                    team_a=fixture["team_a"],
                    team_b=fixture["team_b"],
                    use_model=use_model,
                    top_scores=3,
                    weather="auto",
                    venue=fixture.get("venue"),
                )
            )
            stories.append(build_match_story(fixture, forecast, live_state))
        except (HTTPException, KeyError, ValueError) as exc:
            warnings.append(
                {
                    "match_id": fixture.get("match_id"),
                    "match": f"{fixture.get('team_a', 'Unknown')} vs {fixture.get('team_b', 'Unknown')}",
                    "note": str(exc),
                }
            )
    return {
        "stories": stories,
        "warnings": warnings,
        "source": board["source"],
        "updated_at": board["updated_at"],
        "offset": safe_offset,
        "limit": safe_limit,
        "total_upcoming": len(board["upcoming"]),
        "next_offset": safe_offset + len(fixtures),
        "has_more": safe_offset + len(fixtures) < len(board["upcoming"]),
        "reasoning_boundary": "Match stories summarize existing forecasts and do not alter prediction behavior.",
    }


@app.get("/api/ai/player-comparison")
def api_ai_player_comparison(team_a: str, team_b: str) -> dict[str, Any]:
    teams = load_teams()
    if team_a not in teams or team_b not in teams:
        raise HTTPException(status_code=404, detail="Unknown team")
    if team_a == team_b:
        raise HTTPException(status_code=400, detail="Choose two different teams")
    return build_player_matchup_intelligence(team_a, team_b)


@app.post("/api/ai/match")
def api_ai_match(request: AiMatchRequest) -> dict[str, Any]:
    teams = load_teams()
    if request.team_a not in teams or request.team_b not in teams:
        raise HTTPException(status_code=404, detail="Unknown team")
    if request.team_a == request.team_b:
        raise HTTPException(status_code=400, detail="Choose two different teams")
    forecast = api_match(
        MatchRequest(
            team_a=request.team_a,
            team_b=request.team_b,
            use_model=request.use_model,
            top_scores=8,
            weather="auto",
        )
    )
    return build_match_reasoning(
        request.team_a,
        request.team_b,
        forecast,
        load_live_state(),
        match_id=request.match_id,
        use_llm=request.use_llm,
    )


@app.post("/api/ai/tournament")
def api_ai_tournament(request: AiTournamentRequest) -> dict[str, Any]:
    simulation = api_simulate(
        SimulationRequest(
            sims=request.sims,
            seed=request.seed,
            use_model=request.use_model,
            weather="auto",
        )
    )
    return build_tournament_reasoning(simulation, load_live_state())


def driver_label(driver: dict[str, Any]) -> str:
    for key in ("label", "feature", "name"):
        if driver.get(key):
            return str(driver[key]).replace("_", " ")
    return "model signal"


def squad_summary_for_team(team: str) -> dict[str, Any] | None:
    try:
        payload = api_squads(team)
    except HTTPException:
        return None
    return payload["summaries"][0] if payload.get("summaries") else None


def xg_danger_summary(team: str) -> dict[str, Any] | None:
    payload = api_xg_danger(team)
    zones = payload.get("zones") or []
    if not zones:
        return None
    zone = zones[0]
    return {
        "zone": f"{zone['x_zone']} / {zone['y_zone']}",
        "shots": zone["shots"],
        "avg_xg_pct": round(zone["avg_xg"] * 100, 1),
        "predicted_goals": round(zone["predicted_goals"], 2),
        "actual_goals": zone["actual_goals"],
    }


def same_market_match(edge: dict[str, Any], team_a: str, team_b: str) -> bool:
    edge_teams = {edge.get("team_a"), edge.get("team_b")}
    if edge_teams == {team_a, team_b}:
        return True
    event = normalize_name_key(edge.get("event", ""))
    return normalize_name_key(team_a) in event and normalize_name_key(team_b) in event


def match_market_edges(team_a: str, team_b: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    edges = payload.get("edges") or []
    return [edge for edge in edges if same_market_match(edge, team_a, team_b)]


def analyst_evidence(team_a: str, team_b: str) -> tuple[list[dict[str, Any]], str]:
    index = get_intelligence_index(ROOT)
    try:
        index.ensure_ready()
        evidence = index.retrieve(
            f"{team_a} vs {team_b} World Cup model squad xG penalty market weather",
            5,
            [team_a, team_b],
        )
        return evidence, f"Retrieved {len(evidence)} local evidence chunks"
    except Exception as exc:  # pragma: no cover - defensive for optional local indexes
        return [], f"Evidence retrieval unavailable: {exc}"


def analyst_headline(team_a: str, team_b: str, probabilities: dict[str, float]) -> tuple[str, str, str]:
    team_a_prob = probabilities["team_a_win"]
    team_b_prob = probabilities["team_b_win"]
    draw_prob = probabilities["draw"]
    if abs(team_a_prob - team_b_prob) < 3:
        return (
            f"{team_a} vs {team_b} is close",
            "Toss-up",
            f"Only {abs(team_a_prob - team_b_prob):.1f} points separate the two win probabilities; draw risk is {draw_prob:.1f}%.",
        )
    leader = team_a if team_a_prob > team_b_prob else team_b
    lead_prob = max(team_a_prob, team_b_prob)
    gap = abs(team_a_prob - team_b_prob)
    strength = "clear" if gap >= 12 else "slight"
    return (
        f"{leader} has a {strength} model edge",
        f"{leader} lean",
        f"The model gives {leader} {lead_prob:.1f}% in regulation-style score aggregation, a {gap:.1f}-point gap before shootout randomness.",
    )


def analyst_factor_cards(
    match: dict[str, Any],
    team_a_squad: dict[str, Any] | None,
    team_b_squad: dict[str, Any] | None,
    team_a_xg: dict[str, Any] | None,
    team_b_xg: dict[str, Any] | None,
    market_edges: list[dict[str, Any]],
    weather_payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    probabilities = match["score_aggregate_probabilities"]
    top_score = match["scorelines"][0]
    top_score_text = f"{top_score['team_a_score']}-{top_score['team_b_score']}"
    cards = [
        {
            "agent": "Forecast analyst",
            "title": "Exact-score center",
            "value": top_score_text,
            "detail": f"{top_score['probability']}% mode; {probabilities['team_a_win']}% / {probabilities['draw']}% / {probabilities['team_b_win']}% split.",
            "tone": "primary",
        }
    ]

    drivers = (match.get("shap_drivers", {}).get("drivers") or match.get("model_drivers") or [])[:3]
    cards.append(
        {
            "agent": "Model driver analyst",
            "title": "Top model signals",
            "value": str(len(drivers)),
            "detail": ", ".join(driver_label(driver) for driver in drivers) if drivers else "Train the ensemble to expose richer drivers.",
            "tone": "neutral",
        }
    )

    if team_a_squad and team_b_squad:
        confidence_gap = team_a_squad["lineup_confidence"] - team_b_squad["lineup_confidence"]
        value_gap = team_a_squad["projected_xi_value_eur"] - team_b_squad["projected_xi_value_eur"]
        leader = team_a_squad["name"] if confidence_gap + (value_gap / 10_000_000) >= 0 else team_b_squad["name"]
        cards.append(
            {
                "agent": "Squad analyst",
                "title": "XI confidence and value",
                "value": leader,
                "detail": f"{team_a_squad['name']} XI {team_a_squad['lineup_confidence']}% / {euros_text(team_a_squad['projected_xi_value_eur'])}; {team_b_squad['name']} XI {team_b_squad['lineup_confidence']}% / {euros_text(team_b_squad['projected_xi_value_eur'])}.",
                "tone": "neutral",
            }
        )

    if team_a_xg or team_b_xg:
        xg_bits = []
        if team_a_xg:
            xg_bits.append(f"{match['team_a']['name']} {team_a_xg['avg_xg_pct']}% from {team_a_xg['zone']}")
        if team_b_xg:
            xg_bits.append(f"{match['team_b']['name']} {team_b_xg['avg_xg_pct']}% from {team_b_xg['zone']}")
        cards.append(
            {
                "agent": "Shot-quality analyst",
                "title": "Danger zones",
                "value": "xG",
                "detail": "; ".join(xg_bits),
                "tone": "neutral",
            }
        )

    team_a_traits = match["team_a"]["model_factors"]
    team_b_traits = match["team_b"]["model_factors"]
    a_attack = (team_a_traits["player_shooting"] + team_a_traits["player_chance_creation"] + team_a_traits["player_progression"]) / 3
    b_attack = (team_b_traits["player_shooting"] + team_b_traits["player_chance_creation"] + team_b_traits["player_progression"]) / 3
    a_without_ball = (team_a_traits["player_defensive_activity"] + team_a_traits["player_goalkeeping"]) / 2
    b_without_ball = (team_b_traits["player_defensive_activity"] + team_b_traits["player_goalkeeping"]) / 2
    trait_leader = match["team_a"]["name"] if (a_attack + a_without_ball) >= (b_attack + b_without_ball) else match["team_b"]["name"]
    cards.append(
        {
            "agent": "Normal-time player analyst",
            "title": "Seasonal trait layer",
            "value": trait_leader,
            "detail": f"{match['team_a']['name']} attack {a_attack:.1f}, off-ball/GK {a_without_ball:.1f}; {match['team_b']['name']} attack {b_attack:.1f}, off-ball/GK {b_without_ball:.1f}.",
            "tone": "neutral",
        }
    )

    if market_edges:
        best = market_edges[0]
        tone = "positive" if best["expected_value_pct"] > 0 and best["edge_pct"] > 0 else "warning"
        cards.append(
            {
                "agent": "Market analyst",
                "title": "Book price gap",
                "value": f"{best['expected_value_pct']}% EV",
                "detail": f"{best['selection']} at {best['bookmaker']}; model {best['model_probability']}% vs no-vig {best['no_vig_probability']}%.",
                "tone": tone,
            }
        )
    else:
        cards.append(
            {
                "agent": "Market analyst",
                "title": "Book price gap",
                "value": "No match",
                "detail": "No local bookmaker row matched this fixture. Pull a snapshot or add odds to data/bookmaker_odds.csv.",
                "tone": "warning",
            }
        )

    if weather_payload and weather_payload.get("venue"):
        current = weather_payload.get("current") or {}
        temp = current.get("temperature_2m")
        wind = current.get("wind_speed_10m")
        cards.append(
            {
                "agent": "Environment analyst",
                "title": weather_payload["venue"]["venue"],
                "value": str(weather_payload.get("weather", "normal")).title(),
                "detail": f"{weather_payload['venue']['city']} context; temp {temp if temp is not None else 'n/a'} C, wind {wind if wind is not None else 'n/a'} km/h.",
                "tone": "neutral",
            }
        )

    team_a_penalty = match["team_a"]["model_factors"]["penalties"]
    team_b_penalty = match["team_b"]["model_factors"]["penalties"]
    penalty_leader = match["team_a"]["name"] if team_a_penalty >= team_b_penalty else match["team_b"]["name"]
    cards.append(
        {
            "agent": "Shootout analyst",
            "title": "Penalty fallback",
            "value": penalty_leader,
            "detail": f"Aggregate shootout strength: {match['team_a']['name']} {team_a_penalty}, {match['team_b']['name']} {team_b_penalty}.",
            "tone": "neutral",
        }
    )
    return cards


def euros_text(value: float | int | None) -> str:
    amount = float(value or 0)
    if amount >= 1_000_000_000:
        return f"EUR {amount / 1_000_000_000:.2f}bn"
    if amount >= 1_000_000:
        return f"EUR {amount / 1_000_000:.1f}m"
    if amount >= 1_000:
        return f"EUR {amount / 1_000:.0f}k"
    return "n/a"


@app.post("/api/analyst-brief")
def api_analyst_brief(request: AnalystBriefRequest) -> dict[str, Any]:
    if request.team_a == request.team_b:
        raise HTTPException(status_code=400, detail="Choose two different teams.")

    trace = []
    odds_snapshot = None
    if request.refresh_odds:
        odds_snapshot = refresh_the_odds_api_snapshot(OddsSnapshotRequest())
        trace.append(
            {
                "step": "refresh_market_snapshot",
                "status": "complete" if odds_snapshot.get("ok") else "warning",
                "detail": odds_snapshot.get("message", "Odds snapshot checked"),
            }
        )

    match = api_match(
        MatchRequest(
            team_a=request.team_a,
            team_b=request.team_b,
            use_model=request.use_model,
            top_scores=6,
            weather=request.weather,
            travel=request.travel,
            fatigue=request.fatigue,
            home_advantage=request.home_advantage,
            venue=request.venue,
        )
    )
    trace.append(
        {
            "step": "forecast",
            "status": "complete",
            "detail": f"Computed exact-score distribution for {request.team_a} vs {request.team_b}",
        }
    )

    betting_payload = api_betting_edges(
        BettingEdgesRequest(
            sims=request.sims,
            seed=26,
            use_model=request.use_model,
            weather=request.weather,
            travel=request.travel,
            fatigue=request.fatigue,
            home_advantage=request.home_advantage,
            venue=request.venue,
            min_edge_pct=-100,
        )
    )
    market_edges = match_market_edges(request.team_a, request.team_b, betting_payload)
    trace.append(
        {
            "step": "market_compare",
            "status": "complete" if betting_payload.get("ok") else "warning",
            "detail": f"Compared {len(market_edges)} matched bookmaker rows against model probabilities",
        }
    )

    team_a_squad = squad_summary_for_team(request.team_a)
    team_b_squad = squad_summary_for_team(request.team_b)
    trace.append(
        {
            "step": "squad_check",
            "status": "complete" if team_a_squad and team_b_squad else "warning",
            "detail": "Loaded projected squads and XI confidence" if team_a_squad and team_b_squad else "Squad summary unavailable",
        }
    )

    team_a_xg = xg_danger_summary(request.team_a)
    team_b_xg = xg_danger_summary(request.team_b)
    trace.append(
        {
            "step": "shot_quality",
            "status": "complete" if team_a_xg or team_b_xg else "warning",
            "detail": "Loaded xG danger zones" if team_a_xg or team_b_xg else "Train xG model to unlock danger-zone context",
        }
    )

    weather_payload = None
    if request.weather == "auto" and request.venue:
        weather_payload = venue_weather_payload(request.venue)
        trace.append(
            {
                "step": "venue_weather",
                "status": "complete",
                "detail": f"Applied live venue weather for {request.venue}",
            }
        )

    evidence, evidence_detail = analyst_evidence(request.team_a, request.team_b)
    trace.append({"step": "retrieve_evidence", "status": "complete" if evidence else "warning", "detail": evidence_detail})

    probabilities = match["score_aggregate_probabilities"]
    headline, recommendation, core_thesis = analyst_headline(request.team_a, request.team_b, probabilities)
    top_score = match["scorelines"][0]
    paper_edge = next((edge for edge in market_edges if edge["expected_value_pct"] > 0 and edge["edge_pct"] > 0), None)
    if paper_edge:
        recommendation = f"Paper watchlist: {paper_edge['selection']}"
        market_thesis = f"The strongest market disagreement is {paper_edge['selection']} at {paper_edge['bookmaker']} with {paper_edge['expected_value_pct']}% expected value before limits, timing, and model risk."
    elif market_edges:
        market_thesis = "Matched bookmaker rows are mostly aligned with the model, so this is a forecast read more than a price-dislocation read."
    else:
        market_thesis = "No matched bookmaker row is available yet, so the brief should be treated as model-plus-context only."

    cards = analyst_factor_cards(match, team_a_squad, team_b_squad, team_a_xg, team_b_xg, market_edges, weather_payload)
    trace.append(
        {
            "step": "synthesize",
            "status": "complete",
            "detail": "Combined forecast, squad, xG, weather, penalties, market, and evidence into one analyst brief",
        }
    )
    return {
        "ok": True,
        "headline": headline,
        "recommendation": recommendation,
        "thesis": f"{core_thesis} The most likely exact score is {top_score['team_a_score']}-{top_score['team_b_score']} at {top_score['probability']}%. {market_thesis}",
        "teams": {"team_a": match["team_a"], "team_b": match["team_b"]},
        "forecast": {
            "expected_score": match["expected_score"],
            "probabilities": probabilities,
            "top_scoreline": top_score,
            "scorelines": match["scorelines"],
            "confidence": match["confidence"],
            "drivers": (match.get("shap_drivers", {}).get("drivers") or match.get("model_drivers") or [])[:5],
        },
        "factor_cards": cards,
        "market_edges": market_edges[:8],
        "market_status": {
            "ok": betting_payload.get("ok"),
            "source": betting_payload.get("source"),
            "message": betting_payload.get("message"),
            "matched_rows": len(market_edges),
        },
        "odds_snapshot": odds_snapshot,
        "watchlist": [
            "Re-run after confirmed lineups, injuries, and suspensions.",
            "Treat paper EV as a disagreement signal, not betting advice.",
            "Watch venue weather if heat, rain, altitude, or travel load is active.",
            "In knockout rounds, compare regulation lean separately from shootout strength.",
        ],
        "agent_trace": trace,
        "evidence": evidence,
        "disclaimer": "Educational football analytics only. Odds are volatile, models can be wrong, and this is not financial or betting advice.",
    }


def scorelines_from_lambdas(lambda_a: float, lambda_b: float, max_goals: int = 7) -> list[tuple[int, int, float]]:
    rows = []
    for goals_a in range(max_goals + 1):
        probability_a = (2.718281828 ** -lambda_a) * (lambda_a**goals_a) / factorial(goals_a)
        for goals_b in range(max_goals + 1):
            probability_b = (2.718281828 ** -lambda_b) * (lambda_b**goals_b) / factorial(goals_b)
            rows.append((goals_a, goals_b, probability_a * probability_b))
    return sorted(rows, key=lambda row: row[2], reverse=True)


def score_matrix_payload(lambda_a: float, lambda_b: float, max_goals: int = 6) -> dict[str, Any]:
    rows = []
    win_a = 0.0
    draw = 0.0
    win_b = 0.0
    total = 0.0
    for goals_a in range(max_goals + 1):
        for goals_b in range(max_goals + 1):
            probability = ((2.718281828 ** -lambda_a) * (lambda_a**goals_a) / factorial(goals_a)) * (
                (2.718281828 ** -lambda_b) * (lambda_b**goals_b) / factorial(goals_b)
            )
            total += probability
            if goals_a > goals_b:
                win_a += probability
                outcome = "team_a_win"
            elif goals_b > goals_a:
                win_b += probability
                outcome = "team_b_win"
            else:
                draw += probability
                outcome = "draw"
            rows.append(
                {
                    "team_a_score": goals_a,
                    "team_b_score": goals_b,
                    "probability": probability,
                    "outcome": outcome,
                }
            )
    return {
        "aggregates": {
            "team_a_win": round(100 * win_a / total, 1),
            "draw": round(100 * draw / total, 1),
            "team_b_win": round(100 * win_b / total, 1),
        },
        "cells": [
            {
                **row,
                "probability": round(100 * row["probability"] / total, 2),
            }
            for row in rows
        ],
    }


def score_matrix_from_scorelines(scorelines: list[tuple[int, int, float]], max_goals: int = 6) -> dict[str, Any]:
    aggregate = aggregate_scoreline_probabilities(scorelines)
    cells = []
    for goals_a, goals_b, probability in scorelines:
        if goals_a > max_goals or goals_b > max_goals:
            continue
        outcome = "team_a_win" if goals_a > goals_b else "team_b_win" if goals_b > goals_a else "draw"
        cells.append(
            {
                "team_a_score": goals_a,
                "team_b_score": goals_b,
                "probability": round(100 * probability, 2),
                "outcome": outcome,
            }
        )
    return {
        "aggregates": {key: round(100 * value, 1) for key, value in aggregate.items()},
        "cells": cells,
    }


def confidence_payload(aggregates: dict[str, float], team_a: Team, team_b: Team) -> dict[str, Any]:
    outcomes = [
        {"key": "team_a_win", "label": team_a.name, "probability": aggregates["team_a_win"]},
        {"key": "draw", "label": "Draw", "probability": aggregates["draw"]},
        {"key": "team_b_win", "label": team_b.name, "probability": aggregates["team_b_win"]},
    ]
    ordered = sorted(outcomes, key=lambda item: item["probability"], reverse=True)
    margin = ordered[0]["probability"] - ordered[1]["probability"]
    top = ordered[0]["probability"]
    entropy = 0.0
    for outcome in outcomes:
        probability = max(outcome["probability"] / 100, 0.0001)
        entropy -= probability * math.log(probability, 3)

    if top >= 52 and margin >= 16:
        label = "High"
    elif top >= 43 and margin >= 8:
        label = "Medium"
    else:
        label = "Volatile"

    return {
        "label": label,
        "favorite": ordered[0],
        "margin_pct": round(margin, 1),
        "uncertainty_pct": round(100 * min(1.0, entropy), 1),
    }


def score_insight_payload(cells: list[dict[str, Any]]) -> dict[str, Any]:
    def total_if(predicate: Any) -> float:
        return sum(float(cell["probability"]) for cell in cells if predicate(cell))

    most_likely = max(cells, key=lambda cell: float(cell["probability"]))
    return {
        "most_likely_score": {
            "team_a_score": most_likely["team_a_score"],
            "team_b_score": most_likely["team_b_score"],
            "probability": most_likely["probability"],
        },
        "under_2_5_goals": round(total_if(lambda cell: cell["team_a_score"] + cell["team_b_score"] <= 2), 1),
        "over_2_5_goals": round(total_if(lambda cell: cell["team_a_score"] + cell["team_b_score"] >= 3), 1),
        "both_teams_score": round(total_if(lambda cell: cell["team_a_score"] > 0 and cell["team_b_score"] > 0), 1),
        "clean_sheet": round(total_if(lambda cell: cell["team_a_score"] == 0 or cell["team_b_score"] == 0), 1),
        "one_goal_margin": round(total_if(lambda cell: abs(cell["team_a_score"] - cell["team_b_score"]) == 1), 1),
        "regulation_draw": round(total_if(lambda cell: cell["team_a_score"] == cell["team_b_score"]), 1),
    }


def scenario_driver_payload(team_a: Team, team_b: Team, context: dict[str, Any]) -> list[dict[str, Any]]:
    drivers = []
    squad_signals = [
        ("Projected XI quality", team_a.projected_xi_score - team_b.projected_xi_score, 4.0),
        ("26-player roster value", team_a.roster_value_score - team_b.roster_value_score, 3.0),
        ("Squad experience", team_a.squad_experience - team_b.squad_experience, 2.0),
        ("Formation fit", team_a.formation_fit - team_b.formation_fit, 2.0),
        ("Lineup continuity", team_a.lineup_continuity - team_b.lineup_continuity, 2.0),
        ("Available XI quality", team_a.squad_availability - team_b.squad_availability, 3.0),
        ("Player shooting traits", team_a.player_shooting_score - team_b.player_shooting_score, 2.2),
        ("Chance creation traits", team_a.player_chance_creation_score - team_b.player_chance_creation_score, 2.0),
        ("Passing control traits", team_a.player_passing_score - team_b.player_passing_score, 1.8),
        ("Normal-time defending traits", team_a.player_defensive_activity_score - team_b.player_defensive_activity_score, 1.8),
        ("Goalkeeper normal-time traits", team_a.player_goalkeeping_score - team_b.player_goalkeeping_score, 2.0),
        ("Late-goal profile", team_a.player_late_goal_score - team_b.player_late_goal_score, 1.6),
    ]
    for label, difference, multiplier in squad_signals:
        if abs(difference) >= 1:
            favored = team_a if difference > 0 else team_b
            drivers.append({"label": label, "favored_team": favored.name, "impact": round(min(100.0, 25 + abs(difference) * multiplier), 1)})
    weather = context.get("weather", "normal")
    if weather != "normal":
        if weather == "heat":
            favored = team_a if team_a.fitness >= team_b.fitness else team_b
            impact = min(100.0, 35 + abs(team_a.fitness - team_b.fitness) * 3)
            label = "Heat fitness edge"
        elif weather in {"rain", "cold"}:
            favored = team_a if team_a.set_piece_attack >= team_b.set_piece_attack else team_b
            impact = min(100.0, 35 + abs(team_a.set_piece_attack - team_b.set_piece_attack) * 3)
            label = "Weather set-piece edge"
        else:
            favored = team_a if team_a.fitness + team_a.bench >= team_b.fitness + team_b.bench else team_b
            impact = min(100.0, 35 + abs((team_a.fitness + team_a.bench) - (team_b.fitness + team_b.bench)) * 1.5)
            label = "Altitude depth edge"
        drivers.append({"label": label, "favored_team": favored.name, "impact": round(impact, 1)})

    team_travel = context.get("team_travel") or {}
    if team_travel:
        travel_a = float(team_travel.get(team_a.name, 20))
        travel_b = float(team_travel.get(team_b.name, 20))
        if abs(travel_a - travel_b) >= 8:
            favored = team_a if travel_a < travel_b else team_b
            drivers.append({"label": "Lower travel load", "favored_team": favored.name, "impact": round(min(100.0, 35 + abs(travel_a - travel_b)), 1)})
    else:
        travel = float(context.get("travel", 20))
        if travel >= 45:
            favored = team_a if team_a.fitness + team_a.bench >= team_b.fitness + team_b.bench else team_b
            drivers.append({"label": "Travel resilience", "favored_team": favored.name, "impact": round(min(100.0, travel), 1)})

    team_fatigue = context.get("team_fatigue") or {}
    if team_fatigue:
        fatigue_a = float(team_fatigue.get(team_a.name, 20))
        fatigue_b = float(team_fatigue.get(team_b.name, 20))
        if abs(fatigue_a - fatigue_b) >= 8:
            favored = team_a if fatigue_a < fatigue_b else team_b
            drivers.append({"label": "Lower fatigue load", "favored_team": favored.name, "impact": round(min(100.0, 35 + abs(fatigue_a - fatigue_b)), 1)})
    else:
        fatigue = float(context.get("fatigue", 20))
        if fatigue >= 45:
            favored = team_a if team_a.injury_resilience + team_a.bench >= team_b.injury_resilience + team_b.bench else team_b
            drivers.append({"label": "Fatigue depth", "favored_team": favored.name, "impact": round(min(100.0, fatigue), 1)})

    fan_edges = context.get("fan_edges") or {}
    if fan_edges and abs(float(fan_edges.get(team_a.name, 0)) - float(fan_edges.get(team_b.name, 0))) >= 0.4:
        favored = team_a if float(fan_edges.get(team_a.name, 0)) > float(fan_edges.get(team_b.name, 0)) else team_b
        drivers.append({"label": "Crowd support", "favored_team": favored.name, "impact": round(min(100.0, 45 + abs(float(fan_edges.get(favored.name, 0))) * 25), 1)})
    home_advantage = float(context.get("home_advantage", 1.0))
    if home_advantage and (team_a.host or team_b.host) and not fan_edges:
        favored = team_a if team_a.host else team_b
        drivers.append({"label": "Host advantage", "favored_team": favored.name, "impact": round(50 * home_advantage, 1)})

    advanced = advanced_signal_pair(team_a, team_b, context)
    signals_a = {signal["label"]: signal for signal in advanced["team_a"].get("signals", [])}
    signals_b = {signal["label"]: signal for signal in advanced["team_b"].get("signals", [])}
    for label in (
        "Availability",
        "Confirmed XI",
        "Market probability",
        "Tactical matchup",
        "Set pieces",
        "Post-shot GK",
        "360 freeze-frame",
        "Referee tendencies",
        "Live Bayesian update",
    ):
        delta_a = float(signals_a.get(label, {}).get("xg_delta", 0.0))
        delta_b = float(signals_b.get(label, {}).get("xg_delta", 0.0))
        if abs(delta_a - delta_b) >= 0.018:
            favored = team_a if delta_a > delta_b else team_b
            drivers.append(
                {
                    "label": label,
                    "favored_team": favored.name,
                    "impact": round(min(100.0, 30 + abs(delta_a - delta_b) * 700), 1),
                }
            )

    return sorted(drivers, key=lambda item: item["impact"], reverse=True)[:6]


def shap_driver_payload(team_a: Team, team_b: Team, bundle: Any, aggregates: dict[str, float], top_n: int = 6) -> dict[str, Any]:
    if not bundle:
        return {"available": False, "reason": "baseline-model", "drivers": []}
    try:
        import shap  # type: ignore
        import numpy as np
    except ModuleNotFoundError:
        return {"available": False, "reason": "install-shap", "drivers": []}

    model = bundle.model.get("classifier")
    columns = bundle.model.get("feature_columns", [])
    if model is None or not columns:
        return {"available": False, "reason": "model-metadata-missing", "drivers": []}

    try:
        row = model_features(team_a, team_b, bundle)
        values = np.array([[row[column] for column in columns]])
        classes = list(model.classes_)
        favorite_key = max(aggregates, key=aggregates.get)
        class_idx = classes.index(favorite_key) if favorite_key in classes else 0
        explanation = shap.TreeExplainer(model).shap_values(values)
        if isinstance(explanation, list):
            shap_values = explanation[class_idx][0]
        elif getattr(explanation, "ndim", 0) == 3:
            shap_values = explanation[0, :, class_idx]
        else:
            shap_values = explanation[0]
    except Exception as exc:  # SHAP can fail on version/model-shape mismatches.
        return {"available": False, "reason": str(exc), "drivers": []}

    raw = []
    for column, value in zip(columns, shap_values):
        score = float(value)
        if abs(score) < 0.0001:
            continue
        raw.append(
            {
                "label": column.replace("_", " ").title(),
                "feature": column,
                "favored_team": team_a.name if score > 0 else team_b.name,
                "raw_value": round(float(row[column]), 3),
                "score": score,
            }
        )
    selected = sorted(raw, key=lambda item: abs(item["score"]), reverse=True)[:top_n]
    max_score = max((abs(item["score"]) for item in selected), default=1.0)
    return {
        "available": True,
        "target": favorite_key,
        "drivers": [
            {
                **item,
                "impact": round(100 * abs(item["score"]) / max_score, 1),
            }
            for item in selected
        ],
    }


def model_metadata_payload(bundle: Any) -> dict[str, Any]:
    if not bundle:
        return {"type": "poisson_baseline"}
    model = bundle.model
    metrics = model.get("metrics", {})
    return {
        "type": model.get("classifier_type", "random_forest"),
        "training_rows": model.get("training_rows"),
        "trained_through": model.get("trained_through"),
        "recency_half_life_years": model.get("recency_half_life_years"),
        "probability_shrinkage": model.get("probability_shrinkage"),
        "validation_strategy": model.get("validation_strategy"),
        "leakage_safe_features": model.get("leakage_safe_features", False),
        "components": model.get("ensemble_components", ["random_forest"]),
        "holdout_accuracy": round(metrics.get("holdout_accuracy", 0), 3) if metrics else None,
        "holdout_log_loss": round(metrics.get("holdout_log_loss", 0), 3) if metrics else None,
        "holdout_brier_score": round(metrics.get("holdout_brier_score", 0), 3) if metrics else None,
    }


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text.replace("+", ""))
    except ValueError:
        return None


def decimal_odds_from_row(row: dict[str, str]) -> float | None:
    decimal = safe_float(row.get("decimal_odds"))
    if decimal and decimal > 1:
        return decimal

    american = safe_float(row.get("american_odds"))
    if american is None or american == 0:
        return None
    if american > 0:
        return 1 + (american / 100)
    return 1 + (100 / abs(american))


def load_bookmaker_odds() -> list[dict[str, Any]]:
    if not ODDS_PATH.exists():
        return []

    rows = []
    with ODDS_PATH.open(newline="", encoding="utf-8") as handle:
        for idx, row in enumerate(csv.DictReader(handle), start=1):
            decimal = decimal_odds_from_row(row)
            if not decimal:
                continue
            market = (row.get("market") or "").strip().lower()
            bookmaker = (row.get("bookmaker") or "market").strip()
            team_a = (row.get("team_a") or "").strip()
            team_b = (row.get("team_b") or "").strip()
            event = (row.get("event") or f"{team_a} vs {team_b}").strip()
            selection = (row.get("selection") or "").strip()
            rows.append(
                {
                    "row": idx,
                    "market": market,
                    "event": event,
                    "team_a": team_a,
                    "team_b": team_b,
                    "selection": selection,
                    "bookmaker": bookmaker,
                    "decimal_odds": decimal,
                    "american_odds": (row.get("american_odds") or "").strip(),
                    "start_time": (row.get("start_time") or "").strip(),
                    "notes": (row.get("notes") or "").strip(),
                    "implied_probability": 1 / decimal,
                }
            )
    return rows


def odds_market_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        row["bookmaker"].lower(),
        row["market"],
        row["event"].lower(),
        row["team_a"].lower(),
        row["team_b"].lower(),
    )


def selection_probability_key(selection: str, team_a: str, team_b: str) -> str | None:
    normalized = selection.strip().lower()
    if normalized in {"draw", "tie", "x"}:
        return "draw"
    if normalized == team_a.strip().lower() or normalized in {"team_a", "home", "1"}:
        return "team_a_win"
    if normalized == team_b.strip().lower() or normalized in {"team_b", "away", "2"}:
        return "team_b_win"
    return None


def normalize_name_key(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", "and")
    return "".join(char for char in text if char.isalnum())


ODDS_TEAM_ALIASES = {
    "usa": "USA",
    "us": "USA",
    "unitedstates": "USA",
    "unitedstatesofamerica": "USA",
    "iran": "IR Iran",
    "iri": "IR Iran",
    "southkorea": "Korea Republic",
    "korearepublic": "Korea Republic",
    "republicofkorea": "Korea Republic",
    "turkey": "Turkiye",
    "turkiye": "Turkiye",
    "cotedivoire": "Cote d'Ivoire",
    "ivorycoast": "Cote d'Ivoire",
    "drcongo": "Congo DR",
    "congodr": "Congo DR",
    "democraticrepublicofcongo": "Congo DR",
    "capeverde": "Cabo Verde",
    "cabo verde": "Cabo Verde",
    "curacao": "Curacao",
    "czechrepublic": "Czechia",
    "cz": "Czechia",
    "england": "England",
    "scotland": "Scotland",
}


def canonical_team_name(name: str | None, teams: dict[str, Team]) -> str | None:
    if not name:
        return None
    key = normalize_name_key(name)
    if key in {"draw", "tie", "x"}:
        return "Draw"
    alias = ODDS_TEAM_ALIASES.get(key)
    if alias and alias in teams:
        return alias
    by_key = {normalize_name_key(team_name): team_name for team_name in teams}
    return by_key.get(key)


def odds_api_price_fields(price: Any) -> tuple[str, str]:
    value = safe_float(price)
    if value is None or value == 0:
        return "", ""
    if 1.01 < value < 20:
        if value >= 2:
            american = f"+{int(round((value - 1) * 100))}"
        else:
            american = str(int(round(-100 / (value - 1))))
        return american, f"{value:.3f}"
    american = int(round(value))
    return (f"+{american}" if american > 0 else str(american)), ""


def odds_api_events_to_rows(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    teams = load_teams()
    output = []
    skipped = []
    fetched_at = datetime.now(timezone.utc).isoformat()

    for event in events:
        team_a = canonical_team_name(event.get("home_team"), teams)
        team_b = canonical_team_name(event.get("away_team"), teams)
        if not team_a or not team_b:
            skipped.append(
                {
                    "home_team": event.get("home_team"),
                    "away_team": event.get("away_team"),
                    "reason": "not in current World Cup team list",
                }
            )
            continue

        for bookmaker in event.get("bookmakers") or []:
            bookmaker_name = bookmaker.get("title") or bookmaker.get("key") or "The Odds API"
            for market in bookmaker.get("markets") or []:
                if market.get("key") not in {"h2h", "h2h_lay"}:
                    continue
                for outcome in market.get("outcomes") or []:
                    selection = canonical_team_name(outcome.get("name"), teams)
                    if not selection:
                        continue
                    american, decimal = odds_api_price_fields(outcome.get("price"))
                    if not american and not decimal:
                        continue
                    output.append(
                        {
                            "market": "match_winner",
                            "event": f"{team_a} vs {team_b}",
                            "team_a": team_a,
                            "team_b": team_b,
                            "selection": selection,
                            "american_odds": american,
                            "decimal_odds": decimal,
                            "bookmaker": bookmaker_name,
                            "start_time": event.get("commence_time") or "",
                            "notes": f"The Odds API snapshot {fetched_at}",
                        }
                    )
    return output, skipped


def write_bookmaker_odds(rows: list[dict[str, Any]]) -> None:
    ODDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ODDS_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=BOOKMAKER_ODDS_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def refresh_the_odds_api_snapshot(request: OddsSnapshotRequest) -> dict[str, Any]:
    load_dotenv(ROOT / ".env", override=False)
    api_key = os.getenv("THE_ODDS_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "source": "the-odds-api",
            "message": "Set THE_ODDS_API_KEY in .env to pull a one-time bookmaker odds snapshot.",
            "rows_written": 0,
            "events_seen": 0,
            "skipped_events": [],
        }

    sport_key = request.sport_key or os.getenv("THE_ODDS_SPORT", "soccer_fifa_world_cup")
    regions = request.regions or os.getenv("THE_ODDS_REGIONS", "us,uk,eu")
    bookmakers = request.bookmakers or os.getenv("THE_ODDS_BOOKMAKERS", "")
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": "h2h",
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    if bookmakers:
        params["bookmakers"] = bookmakers

    try:
        response = requests.get(f"{ODDS_API_HOST}/v4/sports/{sport_key}/odds/", params=params, timeout=12)
        response.raise_for_status()
    except requests.RequestException as exc:
        return {
            "ok": False,
            "source": "the-odds-api",
            "message": f"The Odds API request failed: {exc}",
            "rows_written": 0,
            "events_seen": 0,
            "skipped_events": [],
        }

    events = response.json()
    if not isinstance(events, list):
        return {
            "ok": False,
            "source": "the-odds-api",
            "message": "The Odds API returned an unexpected response shape.",
            "rows_written": 0,
            "events_seen": 0,
            "skipped_events": [],
        }

    rows, skipped = odds_api_events_to_rows(events)
    if not rows:
        return {
            "ok": False,
            "source": "the-odds-api",
            "message": "Fetched odds, but none matched the current World Cup team list. Existing local odds were left unchanged.",
            "rows_written": 0,
            "events_seen": len(events),
            "skipped_events": skipped[:12],
            "quota": {
                "remaining": response.headers.get("x-requests-remaining"),
                "used": response.headers.get("x-requests-used"),
                "last": response.headers.get("x-requests-last"),
            },
        }

    write_bookmaker_odds(rows)
    return {
        "ok": True,
        "source": "the-odds-api",
        "sport_key": sport_key,
        "regions": regions,
        "rows_written": len(rows),
        "events_seen": len(events),
        "skipped_events": skipped[:12],
        "quota": {
            "remaining": response.headers.get("x-requests-remaining"),
            "used": response.headers.get("x-requests-used"),
            "last": response.headers.get("x-requests-last"),
        },
        "message": f"Wrote {len(rows)} match-winner odds rows from The Odds API.",
    }


def betting_market_probability(
    row: dict[str, Any],
    teams: dict[str, Team],
    bundle: Any,
    context: dict[str, Any],
    match_cache: dict[tuple[str, str], dict[str, float]],
    champion_probabilities: dict[str, float],
) -> float | None:
    market = row["market"]
    if market in {"champion", "outright", "winner"}:
        return champion_probabilities.get(row["selection"])

    if market not in {"match_winner", "moneyline", "1x2"}:
        return None
    if row["team_a"] not in teams or row["team_b"] not in teams:
        return None

    probability_key = selection_probability_key(row["selection"], row["team_a"], row["team_b"])
    if not probability_key:
        return None

    match_key = (row["team_a"], row["team_b"])
    if match_key not in match_cache:
        team_a = teams[row["team_a"]]
        team_b = teams[row["team_b"]]
        fixture_context = automatic_fixture_context(context, fixture_for_team_pair(team_a.name, team_b.name), team_a, team_b, {})
        match_cache[match_key] = blended_context_probabilities(team_a, team_b, bundle, fixture_context)
    return match_cache[match_key][probability_key]


def champion_probability_map(request: BettingEdgesRequest, context: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, float]:
    if not any(row["market"] in {"champion", "outright", "winner"} for row in rows):
        return {}
    odds = run_many(request.sims, request.seed, request.use_model, context)["odds"]
    return {row["name"]: row["win_pct"] / 100 for row in odds}


def recommended_stake(bankroll: float, decimal_odds: float, probability: float, kelly_fraction: float, max_stake_pct: float) -> dict[str, float]:
    profit_multiple = decimal_odds - 1
    full_kelly = 0.0
    if profit_multiple > 0:
        full_kelly = max(0.0, ((probability * decimal_odds) - 1) / profit_multiple)
    stake_pct = min(full_kelly * kelly_fraction * 100, max_stake_pct)
    stake = bankroll * stake_pct / 100
    return {
        "full_kelly_pct": round(full_kelly * 100, 2),
        "stake_pct": round(stake_pct, 2),
        "stake": round(stake, 2),
    }


@app.post("/api/refresh-odds-snapshot")
def api_refresh_odds_snapshot(request: OddsSnapshotRequest | None = None) -> dict[str, Any]:
    return refresh_the_odds_api_snapshot(request or OddsSnapshotRequest())


@app.post("/api/betting-edges")
def api_betting_edges(request: BettingEdgesRequest) -> dict[str, Any]:
    rows = load_bookmaker_odds()
    if not rows:
        return {
            "ok": False,
            "source": str(ODDS_PATH),
            "edges": [],
            "message": "Add odds to data/bookmaker_odds.csv to compare market prices against the model.",
        }

    context = request_context(request)
    teams = load_teams()
    bundle = load_cached_model() if request.use_model else None
    champion_probs = champion_probability_map(request, context, rows)
    match_cache: dict[tuple[str, str], dict[str, float]] = {}
    overround_by_market: dict[tuple[str, str, str, str, str], float] = defaultdict(float)
    for row in rows:
        overround_by_market[odds_market_key(row)] += row["implied_probability"]

    edges = []
    skipped = 0
    for row in rows:
        model_probability = betting_market_probability(row, teams, bundle, context, match_cache, champion_probs)
        if model_probability is None:
            skipped += 1
            continue

        overround = max(overround_by_market[odds_market_key(row)], row["implied_probability"])
        no_vig_probability = row["implied_probability"] / overround
        edge = model_probability - no_vig_probability
        ev = (model_probability * row["decimal_odds"]) - 1
        stake = recommended_stake(
            request.bankroll,
            row["decimal_odds"],
            model_probability,
            request.kelly_fraction,
            request.max_stake_pct,
        )
        if edge * 100 < request.min_edge_pct:
            continue

        if ev > 0.08 and edge > 0.04:
            grade = "Strong watchlist"
        elif ev > 0 and edge > 0:
            grade = "Small edge"
        else:
            grade = "No bet"

        edges.append(
            {
                "market": row["market"],
                "event": row["event"],
                "team_a": row["team_a"],
                "team_b": row["team_b"],
                "selection": row["selection"],
                "bookmaker": row["bookmaker"],
                "decimal_odds": round(row["decimal_odds"], 3),
                "american_odds": row["american_odds"],
                "model_probability": round(model_probability * 100, 1),
                "market_implied_probability": round(row["implied_probability"] * 100, 1),
                "no_vig_probability": round(no_vig_probability * 100, 1),
                "overround": round(overround * 100, 1),
                "edge_pct": round(edge * 100, 1),
                "expected_value_pct": round(ev * 100, 1),
                "stake": stake["stake"] if ev > 0 and edge > 0 else 0.0,
                "stake_pct": stake["stake_pct"] if ev > 0 and edge > 0 else 0.0,
                "full_kelly_pct": stake["full_kelly_pct"],
                "grade": grade,
                "notes": row["notes"],
            }
        )

    return {
        "ok": True,
        "source": str(ODDS_PATH),
        "bankroll": request.bankroll,
        "settings": {
            "kelly_fraction": request.kelly_fraction,
            "max_stake_pct": request.max_stake_pct,
            "sims": request.sims,
        },
        "edges": sorted(edges, key=lambda row: (row["expected_value_pct"], row["edge_pct"]), reverse=True),
        "skipped_rows": skipped,
        "message": "Educational EV screen only. Odds move, models miss, and no wager is guaranteed.",
    }


@app.post("/api/live-state/match")
def api_live_state_match(update: LiveMatchUpdate) -> dict[str, Any]:
    teams = load_teams()
    if update.team_a not in teams or update.team_b not in teams:
        raise HTTPException(status_code=404, detail="Unknown team")
    if update.team_a == update.team_b:
        raise HTTPException(status_code=400, detail="Teams must be different")

    state = load_live_state()
    state["source"] = "manual"
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    match = {
        "team_a": update.team_a,
        "team_b": update.team_b,
        "team_a_score": update.team_a_score,
        "team_b_score": update.team_b_score,
        "updated_at": state["updated_at"],
    }
    completed = [
        current
        for current in state.get("completed_matches", [])
        if frozenset((current.get("team_a"), current.get("team_b"))) != frozenset((update.team_a, update.team_b))
    ]
    completed.append(match)
    state["completed_matches"] = completed
    save_live_state(state)
    sync_live_team_state_from_results(state)
    return {"ok": True, "live_state": state, "live_team_state_source": str(LIVE_TEAM_STATE_PATH)}


@app.post("/api/live-state/elimination")
def api_live_state_elimination(update: EliminationUpdate) -> dict[str, Any]:
    teams = load_teams()
    if update.team not in teams:
        raise HTTPException(status_code=404, detail="Unknown team")
    state = load_live_state()
    eliminated = set(state.get("eliminated_teams", []))
    if update.eliminated:
        eliminated.add(update.team)
    else:
        eliminated.discard(update.team)
    state["source"] = "manual"
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["eliminated_teams"] = sorted(eliminated)
    save_live_state(state)
    return {"ok": True, "live_state": state}


def provider_get(base_url: str, path: str, api_key: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str | None]:
    try:
        response = requests.get(
            f"{base_url.rstrip('/')}/{path.lstrip('/')}",
            headers={"Authorization": api_key},
            params=params or {},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return None, str(exc)
    return response.json(), None


def object_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("name", "full_name", "display_name", "country", "team_name"):
            if value.get(key):
                return str(value[key])
    return None


def first_present(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    return None


def match_team_names(row: dict[str, Any]) -> tuple[str | None, str | None]:
    team_a = object_name(first_present(row, ("home_team", "team_a", "home", "team1", "homeTeam")))
    team_b = object_name(first_present(row, ("away_team", "team_b", "away", "team2", "awayTeam")))
    return team_a, team_b


def normalize_completed_matches(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    completed = []
    for row in rows:
        status = str(first_present(row, ("status", "match_status", "state")) or "").lower()
        is_finished = any(token in status for token in ("finished", "complete", "final", "ft"))
        team_a, team_b = match_team_names(row)
        score_a = first_present(row, ("home_score", "team_a_score", "home_goals", "score_home"))
        score_b = first_present(row, ("away_score", "team_b_score", "away_goals", "score_away"))
        if not is_finished or not team_a or not team_b or score_a is None or score_b is None:
            continue
        completed.append(
            {
                "team_a": team_a,
                "team_b": team_b,
                "team_a_score": int(score_a),
                "team_b_score": int(score_b),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "provider_match_id": row.get("id"),
            }
        )
    return completed


def write_provider_odds(match_rows: list[dict[str, Any]], odds_rows: list[dict[str, Any]], futures_rows: list[dict[str, Any]]) -> int:
    if not odds_rows and not futures_rows:
        return 0

    match_by_id = {row.get("id"): row for row in match_rows if row.get("id") is not None}
    output = []
    for odd in odds_rows:
        match = match_by_id.get(odd.get("match_id"), {})
        team_a, team_b = match_team_names(match)
        if not team_a or not team_b:
            continue
        event = f"{team_a} vs {team_b}"
        vendor = str(odd.get("vendor") or odd.get("bookmaker") or "provider")
        updated_at = str(odd.get("updated_at") or "")
        for selection, key in (
            (team_a, "moneyline_home_odds"),
            ("Draw", "moneyline_draw_odds"),
            (team_b, "moneyline_away_odds"),
        ):
            if odd.get(key) is None:
                continue
            output.append(
                {
                    "market": "match_winner",
                    "event": event,
                    "team_a": team_a,
                    "team_b": team_b,
                    "selection": selection,
                    "american_odds": odd[key],
                    "decimal_odds": "",
                    "bookmaker": vendor,
                    "start_time": str(match.get("start_time") or match.get("date") or ""),
                    "notes": f"BALLDONTLIE updated {updated_at}",
                }
            )

    for future in futures_rows:
        market_type = str(future.get("market_type") or "").lower()
        if market_type not in {"outright", "champion", "winner"}:
            continue
        selection = object_name(future.get("subject")) or object_name(future.get("team")) or str(future.get("selection") or "")
        if not selection:
            continue
        output.append(
            {
                "market": "champion",
                "event": "World Cup 2026",
                "team_a": "",
                "team_b": "",
                "selection": selection,
                "american_odds": future.get("american_odds") or "",
                "decimal_odds": future.get("decimal_odds") or "",
                "bookmaker": future.get("vendor") or future.get("bookmaker") or "provider",
                "start_time": "",
                "notes": f"BALLDONTLIE {future.get('market_name') or 'futures'} updated {future.get('updated_at') or ''}",
            }
        )

    if not output:
        return 0

    with ODDS_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=BOOKMAKER_ODDS_FIELDNAMES,
        )
        writer.writeheader()
        writer.writerows(output)
    return len(output)


@app.post("/api/refresh-live-data")
def api_refresh_live_data() -> dict[str, Any]:
    api_key = os.getenv("BALLDONTLIE_API_KEY")
    base_url = os.getenv("WORLD_CUP_API_BASE_URL", "https://api.balldontlie.io/fifa/worldcup/v1")
    state = load_live_state()
    state["updated_at"] = datetime.now(timezone.utc).isoformat()

    if not api_key:
        state["source"] = "manual-no-api-key"
        save_live_state(state)
        return {
            "ok": False,
            "message": "Set BALLDONTLIE_API_KEY in .env to enable live refresh.",
            "live_state": state,
        }

    match_payload, match_error = provider_get(base_url, "matches", api_key, {"seasons[]": 2026, "per_page": 100})
    odds_payload, odds_error = provider_get(base_url, "odds", api_key, {"seasons[]": 2026, "per_page": 100})
    futures_payload, futures_error = provider_get(base_url, "odds/futures", api_key, {"seasons[]": 2026})
    if match_error and odds_error and futures_error:
        state["source"] = "api-refresh-failed"
        save_live_state(state)
        return {"ok": False, "message": match_error, "live_state": state}

    match_rows = match_payload.get("data", []) if isinstance(match_payload, dict) else []
    odds_rows = odds_payload.get("data", []) if isinstance(odds_payload, dict) else []
    futures_rows = futures_payload.get("data", []) if isinstance(futures_payload, dict) else []
    completed_matches = normalize_completed_matches(match_rows)
    if completed_matches:
        state["completed_matches"] = completed_matches
    state["source"] = base_url
    state["raw_match_count"] = len(match_rows)
    state["raw_odds_count"] = len(odds_rows)
    state["raw_futures_count"] = len(futures_rows)
    state["provider_errors"] = {
        "matches": match_error,
        "odds": odds_error,
        "futures": futures_error,
    }
    written_odds = write_provider_odds(match_rows, odds_rows, futures_rows)
    save_live_state(state)
    sync_live_team_state_from_results(state)
    return {
        "ok": True,
        "message": f"Fetched BALLDONTLIE data. Completed matches: {len(completed_matches)}. Odds rows written: {written_odds}.",
        "live_state": state,
        "live_team_state_source": str(LIVE_TEAM_STATE_PATH),
    }


@app.post("/api/ai/refresh-live")
def api_ai_refresh_live() -> dict[str, Any]:
    refresh = api_refresh_live_data()
    return {"refresh": refresh, "live_board": live_match_board(load_live_state())}
