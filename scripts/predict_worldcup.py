#!/usr/bin/env python3
"""Monte Carlo predictor for the 2026 FIFA World Cup."""

from __future__ import annotations

import argparse
import csv
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import joblib
except ModuleNotFoundError:
    joblib = None


ROOT = Path(__file__).resolve().parents[1]
TEAMS_PATH = ROOT / "data" / "teams.csv"
GROUPS_PATH = ROOT / "data" / "groups.csv"
FEATURES_PATH = ROOT / "data" / "team_features.csv"
ADVANCED_FEATURES_PATH = ROOT / "data" / "team_advanced_features.csv"
SQUAD_FEATURES_PATH = ROOT / "data" / "squad_features.csv"
PLAYER_MATCH_TEAM_FEATURES_PATH = ROOT / "data" / "player_match_team_features.csv"
LIVE_PLAYER_TEAM_FEATURES_PATH = ROOT / "data" / "derived" / "live_player_team_features.csv"
XG_TEAM_ZONES_PATH = ROOT / "data" / "xg_team_zones.csv"
MODEL_PATH = ROOT / "models" / "worldcup_random_forest.joblib"

CONFEDERATION_ADJUSTMENT = {
    "CONMEBOL": 0.10,
    "UEFA": 0.08,
    "CAF": 0.00,
    "CONCACAF": -0.02,
    "AFC": -0.05,
    "OFC": -0.12,
}

CONFEDERATION_STRENGTH = {
    "CONMEBOL": 0.10,
    "UEFA": 0.08,
    "CAF": 0.00,
    "CONCACAF": -0.02,
    "AFC": -0.05,
    "OFC": -0.12,
}

DEFAULT_TEAM_STATE = {
    "elo": 1500.0,
    "recent_points": 1.15,
    "recent_goal_diff": 0.0,
    "recent_goals_for": 1.25,
    "recent_goals_against": 1.25,
    "recent_clean_sheet": 0.25,
    "recent_win_rate": 0.33,
    "recent_draw_rate": 0.27,
    "recent_points_volatility": 1.0,
    "recent_goal_diff_volatility": 1.0,
    "experience_log": 0.0,
}

XG_SIGNAL_CACHE: dict[str, Any] = {"mtime": None, "signals": {}}

FEATURE_LABELS = {
    "rank_diff": "FIFA ranking edge",
    "squad_diff": "Squad quality",
    "attack_defense_edge": "Attack vs defense",
    "midfield_diff": "Midfield control",
    "keeper_diff": "Goalkeeper edge",
    "bench_diff": "Bench depth",
    "form_feature_diff": "Recent form input",
    "fitness_diff": "Fitness",
    "chemistry_diff": "Team chemistry",
    "manager_diff": "Manager rating",
    "set_piece_edge": "Set pieces",
    "penalty_diff": "Penalty strength",
    "discipline_diff": "Discipline",
    "tactical_diff": "Tactical flexibility",
    "injury_resilience_diff": "Injury resilience",
    "pressing_diff": "Pressing",
    "transition_diff": "Transition speed",
    "big_match_diff": "Big-match composure",
    "elo_diff": "Historical Elo",
    "recent_points_diff": "Recent points",
    "recent_goal_diff": "Recent goal difference",
    "recent_goals_for_diff": "Recent scoring form",
    "recent_goals_against_diff": "Recent defensive form",
    "recent_clean_sheet_diff": "Clean-sheet form",
    "recent_win_rate_diff": "Recent win rate",
    "recent_draw_rate_diff": "Recent draw rate",
    "recent_points_volatility_diff": "Form consistency",
    "recent_goal_diff_volatility_diff": "Goal-difference consistency",
    "rest_days_diff": "Rest advantage",
    "experience_diff": "International experience",
    "host_edge": "Host advantage",
    "confederation_strength_diff": "Confederation strength",
}

FEATURE_DIRECTIONS = {
    "recent_goals_against_diff": -1.0,
    "neutral": 0.0,
    "same_confederation": 0.0,
    "tournament_weight": 0.0,
}


