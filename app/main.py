from __future__ import annotations

import json
import os
import random
import sys
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
sys.path.append(str(ROOT / "scripts"))

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
    scoreline_distribution,
    select_knockout_teams,
    poisson,
)

load_dotenv(ROOT / ".env")

STATIC_DIR = ROOT / "app" / "static"
LIVE_STATE_PATH = ROOT / "data" / "live_state.json"
PLAYERS_PATH = ROOT / "data" / "player_candidates.csv"

app = FastAPI(title="World Cup 2026 Predictor")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

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


class MatchRequest(BaseModel):
    team_a: str
    team_b: str
    use_model: bool = True
    top_scores: int = Field(default=8, ge=1, le=20)
    weather: str = "normal"
    travel: int = Field(default=20, ge=0, le=100)
    fatigue: int = Field(default=20, ge=0, le=100)
    home_advantage: float = Field(default=1.0, ge=0.0, le=2.0)


def request_context(request: SimulationRequest | MatchRequest) -> dict[str, Any]:
    return {
        "weather": request.weather,
        "travel": request.travel,
        "fatigue": request.fatigue,
        "home_advantage": request.home_advantage,
    }


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
    bundle = load_model(MODEL_PATH) if use_model else None
    return simulate_detail_core(teams, groups, state, bundle, seed, {"weather": "normal", "travel": 20, "fatigue": 20, "home_advantage": 1.0})


def run_many(sims: int, seed: int, use_model: bool, context: dict[str, Any]) -> dict[str, Any]:
    random.seed(seed)
    teams = load_teams()
    groups = load_groups(teams)
    state = load_live_state()
    bundle = load_model(MODEL_PATH) if use_model else None
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
        table.append(
            {
                **team_payload(team),
                "r32_pct": round(100 * counters["round_of_32"][team.name] / sims, 1),
                "r16_pct": round(100 * counters["round_of_16"][team.name] / sims, 1),
                "qf_pct": round(100 * counters["quarterfinals"][team.name] / sims, 1),
                "sf_pct": round(100 * counters["semifinals"][team.name] / sims, 1),
                "final_pct": round(100 * counters["finalists"][team.name] / sims, 1),
                "win_pct": round(100 * counters["champion"][team.name] / sims, 1),
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


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    model_exists = MODEL_PATH.exists()
    return {
        "model_exists": model_exists,
        "model_path": str(MODEL_PATH),
        "live_state": load_live_state(),
    }


@app.post("/api/simulate")
def api_simulate(request: SimulationRequest) -> dict[str, Any]:
    context = request_context(request)
    teams = load_teams()
    groups = load_groups(teams)
    state = load_live_state()
    bundle = load_model(MODEL_PATH) if request.use_model else None
    bracket = simulate_detail_core(teams, groups, state, bundle, request.seed, context)
    odds = run_many(request.sims, request.seed, request.use_model, context)
    return {"bracket": bracket, "odds": odds}


@app.post("/api/match")
def api_match(request: MatchRequest) -> dict[str, Any]:
    teams = load_teams()
    if request.team_a not in teams or request.team_b not in teams:
        raise HTTPException(status_code=404, detail="Unknown team")
    bundle = load_model(MODEL_PATH) if request.use_model else None
    team_a = teams[request.team_a]
    team_b = teams[request.team_b]
    context = request_context(request)
    lambda_a = context_expected_goals(team_a, team_b, bundle, context)
    lambda_b = context_expected_goals(team_b, team_a, bundle, context)
    probabilities = blended_context_probabilities(team_a, team_b, bundle, context)
    scores = scorelines_from_lambdas(lambda_a, lambda_b)[: request.top_scores]
    return {
        "team_a": team_payload(team_a),
        "team_b": team_payload(team_b),
        "expected_score": {"team_a": round(lambda_a, 2), "team_b": round(lambda_b, 2)},
        "probabilities": {key: round(value * 100, 1) for key, value in probabilities.items()},
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


@app.post("/api/refresh-live-data")
def api_refresh_live_data() -> dict[str, Any]:
    api_key = os.getenv("BALLDONTLIE_API_KEY")
    base_url = os.getenv("WORLD_CUP_API_BASE_URL", "https://fifa.balldontlie.io")
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

    try:
        response = requests.get(
            f"{base_url.rstrip('/')}/v1/world_cups/2026/matches",
            headers={"Authorization": api_key},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        state["source"] = "api-refresh-failed"
        save_live_state(state)
        return {"ok": False, "message": str(exc), "live_state": state}

    payload = response.json()
    state["source"] = base_url
    state["raw_match_count"] = len(payload.get("data", [])) if isinstance(payload, dict) else None
    save_live_state(state)
    return {"ok": True, "message": "Fetched live API payload. Mapping can be extended once provider schema is finalized.", "live_state": state}
