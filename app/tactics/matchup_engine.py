"""Transparent player- and team-level tactical matchup scoring."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

from app.tactics.player_profiles import (
    load_player_availability,
    load_player_profiles,
    load_projected_lineup,
)
from app.tactics.schemas import MatchupEdge, PlayerAvailability, PlayerProfile, ProjectedLineupPlayer


ROOT = Path(__file__).resolve().parents[2]
TACTICAL_PROFILES_PATH = ROOT / "data" / "tactical_profiles.csv"
SET_PIECE_PROFILES_PATH = ROOT / "data" / "set_piece_profiles.csv"
TEAM_FEATURES_PATH = ROOT / "data" / "team_features.csv"
TEAM_ADVANCED_FEATURES_PATH = ROOT / "data" / "team_advanced_features.csv"


def _clamp(value: float, minimum: float = -1.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _average(values: list[float], default: float = 50.0) -> float:
    return sum(values) / len(values) if values else default


def _rows_by_team(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["team"]: row for row in csv.DictReader(handle)}


def _number(row: dict[str, str] | None, key: str, default: float = 50.0) -> float:
    try:
        return float((row or {}).get(key, default))
    except (TypeError, ValueError):
        return default


def score_winger_vs_fullback(attacker: PlayerProfile, defender: PlayerProfile) -> float:
    """Positive values favor the winger; negative values favor the fullback."""
    attack = (
        (0.28 * attacker.dribbling)
        + (0.24 * attacker.pace)
        + (0.20 * attacker.chance_creation)
        + (0.16 * attacker.progression)
        + (0.12 * attacker.crossing)
    )
    defense = (
        (0.28 * defender.tackling)
        + (0.26 * defender.recovery)
        + (0.20 * defender.pace)
        + (0.16 * defender.press_resistance)
        + (0.10 * defender.aerial)
    )
    return _clamp((attack - defense) / 40)


def score_striker_vs_centerbacks(striker: PlayerProfile, centerbacks: list[PlayerProfile]) -> float:
    """Positive values favor the striker; negative values favor the centerbacks."""
    attack = (
        (0.38 * striker.finishing)
        + (0.24 * striker.pace)
        + (0.18 * striker.aerial)
        + (0.12 * striker.dribbling)
        + (0.08 * striker.press_resistance)
    )
    defense = _average(
        [
            (0.34 * defender.tackling)
            + (0.28 * defender.recovery)
            + (0.20 * defender.aerial)
            + (0.10 * defender.pace)
            + (0.08 * defender.build_up)
            for defender in centerbacks
        ]
    )
    return _clamp((attack - defense) / 40)


def score_midfield_control(midfield_a: list[PlayerProfile], midfield_b: list[PlayerProfile]) -> float:
    """Positive values favor midfield A; negative values favor midfield B."""
    def control(players: list[PlayerProfile]) -> float:
        return _average(
            [
                (0.24 * player.passing)
                + (0.22 * player.progression)
                + (0.20 * player.press_resistance)
                + (0.18 * player.pressing)
                + (0.16 * player.recovery)
                for player in players
            ]
        )

    return _clamp((control(midfield_a) - control(midfield_b)) / 35)


def score_set_piece_edge(team_a: str, team_b: str) -> float:
    """Positive values favor team A's two-way set-piece matchup."""
    set_pieces = _rows_by_team(SET_PIECE_PROFILES_PATH)
    advanced = _rows_by_team(TEAM_ADVANCED_FEATURES_PATH)

    def attack(team: str) -> float:
        row = set_pieces.get(team)
        return (
            (0.35 * _number(row, "aerial_threat"))
            + (0.35 * _number(row, "delivery_quality"))
            + (0.30 * _number(advanced.get(team), "set_piece_attack"))
        )

    def defense(team: str) -> float:
        row = set_pieces.get(team)
        concede_resistance = 100 - _number(row, "set_piece_concede_risk", 25)
        return (0.55 * concede_resistance) + (0.45 * _number(advanced.get(team), "set_piece_defense"))

    a_net = attack(team_a) - defense(team_b)
    b_net = attack(team_b) - defense(team_a)
    return _clamp((a_net - b_net) / 45)