@dataclass(frozen=True)
class Team:
    name: str
    confederation: str
    rank: int
    host: bool
    world_cup_pedigree: int
    attack: float = 70.0
    midfield: float = 70.0
    defense: float = 70.0
    goalkeeper: float = 70.0
    bench: float = 70.0
    recent_form: float = 70.0
    fitness: float = 88.0
    chemistry: float = 70.0
    manager: float = 70.0
    set_piece_attack: float = 75.0
    set_piece_defense: float = 75.0
    penalty_strength: float = 76.0
    discipline: float = 78.0
    tactical_flexibility: float = 76.0
    injury_resilience: float = 84.0
    pressing_intensity: float = 78.0
    transition_speed: float = 78.0
    big_match_composure: float = 78.0
    roster_value_score: float = 70.0
    projected_xi_score: float = 70.0
    bench_value_score: float = 70.0
    squad_experience: float = 70.0
    squad_balance: float = 70.0
    squad_availability: float = 100.0
    formation_fit: float = 70.0
    lineup_continuity: float = 70.0
    lineup_confidence: float = 0.0
    observed_lineups_count: float = 0.0
    player_shooting_score: float = 70.0
    player_chance_creation_score: float = 70.0
    player_passing_score: float = 70.0
    player_progression_score: float = 70.0
    player_pressing_score: float = 70.0
    player_defensive_activity_score: float = 70.0
    player_goalkeeping_score: float = 70.0
    player_keeper_sweeping_score: float = 70.0
    player_keeper_diving_score: float = 70.0
    player_set_piece_delivery_score: float = 70.0
    player_early_goal_score: float = 70.0
    player_late_goal_score: float = 70.0
    player_discipline_score: float = 70.0
    player_minutes_score: float = 70.0

    @property
    def strength(self) -> float:
        ranking_score = (90 - self.rank) / 90
        host_boost = 0.12 if self.host else 0.0
        pedigree_boost = (self.world_cup_pedigree - 3) * 0.045
        confed_boost = CONFEDERATION_ADJUSTMENT.get(self.confederation, 0.0)
        squad_score = (
            self.attack * 0.22
            + self.midfield * 0.20
            + self.defense * 0.18
            + self.goalkeeper * 0.10
            + self.bench * 0.10
            + self.recent_form * 0.08
            + self.fitness * 0.04
            + self.chemistry * 0.05
            + self.manager * 0.03
            + self.set_piece_attack * 0.03
            + self.set_piece_defense * 0.03
            + self.tactical_flexibility * 0.04
            + self.injury_resilience * 0.03
            + self.big_match_composure * 0.03
            + self.roster_value_score * 0.06
            + self.projected_xi_score * 0.08
            + self.squad_experience * 0.03
            + self.squad_balance * 0.03
            + self.squad_availability * 0.03
            + self.formation_fit * 0.03
            + self.lineup_continuity * 0.03
            + self.player_shooting_score * 0.04
            + self.player_chance_creation_score * 0.04
            + self.player_passing_score * 0.03
            + self.player_progression_score * 0.03
            + self.player_defensive_activity_score * 0.03
            + self.player_goalkeeping_score * 0.03
            + self.player_minutes_score * 0.02
        )
        squad_boost = (squad_score - 100) / 140
        return 1.0 + ranking_score + squad_boost + host_boost + pedigree_boost + confed_boost

    @property
    def squad_rating(self) -> float:
        return (
            self.attack * 0.25
            + self.midfield * 0.20
            + self.defense * 0.18
            + self.goalkeeper * 0.12
            + self.bench * 0.10
            + self.recent_form * 0.06
            + self.fitness * 0.03
            + self.chemistry * 0.04
            + self.manager * 0.02
            + self.set_piece_attack * 0.03
            + self.set_piece_defense * 0.03
            + self.tactical_flexibility * 0.03
            + self.injury_resilience * 0.03
            + self.big_match_composure * 0.02
            + self.roster_value_score * 0.05
            + self.projected_xi_score * 0.07
            + self.squad_experience * 0.03
            + self.squad_balance * 0.02
            + self.squad_availability * 0.02
            + self.formation_fit * 0.02
            + self.lineup_continuity * 0.02
            + self.player_shooting_score * 0.03
            + self.player_chance_creation_score * 0.03
            + self.player_passing_score * 0.02
            + self.player_progression_score * 0.02
            + self.player_defensive_activity_score * 0.02
            + self.player_goalkeeping_score * 0.02
            + self.player_minutes_score * 0.01
        ) / 1.52


@dataclass
class Standing:
    team: Team
    points: int = 0
    goals_for: int = 0
    goals_against: int = 0
    wins: int = 0

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against

    def sort_key(self) -> tuple[int, int, int, int, int]:
        return (
            self.points,
            self.goal_difference,
            self.goals_for,
            self.wins,
            -self.team.rank,
        )


@dataclass
class ModelBundle:
    model: dict[str, Any]
    path: Path
    probability_cache: dict[tuple[str, str], dict[str, float]] = field(default_factory=dict)
    goals_cache: dict[tuple[str, str, bool], tuple[float, float]] = field(default_factory=dict)
    scoreline_cache: dict[tuple[str, str, int, bool], list[tuple[int, int, float]]] = field(default_factory=dict)


def load_feature_rows() -> dict[str, dict[str, float]]:
    features: dict[str, dict[str, float]] = {}
    for path in (
        FEATURES_PATH,
        ADVANCED_FEATURES_PATH,
        SQUAD_FEATURES_PATH,
        PLAYER_MATCH_TEAM_FEATURES_PATH,
        LIVE_PLAYER_TEAM_FEATURES_PATH,
    ):
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                features.setdefault(row["team"], {}).update(
                    {
                        key: float(value)
                        for key, value in row.items()
                        if key != "team" and value != ""
                    }
                )
    return features


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


def load_teams() -> dict[str, Team]:
    features = load_feature_rows()
    with TEAMS_PATH.open(newline="", encoding="utf-8") as handle:
        rows = csv.DictReader(handle)
        return {
            row["team"]: Team(
                name=row["team"],
                confederation=row["confederation"],
                rank=int(row["rank"]),
                host=row["host"] == "1",
                world_cup_pedigree=int(row["world_cup_pedigree"]),
                **features.get(row["team"], {}),
            )
            for row in rows
        }


