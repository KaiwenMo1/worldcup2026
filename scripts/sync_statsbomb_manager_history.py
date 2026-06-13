#!/usr/bin/env python3
"""Build observed manager-match history from StatsBomb Open Data."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from app.ingestion.normalizers import safe_write_csv  # noqa: E402
from app.ingestion.provenance import append_ingestion_run, create_ingestion_run  # noqa: E402
from app.ingestion.schemas import IngestionStatus, SourceRecord, SourceType  # noqa: E402
from app.ingestion.source_registry import get_source, upsert_source  # noqa: E402
from scripts.sync_manager_match_history import FIELDS  # noqa: E402
from scripts.sync_managers import read_csv  # noqa: E402


BASE_URL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
SOURCE_ID = "statsbomb_open_data"
MANAGERS_PATH = ROOT / "data" / "managers.csv"
TEAMS_PATH = ROOT / "data" / "teams.csv"
OUTPUT_PATH = ROOT / "data" / "manager_match_history.csv"
CACHE_DIR = ROOT / "data" / "raw" / "statsbomb_manager_history"


def normalized_tokens(value: str) -> set[str]:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    return set(re.findall(r"[a-z0-9]+", ascii_value))


def match_manager(manager_name: str, managers: list[dict[str, str]]) -> dict[str, str] | None:
    """Match a provider's expanded manager name only when one registry name is a unique token subset."""
    provider_tokens = normalized_tokens(manager_name)
    matches = [
        manager
        for manager in managers
        if normalized_tokens(manager.get("manager_name", "")) <= provider_tokens
    ]
    return matches[0] if len(matches) == 1 else None


def object_name(value: Any) -> str:
    return str(value.get("name") or "") if isinstance(value, dict) else str(value or "")


def competition_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("competition_name") or value.get("name") or "")
    return str(value or "")


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def get_json(path: str, cache_path: Path | None = None) -> Any:
    if cache_path and cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    response = requests.get(f"{BASE_URL}/{path.lstrip('/')}", timeout=60)
    response.raise_for_status()
    payload = response.json()
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def match_side(match: dict[str, Any], manager: dict[str, str]) -> tuple[str, str] | None:
    for side in ("home", "away"):
        team = match.get(f"{side}_team") or {}
        for provider_manager in team.get("managers") or []:
            if normalized_tokens(manager["manager_name"]) <= normalized_tokens(provider_manager.get("name", "")):
                return side, str(provider_manager.get("name") or "")
    return None


def starting_formation(events: list[dict[str, Any]], team: str) -> str:
    for event in events:
        if object_name(event.get("type")) != "Starting XI" or object_name(event.get("team")) != team:
            continue
        raw = str((event.get("tactics") or {}).get("formation") or "")
        return "-".join(raw) if raw else ""
    return ""


def score_state_minutes(events: list[dict[str, Any]], team: str, opponent: str) -> tuple[float, float]:
    goals = []
    for event in events:
        kind = object_name(event.get("type"))
        is_goal = kind == "Shot" and object_name((event.get("shot") or {}).get("outcome")) == "Goal"
        if not is_goal:
            continue
        scoring_team = object_name(event.get("team"))
        if scoring_team not in {team, opponent}:
            continue
        minute = min(90.0, float(event.get("minute") or 0) + float(event.get("second") or 0) / 60)
        goals.append((minute, scoring_team))
    score_for = score_against = 0
    leading = trailing = 0.0
    previous = 0.0
    for minute, scoring_team in sorted(goals):
        duration = max(0.0, minute - previous)
        if score_for > score_against:
            leading += duration
        elif score_for < score_against:
            trailing += duration
        if scoring_team == team:
            score_for += 1
        else:
            score_against += 1
        previous = minute
    duration = max(0.0, 90.0 - previous)
    if score_for > score_against:
        leading += duration
    elif score_for < score_against:
        trailing += duration
    return round(leading, 2), round(trailing, 2)


