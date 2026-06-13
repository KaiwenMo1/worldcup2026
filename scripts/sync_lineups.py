#!/usr/bin/env python3
"""Fetch observed national-team lineups, formations, and availability."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from dotenv import load_dotenv

from predict_worldcup import ROOT


TEAMS_PATH = ROOT / "data" / "teams.csv"
LINEUPS_PATH = ROOT / "data" / "lineup_observations.csv"
AVAILABILITY_PATH = ROOT / "data" / "player_availability.csv"
STATUS_PATH = ROOT / "data" / "lineup_sync_status.json"
TEAM_IDS_PATH = ROOT / "data" / "sportmonks_team_ids.json"
DEFAULT_BASE_URL = "https://api.sportmonks.com/v3/football"
SOURCE_NAME = "sportmonks"

TEAM_SEARCH_ALIASES = {
    "Czechia": "Czech Republic",
    "Korea Republic": "South Korea",
    "Turkiye": "Turkey",
    "USA": "United States",
    "Cote d'Ivoire": "Ivory Coast",
    "IR Iran": "Iran",
    "Cabo Verde": "Cape Verde",
    "Congo DR": "DR Congo",
}


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", normalized.lower())


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def nested_data(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        data = value.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


class SportmonksClient:
    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "WorldCupForecastResearch/1.0"})

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = {"api_token": self.token, **(params or {})}
        response = self.session.get(f"{self.base_url}/{path.lstrip('/')}", params=query, timeout=45)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected Sportmonks response for {path}")
        return payload


def load_team_ids() -> dict[str, int]:
    if not TEAM_IDS_PATH.exists():
        return {}
    payload = json.loads(TEAM_IDS_PATH.read_text(encoding="utf-8"))
    return {team: int(team_id) for team, team_id in payload.items()}


def choose_team_candidate(team: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    target_names = {normalize_name(team), normalize_name(TEAM_SEARCH_ALIASES.get(team, team))}
    ranked = []
    for candidate in candidates:
        name = normalize_name(str(candidate.get("name", "")))
        exact = int(name in target_names)
        national = int(str(candidate.get("type", "")).lower() in {"national", "country"})
        male = int(str(candidate.get("gender", "")).lower() in {"male", "men", ""})
        placeholder = int(bool(candidate.get("placeholder")))
        ranked.append(((exact, national, male, -placeholder), candidate))
    return max(ranked, key=lambda item: item[0])[1] if ranked else None


def resolve_team(client: SportmonksClient, team: str) -> tuple[int, dict[str, Any]]:
    query = TEAM_SEARCH_ALIASES.get(team, team)
    payload = client.get(f"teams/search/{quote(query)}", {"include": "sidelined.player", "per_page": 50})
    candidates = nested_data(payload.get("data", payload))
    candidate = choose_team_candidate(team, candidates)
    if candidate is None:
        raise ValueError(f"No Sportmonks team match for {team}")
    return int(candidate["id"]), candidate


def fixture_participants(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    return nested_data(fixture.get("participants"))


def fixture_opponent(fixture: dict[str, Any], team_id: int) -> str:
    for participant in fixture_participants(fixture):
        if int(participant.get("id", 0)) != team_id:
            return str(participant.get("name", "Unknown"))
    name = str(fixture.get("name", "Unknown"))
    return name


def fixture_formation(fixture: dict[str, Any], team_id: int) -> str:
    for formation in nested_data(fixture.get("formations")):
        participant_id = formation.get("participant_id", formation.get("team_id"))
        if participant_id is not None and int(participant_id) == team_id:
            return str(formation.get("formation", formation.get("formation_name", "")))
    locations = {
        str(participant.get("meta", {}).get("location", "")): int(participant.get("id", 0))
        for participant in fixture_participants(fixture)
        if isinstance(participant.get("meta"), dict)
    }
    location = next((key for key, value in locations.items() if value == team_id), "")
    for metadata in nested_data(fixture.get("metadata")):
        if int(metadata.get("type_id", 0)) != 159:
            continue
        values = metadata.get("values", {})
        if isinstance(values, dict) and location:
            return str(values.get(location, ""))
    return ""


def fixture_lineup_confirmed(fixture: dict[str, Any]) -> bool:
    for metadata in nested_data(fixture.get("metadata")):
        if int(metadata.get("type_id", 0)) != 572:
            continue
        values = metadata.get("values", {})
        if isinstance(values, dict):
            return bool(values.get("confirmed"))
    return True


def parse_fixture_lineups(team: str, team_id: int, fixture: dict[str, Any], fetched_at: str) -> list[dict[str, Any]]:
    formation = fixture_formation(fixture, team_id)
    confirmed = fixture_lineup_confirmed(fixture)
    rows = []
    for lineup in nested_data(fixture.get("lineups")):
        if int(lineup.get("team_id", 0)) != team_id or int(lineup.get("type_id", 0)) != 11:
            continue
        rows.append(
            {
                "team": team,
                "fixture_id": int(fixture["id"]),
                "match_date": str(fixture.get("starting_at", ""))[:10],
                "opponent": fixture_opponent(fixture, team_id),
                "formation": formation,
                "player": str(lineup.get("player_name", "")).strip(),
                "player_id": int(lineup.get("player_id", 0)),
                "formation_field": str(lineup.get("formation_field") or ""),
                "confirmed": int(confirmed),
                "source": SOURCE_NAME,
                "fetched_at": fetched_at,
            }
        )
    return rows


def sidelined_rows(team: str, candidate: dict[str, Any], fetched_at: str) -> list[dict[str, Any]]:
    rows = []
    for relation in nested_data(candidate.get("sidelined")):
        sideline = relation.get("sideline") if isinstance(relation.get("sideline"), dict) else relation
        player = relation.get("player") if isinstance(relation.get("player"), dict) else sideline.get("player", {})
        category = str(sideline.get("category", sideline.get("type", "unavailable")))
        end_date = str(sideline.get("end_date", sideline.get("end", "")))[:10]
        if end_date and end_date < date.today().isoformat():
            continue
        rows.append(
            {
                "team": team,
                "player": str(player.get("display_name", player.get("name", sideline.get("player_name", "")))).strip(),
                "player_id": int(player.get("id", sideline.get("player_id", 0)) or 0),
                "status": "unavailable",
                "category": category,
                "start_date": str(sideline.get("start_date", sideline.get("start", "")))[:10],
                "end_date": end_date,
                "source": SOURCE_NAME,
                "fetched_at": fetched_at,
            }
        )
    return rows


def sync(
    client: SportmonksClient,
    teams: list[str],
    days: int,
    max_fixtures: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    fetched_at = datetime.now(timezone.utc).isoformat()
    start_date = (date.today() - timedelta(days=days)).isoformat()
    end_date = date.today().isoformat()
    cached_ids = load_team_ids()
    observations = []
    availability = []
    errors = []
    coverage: dict[str, int] = {}

    for team in teams:
        try:
            if team in cached_ids:
                team_id = cached_ids[team]
                _, candidate = resolve_team(client, team)
            else:
                team_id, candidate = resolve_team(client, team)
                cached_ids[team] = team_id
            availability.extend(sidelined_rows(team, candidate, fetched_at))
            payload = client.get(
                f"fixtures/between/{start_date}/{end_date}/{team_id}",
                {
                    "include": "lineups;formations;participants;metadata",
                    "order": "desc",
                    "per_page": 50,
                },
            )
            fixtures = nested_data(payload.get("data", payload))[:max_fixtures]
            team_rows = []
            for fixture in fixtures:
                team_rows.extend(parse_fixture_lineups(team, team_id, fixture, fetched_at))
            observations.extend(team_rows)
            coverage[team] = len({row["fixture_id"] for row in team_rows})
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            errors.append({"team": team, "error": str(exc)})
            coverage[team] = 0

    write_json(TEAM_IDS_PATH, cached_ids)
    status = {
        "source": SOURCE_NAME,
        "fetched_at": fetched_at,
        "date_range": {"from": start_date, "through": end_date},
        "teams_requested": len(teams),
        "teams_with_lineups": sum(value > 0 for value in coverage.values()),
        "observed_fixtures": sum(coverage.values()),
        "unavailable_players": len(availability),
        "coverage": coverage,
        "errors": errors,
    }
    return observations, availability, status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync observed lineups and availability from Sportmonks.")
    parser.add_argument("--days", type=int, default=450, help="Historical date range to request.")
    parser.add_argument("--max-fixtures", type=int, default=12, help="Maximum recent fixtures per team.")
    parser.add_argument("--team", action="append", help="Sync one or more project team names.")
    parser.add_argument("--optional", action="store_true", help="Exit successfully when no API token is configured.")
    parser.add_argument("--base-url", default=os.getenv("SPORTMONKS_API_BASE_URL", DEFAULT_BASE_URL))
    return parser.parse_args()


def main() -> None:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    token = os.getenv("SPORTMONKS_API_TOKEN", "").strip()
    if not token:
        message = "Set SPORTMONKS_API_TOKEN in .env to sync observed lineups and availability."
        if args.optional:
            print(f"Skipped: {message}")
            return
        raise SystemExit(message)

    all_teams = [row["team"] for row in csv.DictReader(TEAMS_PATH.open(newline="", encoding="utf-8"))]
    requested = args.team or all_teams
    unknown = sorted(set(requested) - set(all_teams))
    if unknown:
        raise SystemExit(f"Unknown project teams: {', '.join(unknown)}")

    observations, availability, status = sync(
        SportmonksClient(token, args.base_url),
        requested,
        args.days,
        args.max_fixtures,
    )
    write_csv(
        LINEUPS_PATH,
        observations,
        [
            "team",
            "fixture_id",
            "match_date",
            "opponent",
            "formation",
            "player",
            "player_id",
            "formation_field",
            "confirmed",
            "source",
            "fetched_at",
        ],
    )
    write_csv(
        AVAILABILITY_PATH,
        availability,
        [
            "team",
            "player",
            "player_id",
            "status",
            "category",
            "start_date",
            "end_date",
            "source",
            "fetched_at",
        ],
    )
    write_json(STATUS_PATH, status)
    print(f"Observed lineup rows: {len(observations)}")
    print(f"Observed fixtures: {status['observed_fixtures']}")
    print(f"Teams with lineup coverage: {status['teams_with_lineups']}/{status['teams_requested']}")
    print(f"Unavailable players: {len(availability)}")
    if status["errors"]:
        print(f"Provider errors: {len(status['errors'])}; see {STATUS_PATH}")


if __name__ == "__main__":
    main()