def load_groups(teams: dict[str, Team]) -> dict[str, list[Team]]:
    groups: dict[str, list[Team]] = defaultdict(list)
    with GROUPS_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            groups[row["group"]].append(teams[row["team"]])
    return dict(sorted(groups.items()))


def load_model(path: Path) -> ModelBundle | None:
    if not path.exists():
        return None
    if joblib is None:
        raise SystemExit(
            "A model file exists, but joblib is not installed. Run:\n"
            "  source .venv/bin/activate\n"
            "  pip install -r requirements.txt"
        )
    return ModelBundle(model=joblib.load(path), path=path)


def poisson(lam: float) -> int:
    threshold = math.exp(-lam)
    product = 1.0
    count = 0
    while product > threshold:
        count += 1
        product *= random.random()
    return count - 1


def expected_goals(team: Team, opponent: Team, knockout: bool = False) -> float:
    strength_gap = team.strength - opponent.strength
    attack_edge = (team.attack - opponent.defense) / 100
    midfield_edge = (team.midfield - opponent.midfield) / 100
    keeper_edge = (70 - opponent.goalkeeper) / 100
    form_edge = (team.recent_form - opponent.recent_form) / 100
    fitness_edge = (team.fitness - opponent.fitness) / 100
    chemistry_edge = (team.chemistry - opponent.chemistry) / 100
    bench_edge = (team.bench - opponent.bench) / 100
    set_piece_edge = (team.set_piece_attack - opponent.set_piece_defense) / 100
    transition_edge = (team.transition_speed - opponent.pressing_intensity) / 100
    discipline_edge = (team.discipline - opponent.discipline) / 100
    tactical_edge = (team.tactical_flexibility - opponent.tactical_flexibility) / 100
    injury_edge = (team.injury_resilience - opponent.injury_resilience) / 100
    pressure_edge = (team.big_match_composure - opponent.big_match_composure) / 100
    roster_edge = (team.roster_value_score - opponent.roster_value_score) / 100
    xi_edge = (team.projected_xi_score - opponent.projected_xi_score) / 100
    experience_edge = (team.squad_experience - opponent.squad_experience) / 100
    balance_edge = (team.squad_balance - opponent.squad_balance) / 100
    availability_edge = (team.squad_availability - opponent.squad_availability) / 100
    formation_edge = (team.formation_fit - opponent.formation_fit) / 100
    continuity_edge = (team.lineup_continuity - opponent.lineup_continuity) / 100
    player_shooting_edge = (team.player_shooting_score - opponent.player_goalkeeping_score) / 100
    player_creation_edge = (team.player_chance_creation_score - opponent.player_defensive_activity_score) / 100
    player_passing_edge = (team.player_passing_score - opponent.player_pressing_score) / 100
    player_progression_edge = (team.player_progression_score - opponent.player_defensive_activity_score) / 100
    player_timing_edge = ((team.player_early_goal_score + team.player_late_goal_score) - 140) / 100
    player_minutes_edge = (team.player_minutes_score - opponent.player_minutes_score) / 100
    opponent_discipline_vulnerability = (70 - opponent.player_discipline_score) / 100
    xg_zone_edge = xg_forecast_edge(team.name, opponent.name)
    base = 1.22 if not knockout else 1.08
    expected = (
        base
        + (0.58 * strength_gap)
        + (0.42 * attack_edge)
        + (0.18 * midfield_edge)
        + (0.20 * keeper_edge)
        + (0.14 * form_edge)
        + (0.10 * fitness_edge)
        + (0.08 * chemistry_edge)
        + (0.05 * bench_edge)
        + (0.16 * set_piece_edge)
        + (0.11 * transition_edge)
        + (0.06 * discipline_edge)
        + ((0.10 if knockout else 0.05) * tactical_edge)
        + (0.07 * injury_edge)
        + ((0.08 if knockout else 0.03) * pressure_edge)
        + (0.12 * roster_edge)
        + (0.18 * xi_edge)
        + (0.06 * experience_edge)
        + (0.05 * balance_edge)
        + (0.08 * availability_edge)
        + (0.05 * formation_edge)
        + (0.05 * continuity_edge)
        + (0.08 * player_shooting_edge)
        + (0.08 * player_creation_edge)
        + (0.04 * player_passing_edge)
        + (0.05 * player_progression_edge)
        + (0.03 * player_timing_edge)
        + (0.03 * player_minutes_edge)
        + (0.03 * opponent_discipline_vulnerability)
        + (0.08 * xg_zone_edge)
    )
    return max(0.15, min(3.80, expected))


