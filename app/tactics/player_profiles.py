"""Load role-oriented player profiles, projected lineups, and availability."""

from __future__ import annotations

import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.tactics.schemas import PlayerAvailability, PlayerProfile, ProjectedLineupPlayer


ROOT = Path(__file__).resolve().parents[2]
PLAYER_PROFILES_PATH = ROOT / "data" / "player_profiles.csv"
PROJECTED_LINEUPS_PATH = ROOT / "data" / "projected_lineups.csv"
PLAYER_AVAILABILITY_PATH = ROOT / "data" / "player_availability.csv"
PLAYER_MATCH_STATS_PATH = ROOT / "data" / "player_match_stats.csv"
CONFIRMED_LINEUPS_PATH = ROOT / "data" / "confirmed_lineups.csv"


class PlayerProfileDataError(ValueError):
    """Raised when an existing player tactical data file is malformed."""


def player_id_for(team: str, player: str) -> str:
    raw = unicodedata.normalize("NFKD", f"{team}_{player}").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", raw.casefold()).strip("_")


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise PlayerProfileDataError(f"Could not read {path}: {exc}") from exc


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return round(max(minimum, min(maximum, value)), 2)


def _list(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split("|") if item.strip()]


def _position_slot(value: str) -> str:
    normalized = value.casefold().replace("-", " ").strip()
    exact = {
        "goalkeeper": "GK",
        "right back": "RB",
        "left back": "LB",
        "right winger": "RW",
        "left winger": "LW",
        "centre forward": "CF",
        "center forward": "CF",
        "defensive midfield": "DM",
        "central midfield": "CM",
        "attacking midfield": "AM",
        "centre back": "CB",
        "center back": "CB",
    }
    if normalized in exact:
        return exact[normalized]
    broad = {"gk": "GK", "df": "CB", "mf": "CM", "fw": "CF"}
    return broad.get(normalized, value or "Unknown")


def _explicit_profile(row: dict[str, str]) -> PlayerProfile:
    payload: dict[str, Any] = {
        **row,
        "secondary_positions": _list(row.get("secondary_positions")),
        "role_archetypes": _list(row.get("role_archetypes")),
    }
    for field in (
        "starter_probability",
        "pace",
        "finishing",
        "passing",
        "chance_creation",
        "progression",
        "dribbling",
        "crossing",
        "pressing",
        "tackling",
        "aerial",
        "recovery",
        "press_resistance",
        "build_up",
        "set_piece_delivery",
    ):
        payload[field] = _float(row.get(field))
    payload["minutes_projection"] = _int(row.get("minutes_projection"), 90)
    return PlayerProfile.model_validate(payload)


def _derived_profile(row: dict[str, str]) -> PlayerProfile:
    team = row.get("team", "").strip()
    player = row.get("player", "").strip()
    pass_completion = _float(row.get("pass_completion_pct"), 65)
    dribble_success = _float(row.get("dribble_success_pct"), 50)
    pressure_success = _float(row.get("pressure_success_pct"), 35)
    tackle_success = _float(row.get("tackle_success_pct"), 55)
    aerial_win = _float(row.get("aerial_win_pct"), 50)
    progression = _clamp(
        42 + (_float(row.get("progressive_passes_per90")) * 4.0) + (_float(row.get("progressive_carries_per90")) * 4.5)
    )
    dribbling = _clamp((0.65 * dribble_success) + (_float(row.get("successful_dribbles_per90")) * 10))
    passing = _clamp(pass_completion)
    role_archetypes = [
        value
        for value in (row.get("tactical_role", ""), row.get("formation_role", ""), row.get("tactic_profile", ""))
        if value
    ] or ["derived_general_role"]
    projected_starter = row.get("projected_starter") == "1"
    source = row.get("source") or "derived_player_match_stats"
    data_quality = "derived_estimate" if source in {"estimated_from_squad_profile", "derived_player_match_stats"} else "observed_provider"
    return PlayerProfile(
        player_id=player_id_for(team, player),
        player=player,
        team=team,
        club=row.get("club", ""),
        primary_position=row.get("detailed_position") or row.get("position") or "Unknown",
        secondary_positions=[],
        preferred_foot=row.get("preferred_foot") or "Unknown",
        role_archetypes=role_archetypes,
        starter_probability=0.78 if projected_starter else 0.28,
        minutes_projection=78 if projected_starter else 28,
        availability_status="available" if _float(row.get("availability"), 1.0) > 0.5 else "limited",
        pace=_clamp(48 + (_float(row.get("progressive_carries_per90")) * 7) + (_float(row.get("successful_dribbles_per90")) * 4)),
        finishing=_clamp(42 + (_float(row.get("goals_per90")) * 58) + (_float(row.get("xg_per90")) * 18)),
        passing=passing,
        chance_creation=_clamp(42 + (_float(row.get("key_passes_per90")) * 9) + (_float(row.get("xa_per90")) * 30)),
        progression=progression,
        dribbling=dribbling,
        crossing=_clamp(42 + (_float(row.get("crosses_per90")) * 7) + (_float(row.get("cross_completion_pct")) * 0.45)),
        pressing=_clamp(42 + (_float(row.get("pressures_per90")) * 2.0) + (pressure_success * 0.3)),
        tackling=_clamp(tackle_success),
        aerial=_clamp(aerial_win),
        recovery=_clamp(42 + (_float(row.get("ball_recoveries_per90")) * 6)),
        press_resistance=_clamp((passing + dribbling + progression) / 3),
        build_up=_clamp((passing + progression) / 2),
        set_piece_delivery=_clamp(42 + (_float(row.get("set_piece_xa_per90")) * 180) + (_float(row.get("cross_completion_pct")) * 0.4)),
        source=source,
        data_quality=data_quality,
        updated_at=row.get("updated_at") or None,
    )


