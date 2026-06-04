from __future__ import annotations

import json
import math
import os
import random
import sys
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

load_dotenv(ROOT / ".env")

STATIC_DIR = ROOT / "app" / "static"
LIVE_STATE_PATH = ROOT / "data" / "live_state.json"
PLAYERS_PATH = ROOT / "data" / "player_candidates.csv"
ODDS_PATH = ROOT / "data" / "bookmaker_odds.csv"
VENUES_PATH = ROOT / "data" / "venues.csv"

app = FastAPI(title="World Cup 2026 Predictor")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

MODEL_CACHE: dict[str, Any] = {"mtime": None, "bundle": None}

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
    ("Final", [(103, 101, 102)]),
]

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


def request_context(
    request: SimulationRequest | MatchRequest | BettingEdgesRequest | IntelligenceRequest,
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


def weather_context_for_venue(venue_name: str) -> dict[str, Any]:
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
        return {
            "weather": "altitude" if venue["altitude_m"] >= 1400 else "normal",
            "weather_source": "open-meteo-failed",
            "weather_error": str(exc),
            "venue_weather": {"venue": venue},
        }

    payload = response.json()
    current = payload.get("current", {})
    weather = classify_weather(current, venue)
    return {
        "weather": weather,
        "weather_source": "open-meteo",
        "venue_weather": {
            "venue": venue,
            "current": current,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
    }


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


def load_player_candidates() -> dict[str, list[dict[str, Any]]]:
    players: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not PLAYERS_PATH.exists():
        return players

    with PLAYERS_PATH.open(encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            team, player, position, scoring_weight, starter, penalty_taker = line.rstrip("\n").split(",")
            players[team].append(
                {
                    "team": team,
                    "player": player,
                    "position": position,
                    "scoring_weight": float(scoring_weight),
                    "starter": starter == "1",
                    "penalty_taker": penalty_taker == "1",
                    "flag": FLAG_CODE_BY_TEAM.get(team, "un").upper(),
                    "flag_code": FLAG_CODE_BY_TEAM.get(team, "un"),
                    "flag_image": f"https://flagcdn.com/w80/{FLAG_CODE_BY_TEAM.get(team, 'un')}.png",
                }
            )
    return players


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

    travel = float(context.get("travel", 20))
    fatigue = float(context.get("fatigue", 20))
    home_advantage = float(context.get("home_advantage", 1.0))
    resilience = ((team.fitness + team.bench + team.injury_resilience) - 230) / 100
    weather_resilience = (team.fitness - opponent.fitness) / 500
    set_piece_edge = (team.set_piece_attack - opponent.set_piece_defense) / 100
    transition_edge = (team.transition_speed - opponent.pressing_intensity) / 100
    tactical_edge = (team.tactical_flexibility - opponent.tactical_flexibility) / 100
    discipline_edge = (team.discipline - opponent.discipline) / 100
    pressure_edge = (team.big_match_composure - opponent.big_match_composure) / 100
    pressing_heat_drag = 0.0
    if weather == "heat":
        pressing_heat_drag = max(0.0, (team.pressing_intensity - 80) / 100) * 0.08
    weather_set_piece_boost = 0.05 * set_piece_edge if weather in {"rain", "cold"} else 0.0
    fatigue_factor = 1 - (fatigue * 0.0018) + (resilience * fatigue * 0.0009)
    travel_factor = 1 - (travel * 0.0012) + (team.fitness - 80) * 0.001
    host_boost = 0.10 * home_advantage if team.host else 0.0

    adjusted = base * weather_factor * fatigue_factor * travel_factor
    adjusted += (
        weather_resilience
        + weather_set_piece_boost
        + (0.06 * transition_edge)
        + (0.04 * tactical_edge)
        + (0.03 * discipline_edge)
        + (0.05 * pressure_edge if knockout else 0.0)
        + host_boost
        - pressing_heat_drag
    )
    return max(0.12, min(4.2, adjusted))


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
    lambda_a = context_expected_goals(team_a, team_b, bundle, context, knockout)
    lambda_b = context_expected_goals(team_b, team_a, bundle, context, knockout)
    context_probs = poisson_result_probabilities(lambda_a, lambda_b)
    if not bundle:
        return context_probs

    rf_probs = match_probabilities(team_a, team_b, bundle=bundle)
    return {
        key: (0.68 * rf_probs[key]) + (0.32 * context_probs[key])
        for key in context_probs
    }


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
    lambda_a = context_expected_goals(team_a, team_b, bundle, context, knockout)
    lambda_b = context_expected_goals(team_b, team_a, bundle, context, knockout)
    probabilities = blended_context_probabilities(team_a, team_b, bundle, context, knockout)
    return align_score_to_outcome(poisson(lambda_a), poisson(lambda_b), sample_outcome(probabilities))


def play_group_detail(
    group: str,
    teams: list[Team],
    eliminated: set[str],
    completed: dict[frozenset[str], dict[str, Any]],
    bundle: Any,
    context: dict[str, Any],
) -> tuple[list[Standing], list[dict[str, Any]]]:
    table = {team.name: Standing(team) for team in teams}
    matches = []
    for idx, team_a in enumerate(teams):
        for team_b in teams[idx + 1 :]:
            goals_a, goals_b, locked = resolve_match_score(team_a, team_b, completed, bundle, context)
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
            matches.append(match_payload(team_a, team_b, goals_a, goals_b, locked))

    ranked = sorted(
        table.values(),
        key=lambda standing: (
            standing.team.name not in eliminated,
            *standing.sort_key(),
        ),
        reverse=True,
    )
    return ranked, matches


def match_payload(team_a: Team, team_b: Team, goals_a: int, goals_b: int, locked: bool = False) -> dict[str, Any]:
    if goals_a > goals_b:
        winner = team_a.name
    elif goals_b > goals_a:
        winner = team_b.name
    else:
        winner = None
    return {
        "team_a": team_payload(team_a),
        "team_b": team_payload(team_b),
        "score_a": goals_a,
        "score_b": goals_b,
        "winner": winner,
        "locked": locked,
    }


def standing_payload(row: Standing) -> dict[str, Any]:
    return {
        "team": team_payload(row.team),
        "points": row.points,
        "goals_for": row.goals_for,
        "goals_against": row.goals_against,
        "goal_difference": row.goal_difference,
        "wins": row.wins,
    }


def play_knockout_match(match_id: int, team_a: Team, team_b: Team, bundle: Any, context: dict[str, Any], venue: str | None = None) -> dict[str, Any]:
    goals_a, goals_b = play_context_match(team_a, team_b, bundle, context, knockout=True)
    if goals_a == goals_b:
        penalty_edge = ((team_a.penalty_strength + team_a.big_match_composure) - (team_b.penalty_strength + team_b.big_match_composure)) / 100
        probability_a = 1 / (1 + pow(2.718281828, -((team_a.strength - team_b.strength) * 1.8 + penalty_edge)))
        winner = team_a if random.random() < probability_a else team_b
        penalty_winner = winner.name
    else:
        winner = team_a if goals_a > goals_b else team_b
        penalty_winner = None
    match = match_payload(team_a, team_b, goals_a, goals_b)
    match["id"] = match_id
    match["winner"] = winner.name
    match["winner_team"] = team_payload(winner)
    match["penalty_winner"] = penalty_winner
    match["venue"] = venue
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
) -> dict[str, Any]:
    third_available = dict(third_place_candidates(group_tables, eliminated))
    third_slots = [slot["b"][1] for slot in R32_SLOTS if slot["b"][0] == "third"]
    matches_by_id: dict[int, dict[str, Any]] = {}
    winners_by_id: dict[int, Team] = {}
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
        match = play_knockout_match(slot["id"], team_a, team_b, bundle, context, slot["venue"])
        matches_by_id[slot["id"]] = match
        winners_by_id[slot["id"]] = team_a if match["winner"] == team_a.name else team_b
        r32_matches.append(match)

    rounds = [{"name": "Round of 32", "matches": r32_matches}]
    for round_name, match_specs in KNOCKOUT_PATH:
        round_matches = []
        for match_id, source_a, source_b in match_specs:
            team_a = winners_by_id[source_a]
            team_b = winners_by_id[source_b]
            match = play_knockout_match(match_id, team_a, team_b, bundle, context)
            matches_by_id[match_id] = match
            winners_by_id[match_id] = team_a if match["winner"] == team_a.name else team_b
            round_matches.append(match)
        rounds.append({"name": round_name, "matches": round_matches})

    return {"rounds": rounds, "champion": matches_by_id[103]["winner_team"], "format": "FIFA match-number bracket"}


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

    group_tables = {}
    group_matches = {}
    for group, group_teams in groups.items():
        table, matches = play_group_detail(group, group_teams, eliminated, completed, bundle, context)
        group_tables[group] = table
        group_matches[group] = matches

    if sum(1 for table in group_tables.values() for row in table[:3] if row.team.name not in eliminated) < 32:
        raise HTTPException(status_code=409, detail="Not enough active teams remain to simulate.")
    knockout = play_official_knockout_detail(group_tables, bundle, context, eliminated)
    return {
        "model": "Random Forest" if bundle else "Poisson baseline",
        "context": context,
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
            key = stage_key_by_name[round_data["name"]]
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
        "model": "Random Forest" if bundle else "Poisson baseline",
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


@app.get("/api/venue-weather")
def api_venue_weather(venue: str) -> dict[str, Any]:
    return venue_weather_payload(venue)


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
        "suggested_followups": intelligence_followups(entities),
        "disclaimer": "Forecasts are probabilistic model outputs, not facts or guaranteed outcomes.",
    }


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    model_exists = MODEL_PATH.exists()
    return {
        "model_exists": model_exists,
        "model_path": str(MODEL_PATH),
        "live_state": load_live_state(),
        "intelligence": get_intelligence_index(ROOT).status(),
    }


@app.get("/api/live-state")
def api_live_state() -> dict[str, Any]:
    return {"live_state": load_live_state()}


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
    context = request_context(request)
    lambda_a = context_expected_goals(team_a, team_b, bundle, context)
    lambda_b = context_expected_goals(team_b, team_a, bundle, context)
    probabilities = blended_context_probabilities(team_a, team_b, bundle, context)
    score_distribution = scorelines_from_lambdas(lambda_a, lambda_b)
    scores = score_distribution[: request.top_scores]
    score_matrix = score_matrix_payload(lambda_a, lambda_b, max_goals=6)
    score_aggregates = score_matrix["aggregates"]
    return {
        "team_a": team_payload(team_a),
        "team_b": team_payload(team_b),
        "expected_score": {"team_a": round(lambda_a, 2), "team_b": round(lambda_b, 2)},
        "probabilities": {key: round(value * 100, 1) for key, value in probabilities.items()},
        "score_aggregate_probabilities": score_aggregates,
        "score_matrix": score_matrix["cells"],
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

    travel = float(context.get("travel", 20))
    if travel >= 45:
        favored = team_a if team_a.fitness + team_a.bench >= team_b.fitness + team_b.bench else team_b
        drivers.append({"label": "Travel resilience", "favored_team": favored.name, "impact": round(min(100.0, travel), 1)})

    fatigue = float(context.get("fatigue", 20))
    if fatigue >= 45:
        favored = team_a if team_a.injury_resilience + team_a.bench >= team_b.injury_resilience + team_b.bench else team_b
        drivers.append({"label": "Fatigue depth", "favored_team": favored.name, "impact": round(min(100.0, fatigue), 1)})

    home_advantage = float(context.get("home_advantage", 1.0))
    if home_advantage and (team_a.host or team_b.host):
        favored = team_a if team_a.host else team_b
        drivers.append({"label": "Host advantage", "favored_team": favored.name, "impact": round(50 * home_advantage, 1)})

    return sorted(drivers, key=lambda item: item["impact"], reverse=True)[:4]


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
        "holdout_accuracy": round(metrics.get("holdout_accuracy", 0), 3) if metrics else None,
        "holdout_log_loss": round(metrics.get("holdout_log_loss", 0), 3) if metrics else None,
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
        match_cache[match_key] = blended_context_probabilities(team_a, team_b, bundle, context)
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
    return {"ok": True, "live_state": state}


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
            fieldnames=["market", "event", "team_a", "team_b", "selection", "american_odds", "decimal_odds", "bookmaker", "start_time", "notes"],
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
    return {
        "ok": True,
        "message": f"Fetched BALLDONTLIE data. Completed matches: {len(completed_matches)}. Odds rows written: {written_odds}.",
        "live_state": state,
    }