def model_features(team_a: Team, team_b: Team, bundle: ModelBundle, neutral: int = 1) -> dict[str, float]:
    state = bundle.model.get("team_state", {})
    a_state = {**DEFAULT_TEAM_STATE, **state.get(team_a.name, {})}
    b_state = {**DEFAULT_TEAM_STATE, **state.get(team_b.name, {})}
    return {
        "rank_diff": float(team_b.rank - team_a.rank),
        "squad_diff": team_a.squad_rating - team_b.squad_rating,
        "attack_defense_edge": (team_a.attack - team_b.defense) - (team_b.attack - team_a.defense),
        "midfield_diff": team_a.midfield - team_b.midfield,
        "keeper_diff": team_a.goalkeeper - team_b.goalkeeper,
        "bench_diff": team_a.bench - team_b.bench,
        "form_feature_diff": team_a.recent_form - team_b.recent_form,
        "fitness_diff": team_a.fitness - team_b.fitness,
        "chemistry_diff": team_a.chemistry - team_b.chemistry,
        "manager_diff": team_a.manager - team_b.manager,
        "set_piece_edge": (team_a.set_piece_attack - team_b.set_piece_defense)
        - (team_b.set_piece_attack - team_a.set_piece_defense),
        "penalty_diff": team_a.penalty_strength - team_b.penalty_strength,
        "discipline_diff": team_a.discipline - team_b.discipline,
        "tactical_diff": team_a.tactical_flexibility - team_b.tactical_flexibility,
        "injury_resilience_diff": team_a.injury_resilience - team_b.injury_resilience,
        "pressing_diff": team_a.pressing_intensity - team_b.pressing_intensity,
        "transition_diff": team_a.transition_speed - team_b.transition_speed,
        "big_match_diff": team_a.big_match_composure - team_b.big_match_composure,
        "elo_diff": a_state["elo"] - b_state["elo"],
        "recent_points_diff": a_state["recent_points"] - b_state["recent_points"],
        "recent_goal_diff": a_state["recent_goal_diff"] - b_state["recent_goal_diff"],
        "recent_goals_for_diff": a_state["recent_goals_for"] - b_state["recent_goals_for"],
        "recent_goals_against_diff": a_state["recent_goals_against"] - b_state["recent_goals_against"],
        "recent_clean_sheet_diff": a_state["recent_clean_sheet"] - b_state["recent_clean_sheet"],
        "recent_win_rate_diff": a_state["recent_win_rate"] - b_state["recent_win_rate"],
        "recent_draw_rate_diff": a_state["recent_draw_rate"] - b_state["recent_draw_rate"],
        "recent_points_volatility_diff": a_state["recent_points_volatility"] - b_state["recent_points_volatility"],
        "recent_goal_diff_volatility_diff": a_state["recent_goal_diff_volatility"] - b_state["recent_goal_diff_volatility"],
        "rest_days_diff": 0.0,
        "experience_diff": a_state["experience_log"] - b_state["experience_log"],
        "host_edge": 0.0 if neutral else (1.0 if team_a.host else -1.0 if team_b.host else 0.0),
        "neutral": float(neutral),
        "same_confederation": float(team_a.confederation == team_b.confederation),
        "confederation_strength_diff": CONFEDERATION_STRENGTH.get(team_a.confederation, 0.0)
        - CONFEDERATION_STRENGTH.get(team_b.confederation, 0.0),
        "tournament_weight": 1.45,
    }


def aligned_prediction(model: Any, values: list[list[float]]) -> dict[str, float]:
    raw = model.predict_proba(values)[0]
    probabilities = {"team_a_win": 0.0, "draw": 0.0, "team_b_win": 0.0}
    for label, probability in zip(model.classes_, raw):
        probabilities[str(label)] = float(probability)
    return probabilities


def dixon_coles_prediction(team_a: Team, team_b: Team, bundle: ModelBundle, max_goals: int = 11) -> tuple[dict[str, float], Any | None]:
    model = bundle.model.get("dixon_coles_model")
    if model is None:
        return {}, None
    try:
        grid = model.predict(team_a.name, team_b.name, max_goals=max_goals, neutral_venue=True)
    except (ValueError, KeyError):
        return {}, None
    home, draw, away = grid.home_draw_away
    return {
        "team_a_win": float(home),
        "draw": float(draw),
        "team_b_win": float(away),
    }, grid


def model_probabilities(team_a: Team, team_b: Team, bundle: ModelBundle) -> dict[str, float]:
    cache_key = (team_a.name, team_b.name)
    if cache_key in bundle.probability_cache:
        return bundle.probability_cache[cache_key]

    columns = bundle.model["feature_columns"]
    row = model_features(team_a, team_b, bundle)
    classifier = bundle.model["classifier"]
    rf = aligned_prediction(classifier, [[row[column] for column in columns]])
    elo_model = bundle.model.get("elo_model")
    stacker = bundle.model.get("ensemble_calibrator")
    if elo_model is not None and stacker is not None:
        elo_columns = bundle.model.get("elo_feature_columns", ["elo_diff", "neutral", "tournament_weight"])
        elo = aligned_prediction(elo_model, [[row[column] for column in elo_columns]])
        dixon_coles, _ = dixon_coles_prediction(team_a, team_b, bundle)
        if not dixon_coles:
            dixon_coles = elo
        order = ["team_a_win", "draw", "team_b_win"]
        stacked = [[*(rf[label] for label in order), *(dixon_coles[label] for label in order), *(elo[label] for label in order)]]
        probabilities = aligned_prediction(stacker, stacked)
        total = sum(probabilities.values())
        probabilities = {key: value / total for key, value in probabilities.items()}
        bundle.probability_cache[cache_key] = probabilities
        return probabilities

    priors = bundle.model.get("probability_prior", {})
    shrinkage = float(bundle.model.get("probability_shrinkage", 0.0))
    probabilities = {"team_a_win": 0.0, "draw": 0.0, "team_b_win": 0.0}
    for label, probability in rf.items():
        prior = float(priors.get(label, 1 / max(len(classifier.classes_), 1)))
        probabilities[label] = ((1 - shrinkage) * float(probability)) + (shrinkage * prior)
    total = sum(probabilities.values())
    if total:
        probabilities = {key: value / total for key, value in probabilities.items()}
    bundle.probability_cache[cache_key] = probabilities
    return probabilities