def load_player_profiles() -> dict[str, PlayerProfile]:
    """Load explicit role profiles and fill uncovered players from existing seasonal stats."""
    profiles: dict[str, PlayerProfile] = {}
    try:
        for row in _rows(PLAYER_PROFILES_PATH):
            profile = _explicit_profile(row)
            profiles[profile.player_id] = profile
        for row in _rows(PLAYER_MATCH_STATS_PATH):
            derived = _derived_profile(row)
            profiles.setdefault(derived.player_id, derived)
    except ValidationError as exc:
        raise PlayerProfileDataError(f"Invalid player profile data: {exc}") from exc
    return profiles


def _lineup_row(row: dict[str, str]) -> ProjectedLineupPlayer:
    payload: dict[str, Any] = {
        **row,
        "match_id": row.get("match_id") or None,
        "starter_probability": _float(row.get("starter_probability"), 0.5),
    }
    return ProjectedLineupPlayer.model_validate(payload)


def _fallback_lineup(team: str, match_id: str | None, profiles: dict[str, PlayerProfile]) -> list[ProjectedLineupPlayer]:
    rows = [row for row in _rows(CONFIRMED_LINEUPS_PATH) if row.get("team", "").casefold() == team.casefold()]
    exact = [row for row in rows if match_id is not None and row.get("match_id") == str(match_id)]
    selected = exact or [row for row in rows if not row.get("match_id")]
    output = []
    for row in selected:
        if row.get("starter") != "1":
            continue
        player_id = player_id_for(team, row.get("player", ""))
        profile = profiles.get(player_id)
        role = row.get("role") or (profile.role_archetypes[0] if profile else "projected_role")
        output.append(
            ProjectedLineupPlayer(
                match_id=row.get("match_id") or None,
                team=team,
                formation=row.get("formation") or "unknown",
                player_id=player_id,
                player=row.get("player", ""),
                position_slot=_position_slot(profile.primary_position if profile else row.get("role") or row.get("position") or ""),
                role=role,
                starter_probability=_clamp(_float(row.get("confidence"), 50), 0, 100) / 100,
                source=row.get("source") or "confirmed_lineups_fallback",
                data_quality="observed" if row.get("confirmed") == "1" else "projected_fallback",
                updated_at=row.get("updated_at") or None,
            )
        )
    return output


def load_projected_lineup(team: str, match_id: str | None = None) -> list[ProjectedLineupPlayer]:
    """Load a match-specific lineup, falling back to team defaults and existing projections."""
    profiles = load_player_profiles()
    rows = [row for row in _rows(PROJECTED_LINEUPS_PATH) if row.get("team", "").casefold() == team.casefold()]
    exact = [row for row in rows if match_id is not None and row.get("match_id") == str(match_id)]
    selected = exact or [row for row in rows if not row.get("match_id")]
    if selected:
        try:
            return [_lineup_row(row) for row in selected]
        except ValidationError as exc:
            raise PlayerProfileDataError(f"Invalid projected lineup data: {exc}") from exc
    return _fallback_lineup(team, match_id, profiles)


def load_player_availability() -> dict[str, PlayerAvailability]:
    """Load current availability using stable generated player ids when providers omit ids."""
    availability: dict[str, PlayerAvailability] = {}
    try:
        for row in _rows(PLAYER_AVAILABILITY_PATH):
            player_id = row.get("player_id") or player_id_for(row.get("team", ""), row.get("player", ""))
            item = PlayerAvailability(
                match_id=row.get("match_id") or None,
                player_id=player_id,
                player=row.get("player", ""),
                team=row.get("team", ""),
                status=row.get("status") or "unknown",
                availability=_float(row.get("availability"), 1.0),
                minutes_limit=_int(row.get("minutes_limit"), 90),
                impact_score=_float(row.get("impact_score"), 50.0),
                source=row.get("source") or "unknown",
                updated_at=row.get("updated_at") or None,
            )
            availability[item.player_id] = item
    except ValidationError as exc:
        raise PlayerProfileDataError(f"Invalid player availability data: {exc}") from exc
    return availability


def get_team_role_depth(team: str) -> dict[str, Any]:
    """Summarize available players by tactical role for one team."""
    profiles = [profile for profile in load_player_profiles().values() if profile.team.casefold() == team.casefold()]
    availability = load_player_availability()
    roles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for profile in profiles:
        status = availability.get(profile.player_id)
        effective_probability = profile.starter_probability * (status.availability if status else 1.0)
        for role in profile.role_archetypes:
            roles[role].append(
                {
                    "player_id": profile.player_id,
                    "player": profile.player,
                    "primary_position": profile.primary_position,
                    "starter_probability": round(profile.starter_probability, 3),
                    "effective_starter_probability": round(effective_probability, 3),
                    "availability_status": status.status if status else profile.availability_status,
                    "data_quality": profile.data_quality,
                }
            )
    for players in roles.values():
        players.sort(key=lambda item: item["effective_starter_probability"], reverse=True)
    return {
        "team": team,
        "players": len(profiles),
        "roles": dict(sorted(roles.items())),
        "source": "player_profiles + player_match_stats + player_availability",
    }