def score_transition_risk(team_a: str, team_b: str) -> float:
    """Positive values favor team A attacking transitions against team B."""
    tactics = _rows_by_team(TACTICAL_PROFILES_PATH)
    advanced = _rows_by_team(TEAM_ADVANCED_FEATURES_PATH)
    teams = _rows_by_team(TEAM_FEATURES_PATH)

    def transition_attack(team: str) -> float:
        return (
            (0.55 * _number(tactics.get(team), "transition"))
            + (0.45 * _number(advanced.get(team), "transition_speed"))
        )

    def transition_resistance(team: str) -> float:
        high_line_exposure = max(0.0, _number(tactics.get(team), "defensive_line") - 75) * 0.35
        return (
            (0.55 * _number(teams.get(team), "defense"))
            + (0.45 * _number(advanced.get(team), "tactical_flexibility"))
            - high_line_exposure
        )

    a_net = transition_attack(team_a) - transition_resistance(team_b)
    b_net = transition_attack(team_b) - transition_resistance(team_a)
    return _clamp((a_net - b_net) / 45)


def _score_press_vs_build_up(team_a: str, team_b: str) -> float:
    tactics = _rows_by_team(TACTICAL_PROFILES_PATH)
    advanced = _rows_by_team(TEAM_ADVANCED_FEATURES_PATH)

    def press(team: str) -> float:
        return (0.6 * _number(tactics.get(team), "pressing")) + (0.4 * _number(advanced.get(team), "pressing_intensity"))

    def build_up(team: str) -> float:
        return (0.7 * _number(tactics.get(team), "build_up")) + (0.3 * _number(advanced.get(team), "tactical_flexibility"))

    return _clamp(((press(team_a) - build_up(team_b)) - (press(team_b) - build_up(team_a))) / 45)


def _lineup_player(
    lineup: list[ProjectedLineupPlayer],
    profiles: dict[str, PlayerProfile],
    slots: set[str],
) -> tuple[ProjectedLineupPlayer, PlayerProfile] | None:
    for item in lineup:
        if item.position_slot.upper() in slots and item.player_id in profiles:
            return item, profiles[item.player_id]
    return None


def _lineup_players(
    lineup: list[ProjectedLineupPlayer],
    profiles: dict[str, PlayerProfile],
    slots: set[str],
) -> list[tuple[ProjectedLineupPlayer, PlayerProfile]]:
    return [(item, profiles[item.player_id]) for item in lineup if item.position_slot.upper() in slots and item.player_id in profiles]


def _reliability(
    lineup_players: list[ProjectedLineupPlayer],
    availability: dict[str, PlayerAvailability],
) -> float:
    values = []
    for item in lineup_players:
        status = availability.get(item.player_id)
        available = status.availability if status else 1.0
        minutes = min((status.minutes_limit if status else 90) / 90, 1.0)
        values.append(item.starter_probability * available * minutes)
    return math.prod(values) ** (1 / len(values)) if values else 0.35


def _edge_label(score: float, reliability: float) -> str:
    if score < 0.10:
        label = "even"
    elif score < 0.25:
        label = "slight"
    elif score < 0.45:
        label = "moderate"
    else:
        label = "strong"
    return f"uncertain {label}" if reliability < 0.60 and label != "even" else label


def _quality(profiles: list[PlayerProfile], lineup: list[ProjectedLineupPlayer]) -> str:
    qualities = {item.data_quality for item in profiles} | {item.data_quality for item in lineup}
    if qualities == {"manual_prototype"}:
        return "manual_prototype"
    if len(qualities) == 1:
        return next(iter(qualities))
    return "mixed_" + "_and_".join(sorted(qualities))