def model_expected_goals(team_a: Team, team_b: Team, bundle: ModelBundle, knockout: bool = False) -> tuple[float, float]:
    cache_key = (team_a.name, team_b.name, knockout)
    if cache_key in bundle.goals_cache:
        return bundle.goals_cache[cache_key]

    columns = bundle.model["feature_columns"]
    row = model_features(team_a, team_b, bundle)
    values = [[row[column] for column in columns]]
    rf_a = float(bundle.model["goal_a_model"].predict(values)[0])
    rf_b = float(bundle.model["goal_b_model"].predict(values)[0])
    poisson_a = expected_goals(team_a, team_b, knockout)
    poisson_b = expected_goals(team_b, team_a, knockout)
    _, dixon_coles = dixon_coles_prediction(team_a, team_b, bundle)
    dc_a = float(dixon_coles.home_goal_expectation) if dixon_coles is not None else rf_a
    dc_b = float(dixon_coles.away_goal_expectation) if dixon_coles is not None else rf_b
    knockout_factor = 0.96 if knockout else 1.0
    goals = (
        max(0.15, min(3.80, knockout_factor * ((0.50 * dc_a) + (0.30 * rf_a) + (0.20 * poisson_a)))),
        max(0.15, min(3.80, knockout_factor * ((0.50 * dc_b) + (0.30 * rf_b) + (0.20 * poisson_b)))),
    )
    bundle.goals_cache[cache_key] = goals
    return goals


def sample_outcome(probabilities: dict[str, float]) -> str:
    draw_line = probabilities["team_a_win"] + probabilities["draw"]
    value = random.random()
    if value < probabilities["team_a_win"]:
        return "team_a_win"
    if value < draw_line:
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


def play_match(team_a: Team, team_b: Team, knockout: bool = False, bundle: ModelBundle | None = None) -> tuple[int, int]:
    if bundle is None:
        return (
            poisson(expected_goals(team_a, team_b, knockout)),
            poisson(expected_goals(team_b, team_a, knockout)),
        )

    scorelines = scoreline_distribution(team_a, team_b, max_goals=10, knockout=knockout, bundle=bundle)
    value = random.random()
    cumulative = 0.0
    for goals_a, goals_b, probability in scorelines:
        cumulative += probability
        if value <= cumulative:
            return goals_a, goals_b
    return scorelines[-1][0], scorelines[-1][1]


def play_group(group_teams: list[Team], bundle: ModelBundle | None = None) -> list[Standing]:
    table = {team.name: Standing(team) for team in group_teams}
    for idx, team_a in enumerate(group_teams):
        for team_b in group_teams[idx + 1 :]:
            goals_a, goals_b = play_match(team_a, team_b, bundle=bundle)
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
    return sorted(table.values(), key=lambda standing: standing.sort_key(), reverse=True)


def select_knockout_teams(group_tables: dict[str, list[Standing]]) -> list[Team]:
    qualified: list[Standing] = []
    third_place: list[Standing] = []
    for table in group_tables.values():
        qualified.extend(table[:2])
        third_place.append(table[2])

    best_thirds = sorted(third_place, key=lambda standing: standing.sort_key(), reverse=True)[:8]
    qualified.extend(best_thirds)
    return [standing.team for standing in sorted(qualified, key=lambda standing: standing.sort_key(), reverse=True)]


def knockout_winner(team_a: Team, team_b: Team, bundle: ModelBundle | None = None) -> Team:
    goals_a, goals_b = play_match(team_a, team_b, knockout=True, bundle=bundle)
    if goals_a > goals_b:
        return team_a
    if goals_b > goals_a:
        return team_b

    if bundle is not None:
        probabilities = model_probabilities(team_a, team_b, bundle)
        result_probability = probabilities["team_a_win"] + (probabilities["draw"] * 0.5)
        penalty_edge = ((team_a.penalty_strength + team_a.big_match_composure) - (team_b.penalty_strength + team_b.big_match_composure)) / 100
        strength_probability = 1 / (1 + math.exp(-((team_a.strength - team_b.strength) * 1.8 + penalty_edge)))
        probability_a = (0.70 * result_probability) + (0.30 * strength_probability)
    else:
        penalty_edge = ((team_a.penalty_strength + team_a.big_match_composure) - (team_b.penalty_strength + team_b.big_match_composure)) / 100
        probability_a = 1 / (1 + math.exp(-((team_a.strength - team_b.strength) * 1.8 + penalty_edge)))
    return team_a if random.random() < probability_a else team_b


