#!/usr/bin/env python3
"""Validate or refresh the current 48-team World Cup manager registry."""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from predict_worldcup import ROOT


MANAGERS_PATH = ROOT / "data" / "managers.csv"
TEAMS_PATH = ROOT / "data" / "teams.csv"
SQUADS_URL = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WorldCupForecastResearch/1.0)"}
FIELDS = [
    "manager_id",
    "manager_name",
    "team",
    "active_from",
    "active_to",
    "status",
    "preferred_formations",
    "default_style",
    "pressing_level",
    "build_up_style",
    "transition_style",
    "set_piece_emphasis",
    "substitution_aggression",
    "big_game_risk_tolerance",
    "source",
    "last_verified",
    "notes",
]
TEAM_ALIASES = {
    "Czech Republic": "Czechia",
    "South Korea": "Korea Republic",
    "Turkey": "Turkiye",
    "United States": "USA",
    "Curaçao": "Curacao",
    "Ivory Coast": "Cote d'Ivoire",
    "Iran": "IR Iran",
    "Cape Verde": "Cabo Verde",
    "DR Congo": "Congo DR",
}


def slug(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def validate_registry(rows: list[dict[str, str]]) -> dict[str, Any]:
    teams = {row["team"] for row in read_csv(TEAMS_PATH)}
    registry_teams = [row.get("team", "") for row in rows]
    manager_ids = [row.get("manager_id", "") for row in rows]
    missing = sorted(teams - set(registry_teams))
    unknown = sorted(set(registry_teams) - teams)
    duplicates = sorted({team for team in registry_teams if registry_teams.count(team) > 1})
    duplicate_ids = sorted({item for item in manager_ids if manager_ids.count(item) > 1})
    invalid = [
        row.get("team", "<unknown>")
        for row in rows
        if not row.get("manager_id") or not row.get("manager_name") or not row.get("source")
    ]
    return {
        "valid": not (missing or unknown or duplicates or duplicate_ids or invalid) and len(rows) == len(teams),
        "registered": len(rows),
        "expected": len(teams),
        "missing_teams": missing,
        "unknown_teams": unknown,
        "duplicate_teams": duplicates,
        "duplicate_manager_ids": duplicate_ids,
        "invalid_rows": invalid,
    }


def public_manager_registry() -> dict[str, str]:
    response = requests.get(SQUADS_URL, headers=HEADERS, timeout=45)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    expected = {row["team"] for row in read_csv(TEAMS_PATH)}
    output: dict[str, str] = {}
    for heading in soup.select("h3"):
        raw_team = heading.get_text(" ", strip=True)
        team = TEAM_ALIASES.get(raw_team, raw_team)
        if team not in expected:
            continue
        node = heading.find_next_sibling()
        while node is not None and node.name not in {"h2", "h3"}:
            text = node.get_text(" ", strip=True)
            match = re.search(r"(?:Coach|Head coach):\s*(.+?)(?:\s+\[|$)", text)
            if match:
                output[team] = match.group(1).strip()
                break
            node = node.find_next_sibling()
    return output


def refresh(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    observed = public_manager_registry()
    current = {row["team"]: row for row in rows}
    output = []
    for team in sorted({row["team"] for row in read_csv(TEAMS_PATH)}):
        manager_name = observed.get(team)
        previous = current.get(team, {})
        if not manager_name:
            output.append(previous)
            continue
        changed = previous.get("manager_name") and previous.get("manager_name") != manager_name
        row = {field: previous.get(field, "") for field in FIELDS}
        row.update(
            {
                "manager_id": slug(f"{team}_{manager_name}"),
                "manager_name": manager_name,
                "team": team,
                "status": "registry_only" if changed or not previous else previous.get("status", "registry_only"),
                "source": SQUADS_URL,
                "last_verified": date.today().isoformat(),
                "notes": (
                    f"Registry changed from {previous.get('manager_name')} during sync; tactical profile requires review"
                    if changed
                    else previous.get("notes") or "Current tournament manager registry; tactical profile requires observed evidence"
                ),
            }
        )
        output.append(row)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate or refresh the 48-team manager registry.")
    parser.add_argument("--refresh", action="store_true", help="Refresh names from the public 2026 squads page.")
    args = parser.parse_args()

    rows = read_csv(MANAGERS_PATH)
    if args.refresh:
        rows = refresh(rows)
        write_csv(MANAGERS_PATH, rows)
    report = validate_registry(rows)
    print(report)
    if not report["valid"]:
        raise SystemExit("Manager registry does not satisfy the 48-team contract.")


if __name__ == "__main__":
    main()