def _player_edge(
    *,
    matchup_type: str,
    original_team_a: str,
    original_team_b: str,
    attacking_team: str,
    attacker_item: ProjectedLineupPlayer,
    attacker: PlayerProfile,
    defending_team: str,
    defender_items: list[ProjectedLineupPlayer],
    defenders: list[PlayerProfile],
    raw_score: float,
    availability: dict[str, PlayerAvailability],
    reason: str,
    relevant_features: dict[str, Any],
) -> MatchupEdge:
    reliability = _reliability([attacker_item, *defender_items], availability)
    adjusted = _clamp(raw_score * reliability)
    favored = attacking_team if adjusted > 0.02 else defending_team if adjusted < -0.02 else None
    team_a_player = attacker.player if attacking_team == original_team_a else ", ".join(player.player for player in defenders)
    team_b_player = attacker.player if attacking_team == original_team_b else ", ".join(player.player for player in defenders)
    score = abs(adjusted)
    return MatchupEdge(
        matchup_type=matchup_type,
        team_a=original_team_a,
        team_b=original_team_b,
        team_a_player=team_a_player,
        team_b_player=team_b_player,
        favored_team=favored,
        edge_score=round(score, 3),
        edge_label=_edge_label(score, reliability),
        reason=reason,
        relevant_features={**relevant_features, "raw_ranking_score": round(raw_score, 3), "lineup_reliability": round(reliability, 3)},
        lineup_assumptions=[
            f"{attacker.player} starts as {attacker_item.position_slot} ({attacker_item.starter_probability:.0%})",
            *[
                f"{player.player} starts as {item.position_slot} ({item.starter_probability:.0%})"
                for item, player in zip(defender_items, defenders)
            ],
        ],
        data_quality=_quality([attacker, *defenders], [attacker_item, *defender_items]),
    )


def _team_edge(
    matchup_type: str,
    team_a: str,
    team_b: str,
    raw_score: float,
    reason: str,
    relevant_features: dict[str, Any],
    data_quality: str = "derived_team_profiles",
) -> MatchupEdge:
    score = abs(raw_score)
    favored = team_a if raw_score > 0.02 else team_b if raw_score < -0.02 else None
    return MatchupEdge(
        matchup_type=matchup_type,
        team_a=team_a,
        team_b=team_b,
        favored_team=favored,
        edge_score=round(score, 3),
        edge_label=_edge_label(score, 1.0),
        reason=reason,
        relevant_features={**relevant_features, "raw_ranking_score": round(raw_score, 3)},
        lineup_assumptions=[],
        data_quality=data_quality,
    )