def poisson_probability(lam: float, goals: int) -> float:
    return (math.exp(-lam) * (lam**goals)) / math.factorial(goals)


def scoreline_distribution(
    team_a: Team,
    team_b: Team,
    max_goals: int = 7,
    knockout: bool = False,
    bundle: ModelBundle | None = None,
) -> list[tuple[int, int, float]]:
    cache_key = (team_a.name, team_b.name, max_goals, knockout)
    if bundle is not None and cache_key in bundle.scoreline_cache:
        return bundle.scoreline_cache[cache_key]

    if bundle is None:
        lambda_a = expected_goals(team_a, team_b, knockout)
        lambda_b = expected_goals(team_b, team_a, knockout)
    else:
        lambda_a, lambda_b = model_expected_goals(team_a, team_b, bundle, knockout)
    _, dixon_coles = dixon_coles_prediction(team_a, team_b, bundle, max_goals=max_goals + 1) if bundle is not None else ({}, None)
    scorelines: list[tuple[int, int, float]] = []
    for goals_a in range(max_goals + 1):
        for goals_b in range(max_goals + 1):
            poisson_probability_value = poisson_probability(lambda_a, goals_a) * poisson_probability(lambda_b, goals_b)
            if dixon_coles is not None and goals_a < dixon_coles.grid.shape[0] and goals_b < dixon_coles.grid.shape[1]:
                probability = (0.65 * float(dixon_coles.grid[goals_a, goals_b])) + (0.35 * poisson_probability_value)
            else:
                probability = poisson_probability_value
            scorelines.append((goals_a, goals_b, probability))
    if bundle is not None:
        target = model_probabilities(team_a, team_b, bundle)
        base = {
            "team_a_win": sum(p for a, b, p in scorelines if a > b),
            "draw": sum(p for a, b, p in scorelines if a == b),
            "team_b_win": sum(p for a, b, p in scorelines if b > a),
        }
        reweighted = []
        for goals_a, goals_b, probability in scorelines:
            outcome = "team_a_win" if goals_a > goals_b else "team_b_win" if goals_b > goals_a else "draw"
            reweighted.append((goals_a, goals_b, probability * target[outcome] / max(base[outcome], 1e-9)))
        scorelines = reweighted
    total = sum(item[2] for item in scorelines)
    result = sorted(
        [(goals_a, goals_b, probability / total) for goals_a, goals_b, probability in scorelines],
        key=lambda item: item[2],
        reverse=True,
    )
    if bundle is not None:
        bundle.scoreline_cache[cache_key] = result
    return result


def match_probabilities(team_a: Team, team_b: Team, max_goals: int = 9, bundle: ModelBundle | None = None) -> dict[str, float]:
    if bundle is not None:
        return model_probabilities(team_a, team_b, bundle)

    scorelines = scoreline_distribution(team_a, team_b, max_goals=max_goals)
    win_a = sum(probability for goals_a, goals_b, probability in scorelines if goals_a > goals_b)
    draw = sum(probability for goals_a, goals_b, probability in scorelines if goals_a == goals_b)
    win_b = sum(probability for goals_a, goals_b, probability in scorelines if goals_b > goals_a)
    total = win_a + draw + win_b
    return {
        "team_a_win": win_a / total,
        "draw": draw / total,
        "team_b_win": win_b / total,
    }


def model_feature_drivers(team_a: Team, team_b: Team, bundle: ModelBundle | None, top_n: int = 6) -> list[dict[str, Any]]:
    if bundle is None:
        return baseline_feature_drivers(team_a, team_b, top_n)

    columns = bundle.model.get("feature_columns", [])
    importances = bundle.model.get("feature_importance") or {}
    stats = bundle.model.get("feature_stats") or {}
    if not columns or not importances:
        return baseline_feature_drivers(team_a, team_b, top_n)

    row = model_features(team_a, team_b, bundle)
    raw_drivers = []
    for column in columns:
        direction = FEATURE_DIRECTIONS.get(column, 1.0)
        if direction == 0:
            continue
        value = float(row.get(column, 0.0))
        importance = float(importances.get(column, 0.0))
        stat = stats.get(column, {})
        mean = float(stat.get("mean", 0.0))
        std = max(float(stat.get("std", 1.0)), 0.001)
        contribution = ((value - mean) / std) * importance * direction
        if abs(contribution) < 0.0001:
            continue
        favored = team_a.name if contribution > 0 else team_b.name
        raw_drivers.append(
            {
                "label": FEATURE_LABELS.get(column, column.replace("_", " ").title()),
                "feature": column,
                "favored_team": favored,
                "raw_value": round(value, 3),
                "importance": round(importance, 4),
                "score": contribution,
            }
        )

    return normalize_driver_scores(raw_drivers, top_n)