def event_metrics(events: list[dict[str, Any]], team: str, opponent: str) -> dict[str, float]:
    team_events = opponent_events = pressures = defensive_actions = 0
    defensive_x = []
    pass_progressions = []
    transition_attacks = 0
    set_piece_xg = 0.0
    substitutions = []
    set_piece_patterns = {"From Corner", "From Free Kick", "From Throw In", "From Kick Off", "From Goal Kick"}
    for event in events:
        event_team = object_name(event.get("team"))
        possession_team = object_name(event.get("possession_team"))
        kind = object_name(event.get("type"))
        if possession_team == team:
            team_events += 1
        elif possession_team == opponent:
            opponent_events += 1
        if event_team != team:
            continue
        location = event.get("location") or []
        if kind == "Pressure":
            pressures += 1
        if kind in {"Duel", "Interception", "Block", "Clearance", "Ball Recovery", "Pressure"}:
            defensive_actions += 1
            if len(location) >= 2:
                defensive_x.append(float(location[0]))
        if kind == "Pass" and len(location) >= 2:
            end_location = (event.get("pass") or {}).get("end_location") or []
            if len(end_location) >= 2 and not (event.get("pass") or {}).get("outcome"):
                pass_progressions.append(max(0.0, float(end_location[0]) - float(location[0])))
        if kind == "Shot":
            play_pattern = object_name(event.get("play_pattern"))
            shot = event.get("shot") or {}
            if play_pattern == "From Counter":
                transition_attacks += 1
            if play_pattern in set_piece_patterns or object_name(shot.get("type")) in {"Free Kick", "Penalty"}:
                set_piece_xg += float(shot.get("statsbomb_xg") or 0)
        if kind == "Substitution":
            substitutions.append(float(event.get("minute") or 0))
    total_possession_events = team_events + opponent_events
    return {
        "ppda": round(max(2.0, min(30.0, (opponent_events / max(pressures + defensive_actions, 1)) * 3.5)), 3),
        "defensive_line_height": round(clamp((sum(defensive_x) / max(len(defensive_x), 1)) / 1.2), 3),
        "build_up_directness": round(clamp((sum(pass_progressions) / max(len(pass_progressions), 1)) * 4), 3),
        "possession_share": round(team_events / max(total_possession_events, 1), 4),
        "transition_attacks": transition_attacks,
        "set_piece_xg": round(set_piece_xg, 4),
        "first_sub_minute": round(min(substitutions), 2) if substitutions else "",
        "substitution_count": len(substitutions),
    }


def build_history_row(
    match: dict[str, Any],
    events: list[dict[str, Any]],
    manager: dict[str, str],
    opponent_strengths: dict[str, float],
) -> dict[str, Any]:
    matched = match_side(match, manager)
    if matched is None:
        raise ValueError(f"{manager['manager_name']} is not attached to match {match.get('match_id')}")
    side, provider_name = matched
    other = "away" if side == "home" else "home"
    team = str((match.get(f"{side}_team") or {}).get(f"{side}_team_name") or "")
    opponent = str((match.get(f"{other}_team") or {}).get(f"{other}_team_name") or "")
    metrics = event_metrics(events, team, opponent)
    leading, trailing = score_state_minutes(events, team, opponent)
    row = {field: "" for field in FIELDS}
    row.update(
        {
            "match_id": str(match.get("match_id") or ""),
            "date": str(match.get("match_date") or ""),
            "manager_id": manager["manager_id"],
            "team": team,
            "opponent": opponent,
            "competition": competition_name(match.get("competition")),
            "goals_for": match.get(f"{side}_score", ""),
            "goals_against": match.get(f"{other}_score", ""),
            "opponent_strength": round(opponent_strengths.get(opponent, 70.0), 2),
            "formation": starting_formation(events, team),
            "leading_minutes": leading,
            "trailing_minutes": trailing,
            "source": f"statsbomb_open_data:{match.get('match_id')}:{provider_name}",
            **metrics,
        }
    )
    return row