def build_matchup_edges(team_a: str, team_b: str, match_id: str | None = None) -> list[MatchupEdge]:
    """Build ranked, inspectable matchup edges without changing forecast probabilities."""
    profiles = load_player_profiles()
    availability = load_player_availability()
    lineup_a = load_projected_lineup(team_a, match_id)
    lineup_b = load_projected_lineup(team_b, match_id)
    edges: list[MatchupEdge] = []

    wing_pairs = [
        (team_a, lineup_a, {"LW"}, team_b, lineup_b, {"RB", "RWB"}),
        (team_a, lineup_a, {"RW"}, team_b, lineup_b, {"LB", "LWB"}),
        (team_b, lineup_b, {"LW"}, team_a, lineup_a, {"RB", "RWB"}),
        (team_b, lineup_b, {"RW"}, team_a, lineup_a, {"LB", "LWB"}),
    ]
    for attacking_team, attack_lineup, attack_slots, defending_team, defense_lineup, defense_slots in wing_pairs:
        attacker_pair = _lineup_player(attack_lineup, profiles, attack_slots)
        defender_pair = _lineup_player(defense_lineup, profiles, defense_slots)
        if not attacker_pair or not defender_pair:
            continue
        attacker_item, attacker = attacker_pair
        defender_item, defender = defender_pair
        raw = score_winger_vs_fullback(attacker, defender)
        edges.append(
            _player_edge(
                matchup_type="winger_vs_fullback",
                original_team_a=team_a,
                original_team_b=team_b,
                attacking_team=attacking_team,
                attacker_item=attacker_item,
                attacker=attacker,
                defending_team=defending_team,
                defender_items=[defender_item],
                defenders=[defender],
                raw_score=raw,
                availability=availability,
                reason=(
                    f"{attacker.player}'s dribbling, pace, creation, and progression are compared with "
                    f"{defender.player}'s tackling, recovery, pace, and resistance."
                ),
                relevant_features={
                    "attacker_dribbling": attacker.dribbling,
                    "attacker_pace": attacker.pace,
                    "attacker_chance_creation": attacker.chance_creation,
                    "defender_tackling": defender.tackling,
                    "defender_recovery": defender.recovery,
                },
            )
        )

    for attacking_team, attack_lineup, defending_team, defense_lineup in (
        (team_a, lineup_a, team_b, lineup_b),
        (team_b, lineup_b, team_a, lineup_a),
    ):
        striker_pair = _lineup_player(attack_lineup, profiles, {"CF", "ST"})
        centerback_pairs = _lineup_players(defense_lineup, profiles, {"CB", "LCB", "RCB"})
        if not striker_pair or not centerback_pairs:
            continue
        striker_item, striker = striker_pair
        defender_items = [item for item, _ in centerback_pairs]
        defenders = [profile for _, profile in centerback_pairs]
        raw = score_striker_vs_centerbacks(striker, defenders)
        edges.append(
            _player_edge(
                matchup_type="striker_vs_centerbacks",
                original_team_a=team_a,
                original_team_b=team_b,
                attacking_team=attacking_team,
                attacker_item=striker_item,
                attacker=striker,
                defending_team=defending_team,
                defender_items=defender_items,
                defenders=defenders,
                raw_score=raw,
                availability=availability,
                reason=(
                    f"{striker.player}'s finishing, pace, and aerial profile are compared with the projected "
                    f"{defending_team} center-back unit's tackling, recovery, and aerial strength."
                ),
                relevant_features={
                    "striker_finishing": striker.finishing,
                    "striker_pace": striker.pace,
                    "striker_aerial": striker.aerial,
                    "centerback_tackling_avg": round(_average([player.tackling for player in defenders]), 2),
                    "centerback_recovery_avg": round(_average([player.recovery for player in defenders]), 2),
                },
            )
        )

    midfield_a_pairs = _lineup_players(lineup_a, profiles, {"DM", "CM", "LCM", "RCM", "AM"})
    midfield_b_pairs = _lineup_players(lineup_b, profiles, {"DM", "CM", "LCM", "RCM", "AM"})
    if midfield_a_pairs and midfield_b_pairs:
        midfield_a = [profile for _, profile in midfield_a_pairs]
        midfield_b = [profile for _, profile in midfield_b_pairs]
        raw = score_midfield_control(midfield_a, midfield_b)
        reliability = _reliability(
            [item for item, _ in midfield_a_pairs] + [item for item, _ in midfield_b_pairs],
            availability,
        )
        adjusted = raw * reliability
        edges.append(
            MatchupEdge(
                matchup_type="midfield_control",
                team_a=team_a,
                team_b=team_b,
                team_a_player=", ".join(player.player for player in midfield_a),
                team_b_player=", ".join(player.player for player in midfield_b),
                favored_team=team_a if adjusted > 0.02 else team_b if adjusted < -0.02 else None,
                edge_score=round(abs(adjusted), 3),
                edge_label=_edge_label(abs(adjusted), reliability),
                reason="Projected midfield units are compared on passing, progression, press resistance, pressing, and recovery.",
                relevant_features={
                    "team_a_control_score": round((raw * 35) + 50, 2),
                    "team_b_relative_control": round(50 - (raw * 35), 2),
                    "raw_ranking_score": round(raw, 3),
                    "lineup_reliability": round(reliability, 3),
                },
                lineup_assumptions=[
                    f"{item.player} starts as {item.position_slot} ({item.starter_probability:.0%})"
                    for item, _ in midfield_a_pairs + midfield_b_pairs
                ],
                data_quality=_quality(midfield_a + midfield_b, [item for item, _ in midfield_a_pairs + midfield_b_pairs]),
            )
        )

    set_piece = score_set_piece_edge(team_a, team_b)
    edges.append(
        _team_edge(
            "set_piece_edge",
            team_a,
            team_b,
            set_piece,
            "Set-piece delivery and aerial threat are compared with the opponent's set-piece resistance.",
            {"inputs": "set_piece_profiles + team_advanced_features"},
        )
    )
    transition = score_transition_risk(team_a, team_b)
    edges.append(
        _team_edge(
            "transition_defense_risk",
            team_a,
            team_b,
            transition,
            "Transition speed is compared with opponent defensive quality, flexibility, and high-line exposure.",
            {"inputs": "tactical_profiles + team_features + team_advanced_features"},
        )
    )
    press = _score_press_vs_build_up(team_a, team_b)
    edges.append(
        _team_edge(
            "press_vs_build_up",
            team_a,
            team_b,
            press,
            "Team pressing intensity is compared with opponent build-up quality in both directions.",
            {"inputs": "tactical_profiles + team_advanced_features"},
        )
    )

    return sorted(edges, key=lambda edge: edge.edge_score, reverse=True)