def baseline_feature_drivers(team_a: Team, team_b: Team, top_n: int = 6) -> list[dict[str, Any]]:
    raw_drivers = [
        ("FIFA ranking edge", team_b.rank - team_a.rank, 0.05),
        ("Squad quality", team_a.squad_rating - team_b.squad_rating, 0.25),
        ("Attack vs defense", (team_a.attack - team_b.defense) - (team_b.attack - team_a.defense), 0.18),
        ("Midfield control", team_a.midfield - team_b.midfield, 0.12),
        ("Goalkeeper edge", team_a.goalkeeper - team_b.goalkeeper, 0.10),
        ("Recent form", team_a.recent_form - team_b.recent_form, 0.10),
        ("Set pieces", (team_a.set_piece_attack - team_b.set_piece_defense) - (team_b.set_piece_attack - team_a.set_piece_defense), 0.08),
        ("Big-match composure", team_a.big_match_composure - team_b.big_match_composure, 0.07),
        ("Penalty strength", team_a.penalty_strength - team_b.penalty_strength, 0.05),
        ("Projected XI quality", team_a.projected_xi_score - team_b.projected_xi_score, 0.18),
        ("26-player roster value", team_a.roster_value_score - team_b.roster_value_score, 0.12),
        ("Bench value", team_a.bench_value_score - team_b.bench_value_score, 0.07),
        ("Squad experience", team_a.squad_experience - team_b.squad_experience, 0.06),
        ("Formation fit", team_a.formation_fit - team_b.formation_fit, 0.05),
        ("Lineup continuity", team_a.lineup_continuity - team_b.lineup_continuity, 0.05),
    ]
    drivers = []
    for label, value, weight in raw_drivers:
        if abs(value) < 0.01:
            continue
        drivers.append(
            {
                "label": label,
                "feature": label.lower().replace(" ", "_"),
                "favored_team": team_a.name if value > 0 else team_b.name,
                "raw_value": round(value, 3),
                "importance": weight,
                "score": value * weight,
            }
        )
    return normalize_driver_scores(drivers, top_n)