def collect_candidate_matches(
    competitions: list[dict[str, Any]],
    managers: list[dict[str, str]],
    *,
    max_matches_per_manager: int,
) -> dict[str, list[dict[str, Any]]]:
    candidates: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for competition in competitions:
        matches = get_json(f"matches/{competition['competition_id']}/{competition['season_id']}.json")
        for match in matches:
            for side in ("home_team", "away_team"):
                for provider_manager in (match.get(side) or {}).get("managers") or []:
                    manager = match_manager(str(provider_manager.get("name") or ""), managers)
                    if manager:
                        candidates[manager["manager_id"]].append(match)
    return {
        manager_id: sorted(rows, key=lambda row: row.get("match_date", ""), reverse=True)[:max_matches_per_manager]
        for manager_id, rows in candidates.items()
    }


def ensure_source_registry() -> None:
    if get_source(SOURCE_ID):
        return
    upsert_source(
        SourceRecord(
            source_id=SOURCE_ID,
            source_name="StatsBomb Open Data",
            source_type=SourceType.PUBLIC_DATASET,
            reliability_score=0.9,
            requires_api_key=False,
            terms_note="StatsBomb Open Data user agreement applies; retain attribution.",
            enabled=True,
            last_checked=datetime.now(timezone.utc),
            notes="Observed match metadata and event data used for historical manager tendencies.",
        )
    )


def sync(max_matches_per_manager: int, output: Path = OUTPUT_PATH) -> list[dict[str, Any]]:
    managers = read_csv(MANAGERS_PATH)
    manager_by_id = {row["manager_id"]: row for row in managers}
    teams = read_csv(TEAMS_PATH)
    opponent_strengths = {
        row["team"]: 55 + float(row.get("squad_rating") or 70) * 0.45
        for row in teams
    }
    competitions = get_json("competitions.json", CACHE_DIR / "competitions.json")
    candidates = collect_candidate_matches(competitions, managers, max_matches_per_manager=max_matches_per_manager)
    rows = []
    seen = set()
    for manager_id, matches in sorted(candidates.items()):
        for match in matches:
            key = (manager_id, str(match.get("match_id")))
            if key in seen:
                continue
            seen.add(key)
            match_id = str(match["match_id"])
            events = get_json(f"events/{match_id}.json", CACHE_DIR / "events" / f"{match_id}.json")
            rows.append(build_history_row(match, events, manager_by_id[manager_id], opponent_strengths))
    rows.sort(key=lambda row: (row["manager_id"], row["date"], row["match_id"]))
    result = safe_write_csv(output, rows, FIELDS)
    if not result.ok:
        raise RuntimeError("; ".join(issue.problem for issue in result.issues))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Build observed manager-match history from StatsBomb Open Data.")
    parser.add_argument("--max-matches-per-manager", type=int, default=12)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    ensure_source_registry()
    try:
        rows = sync(args.max_matches_per_manager, args.output)
    except Exception as exc:
        append_ingestion_run(
            create_ingestion_run(
                source_id=SOURCE_ID,
                script="scripts/sync_statsbomb_manager_history.py",
                status=IngestionStatus.FAILED,
                error_message=str(exc),
                started_at=started,
            )
        )
        raise
    manager_count = len({row["manager_id"] for row in rows})
    append_ingestion_run(
        create_ingestion_run(
            source_id=SOURCE_ID,
            script="scripts/sync_statsbomb_manager_history.py",
            status=IngestionStatus.SUCCEEDED,
            rows_raw=len(rows),
            rows_normalized=len(rows),
            started_at=started,
        )
    )
    print(f"Saved {len(rows)} observed manager-match rows for {manager_count}/48 managers to {args.output}")


if __name__ == "__main__":
    main()