def normalize_driver_scores(drivers: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    if not drivers:
        return []
    selected = sorted(drivers, key=lambda item: abs(float(item["score"])), reverse=True)[:top_n]
    max_score = max(abs(float(item["score"])) for item in selected) or 1.0
    return [
        {
            "label": item["label"],
            "feature": item["feature"],
            "favored_team": item["favored_team"],
            "raw_value": item["raw_value"],
            "importance": item["importance"],
            "impact": round(100 * abs(float(item["score"])) / max_score, 1),
        }
        for item in selected
    ]


def play_knockout(seed_order: list[Team], bundle: ModelBundle | None = None) -> dict[str, list[Team] | Team]:
    current = seed_order[:]
    stages: dict[str, list[Team] | Team] = {"round_of_32": current[:]}
    stage_names = ["round_of_16", "quarterfinals", "semifinals", "finalists", "champion"]

    for stage_name in stage_names:
        winners: list[Team] = []
        for idx in range(len(current) // 2):
            winners.append(knockout_winner(current[idx], current[-idx - 1], bundle))
        if stage_name == "champion":
            stages[stage_name] = winners[0]
        else:
            stages[stage_name] = winners[:]
        current = winners
    return stages


def simulate_once(groups: dict[str, list[Team]], bundle: ModelBundle | None = None) -> dict[str, object]:
    group_tables = {group: play_group(teams, bundle) for group, teams in groups.items()}
    knockout_teams = select_knockout_teams(group_tables)
    knockout = play_knockout(knockout_teams, bundle)
    return {"groups": group_tables, "knockout": knockout}


def run_simulations(groups: dict[str, list[Team]], sims: int, bundle: ModelBundle | None = None) -> dict[str, Counter]:
    results = {
        "advance_group": Counter(),
        "round_of_16": Counter(),
        "quarterfinals": Counter(),
        "semifinals": Counter(),
        "finalists": Counter(),
        "champion": Counter(),
    }

    for _ in range(sims):
        sim = simulate_once(groups, bundle)
        knockout = sim["knockout"]
        for team in knockout["round_of_32"]:
            results["advance_group"][team.name] += 1
        for stage in ["round_of_16", "quarterfinals", "semifinals", "finalists"]:
            for team in knockout[stage]:
                results[stage][team.name] += 1
        results["champion"][knockout["champion"].name] += 1
    return results


def percentage(count: int, sims: int) -> float:
    return 100 * count / sims


def print_table(results: dict[str, Counter], teams: dict[str, Team], sims: int, target: str | None) -> None:
    names = [target] if target else sorted(
        teams,
        key=lambda name: (
            results["champion"][name],
            results["finalists"][name],
            results["semifinals"][name],
            -teams[name].rank,
        ),
        reverse=True,
    )
    header = f"{'Team':26} {'Rank':>4} {'Squad':>6} {'R32':>7} {'R16':>7} {'QF':>7} {'SF':>7} {'Final':>7} {'Win':>7}"
    print(header)
    print("-" * len(header))
    for name in names:
        if name not in teams:
            raise SystemExit(f"Unknown team: {name}")
        print(
            f"{name:26} "
            f"{teams[name].rank:>4} "
            f"{teams[name].squad_rating:>6.1f} "
            f"{percentage(results['advance_group'][name], sims):>6.1f}% "
            f"{percentage(results['round_of_16'][name], sims):>6.1f}% "
            f"{percentage(results['quarterfinals'][name], sims):>6.1f}% "
            f"{percentage(results['semifinals'][name], sims):>6.1f}% "
            f"{percentage(results['finalists'][name], sims):>6.1f}% "
            f"{percentage(results['champion'][name], sims):>6.1f}%"
        )


def save_csv(results: dict[str, Counter], teams: dict[str, Team], sims: int, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["team", "rank", "squad_rating", "r32_pct", "r16_pct", "qf_pct", "sf_pct", "final_pct", "win_pct"])
        for name, team in sorted(teams.items(), key=lambda item: results["champion"][item[0]], reverse=True):
            writer.writerow(
                [
                    name,
                    team.rank,
                    round(team.squad_rating, 3),
                    round(percentage(results["advance_group"][name], sims), 3),
                    round(percentage(results["round_of_16"][name], sims), 3),
                    round(percentage(results["quarterfinals"][name], sims), 3),
                    round(percentage(results["semifinals"][name], sims), 3),
                    round(percentage(results["finalists"][name], sims), 3),
                    round(percentage(results["champion"][name], sims), 3),
                ]
            )


def print_single_simulation(groups: dict[str, list[Team]], bundle: ModelBundle | None = None) -> None:
    sim = simulate_once(groups, bundle)
    print("Group results")
    for group, table in sim["groups"].items():
        ordered = ", ".join(f"{row.team.name} ({row.points} pts)" for row in table)
        print(f"Group {group}: {ordered}")
    print()
    print(f"Predicted champion: {sim['knockout']['champion'].name}")


def print_match_prediction(
    teams: dict[str, Team],
    team_a_name: str,
    team_b_name: str,
    top_scores: int,
    bundle: ModelBundle | None = None,
) -> None:
    if team_a_name not in teams:
        raise SystemExit(f"Unknown team: {team_a_name}")
    if team_b_name not in teams:
        raise SystemExit(f"Unknown team: {team_b_name}")

    team_a = teams[team_a_name]
    team_b = teams[team_b_name]
    if bundle is None:
        lambda_a = expected_goals(team_a, team_b)
        lambda_b = expected_goals(team_b, team_a)
    else:
        lambda_a, lambda_b = model_expected_goals(team_a, team_b, bundle)
    probabilities = match_probabilities(team_a, team_b, bundle=bundle)
    scorelines = scoreline_distribution(team_a, team_b, bundle=bundle)[:top_scores]

    print(f"{team_a.name} vs {team_b.name}")
    if bundle is not None:
        print(f"Model: RF + Dixon-Coles + Elo ensemble ({bundle.path})")
    print(f"Expected score: {team_a.name} {lambda_a:.2f} - {lambda_b:.2f} {team_b.name}")
    print(
        "Result probabilities: "
        f"{team_a.name} win {probabilities['team_a_win'] * 100:.1f}%, "
        f"draw {probabilities['draw'] * 100:.1f}%, "
        f"{team_b.name} win {probabilities['team_b_win'] * 100:.1f}%"
    )
    print()
    print("Most likely scorelines")
    for goals_a, goals_b, probability in scorelines:
        print(f"{team_a.name} {goals_a}-{goals_b} {team_b.name}: {probability * 100:.1f}%")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Predict the 2026 FIFA World Cup with Monte Carlo simulation.")
    parser.add_argument("--sims", type=int, default=20000, help="Number of tournament simulations.")
    parser.add_argument("--seed", type=int, default=26, help="Random seed for reproducible results.")
    parser.add_argument("--team", help="Only print one team's probabilities.")
    parser.add_argument("--save", type=Path, help="Optional CSV output path.")
    parser.add_argument("--single", action="store_true", help="Print one simulated tournament instead of probabilities.")
    parser.add_argument("--match", nargs=2, metavar=("TEAM_A", "TEAM_B"), help="Predict a specific match scoreline.")
    parser.add_argument("--top-scores", type=int, default=8, help="Number of scorelines to show with --match.")
    parser.add_argument("--model", type=Path, default=MODEL_PATH, help="Forecast ensemble model path.")
    parser.add_argument("--no-model", action="store_true", help="Ignore the trained ensemble and use the Poisson baseline.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.sims < 1:
        raise SystemExit("--sims must be at least 1")

    random.seed(args.seed)
    teams = load_teams()
    groups = load_groups(teams)
    bundle = None if args.no_model else load_model(args.model)

    if args.match:
        print_match_prediction(teams, args.match[0], args.match[1], args.top_scores, bundle)
        return

    if args.single:
        print_single_simulation(groups, bundle)
        return

    results = run_simulations(groups, args.sims, bundle)
    print_table(results, teams, args.sims, args.team)
    if args.save:
        save_csv(results, teams, args.sims, args.save)
        print(f"\nSaved predictions to {args.save}")


if __name__ == "__main__":
    main()
