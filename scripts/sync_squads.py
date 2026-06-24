#!/usr/bin/env python3
"""Fetch final World Cup squads and build forecast-time squad features."""

from __future__ import annotations

import argparse
import csv
import math
import re
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

from predict_worldcup import ROOT
from sync_player_match_stats import (
    PLAYER_MATCH_STATS_COLUMNS,
    PLAYER_MATCH_STATS_PATH,
    PLAYER_MATCH_TEAM_FEATURES_PATH,
    PLAYER_MATCH_TEAM_FEATURE_COLUMNS,
    build_player_match_outputs,
)


SQUADS_URL = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads"
MARKET_VALUES_URL = (
    "https://www.transfermarkt.com/world-cup/marktwerte/pokalwettbewerb/FIWC/"
    "pos//detailpos/0/altersklasse/alle/plus/1/galerie/0/page/{page}"
)
PARTICIPANTS_URL = "https://www.transfermarkt.com/world-cup/teilnehmer/pokalwettbewerb/FIWC"
SQUADS_PATH = ROOT / "data" / "worldcup_squads.csv"
SQUAD_FEATURES_PATH = ROOT / "data" / "squad_features.csv"
PLAYER_CANDIDATES_PATH = ROOT / "data" / "player_candidates.csv"
LINEUPS_PATH = ROOT / "data" / "lineup_observations.csv"
AVAILABILITY_PATH = ROOT / "data" / "player_availability.csv"
TEAMS_PATH = ROOT / "data" / "teams.csv"

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
FORMATIONS = {
    "4-3-3": {"GK": 1, "DF": 4, "MF": 3, "FW": 3},
    "4-4-2": {"GK": 1, "DF": 4, "MF": 4, "FW": 2},
    "3-4-3": {"GK": 1, "DF": 3, "MF": 4, "FW": 3},
    "3-5-2": {"GK": 1, "DF": 3, "MF": 5, "FW": 2},
    "4-2-3-1": {"GK": 1, "DF": 4, "MF": 5, "FW": 1},
}
POSITION_SUFFIXES = [
    "Defensive Midfield",
    "Attacking Midfield",
    "Central Midfield",
    "Right Midfield",
    "Left Midfield",
    "Centre-Forward",
    "Second Striker",
    "Right Winger",
    "Left Winger",
    "Centre-Back",
    "Right-Back",
    "Left-Back",
    "Goalkeeper",
]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WorldCupForecastResearch/1.0)"}


def fetch(url: str, *, optional: bool = False, retries: int = 2) -> str:
    last_error: requests.RequestException | None = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=45)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))

    if optional:
        print(f"Warning: skipped optional squad enrichment URL after {retries + 1} attempts: {url} ({last_error})")
        return ""
    assert last_error is not None
    raise last_error


def optional_html_tables(url: str) -> list[pd.DataFrame]:
    html = fetch(url, optional=True)
    if not html:
        return []
    try:
        return pd.read_html(StringIO(html))
    except ValueError as exc:
        print(f"Warning: skipped optional squad enrichment table: {url} ({exc})")
        return []


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", normalized.lower())


def clean_player_name(value: Any) -> str:
    return re.sub(r"\s*\((?:captain|vice-captain)\)\s*", "", str(value), flags=re.IGNORECASE).strip()


def parse_market_value(value: Any) -> float:
    text = str(value).replace("€", "").replace(",", "").strip().lower()
    match = re.search(r"([0-9.]+)\s*([mk])?", text)
    if not match:
        return 0.0
    amount = float(match.group(1))
    if match.group(2) == "m":
        amount *= 1_000_000
    elif match.group(2) == "k":
        amount *= 1_000
    return amount


def transfermarkt_player(value: Any) -> tuple[str, str]:
    text = str(value).strip()
    for position in POSITION_SUFFIXES:
        if text.endswith(position):
            return text[: -len(position)].strip(), position
    return text, ""


def official_squads() -> list[dict[str, Any]]:
    soup = BeautifulSoup(fetch(SQUADS_URL), "html.parser")
    expected_teams = {row["team"] for row in csv.DictReader(TEAMS_PATH.open(newline="", encoding="utf-8"))}
    players = []
    for heading in soup.select("h3"):
        team = TEAM_ALIASES.get(heading.get_text(" ", strip=True), heading.get_text(" ", strip=True))
        if team not in expected_teams:
            continue
        table = heading.find_next("table")
        if table is None or "wikitable" not in table.get("class", []):
            continue
        frame = pd.read_html(StringIO(str(table)))[0]
        if "Player" not in frame.columns or "Pos." not in frame.columns:
            continue
        for row in frame.to_dict("records"):
            birth_text = str(row.get("Date of birth (age)", ""))
            age_match = re.search(r"aged\s+(\d+)", birth_text)
            birth_date = birth_text.split(" (aged")[0].strip()
            players.append(
                {
                    "team": team,
                    "player": clean_player_name(row.get("Player", "")),
                    "position": str(row.get("Pos.", "")).strip(),
                    "number": int(row.get("No.", 0)) if pd.notna(row.get("No.")) else "",
                    "age": int(age_match.group(1)) if age_match else "",
                    "birth_date": birth_date,
                    "caps": int(row.get("Caps", 0)) if pd.notna(row.get("Caps")) else 0,
                    "international_goals": int(row.get("Goals", 0)) if pd.notna(row.get("Goals")) else 0,
                    "club": str(row.get("Club", "")).strip(),
                }
            )
    return players


def market_values(pages: int, include_team_pages: bool = True) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for page in range(1, pages + 1):
        tables = optional_html_tables(MARKET_VALUES_URL.format(page=page))
        frame = next(
            (
                table
                for table in tables
                if {"#", "Player", "Market value", "Last update"}.issubset(set(table.columns))
            ),
            None,
        )
        if frame is None:
            continue
        for row in frame[frame["#"].notna()].to_dict("records"):
            player, detailed_position = transfermarkt_player(row["Player"])
            values[normalize_name(player)] = {
                "market_value_eur": parse_market_value(row["Market value"]),
                "market_value_updated": str(row.get("Last update", "")),
                "detailed_position": detailed_position,
            }
    if include_team_pages:
        participants_html = fetch(PARTICIPANTS_URL, optional=True)
        if not participants_html:
            return values
        soup = BeautifulSoup(participants_html, "html.parser")
        team_links = {}
        for link in soup.select("a[href*='/startseite/verein/']"):
            team = TEAM_ALIASES.get(link.get_text(" ", strip=True), link.get_text(" ", strip=True))
            if not team:
                continue
            href = link["href"].replace("/startseite/verein/", "/kader/verein/")
            team_links[team] = f"https://www.transfermarkt.com{href}/saison_id/2026"
        for url in team_links.values():
            tables = optional_html_tables(url)
            frame = next(
                (
                    table
                    for table in tables
                    if {"#", "Player", "Market value"}.issubset(set(table.columns))
                    and "Age" in table.columns
                ),
                None,
            )
            if frame is None:
                continue
            for row in frame[frame["#"].notna()].to_dict("records"):
                player, detailed_position = transfermarkt_player(row["Player"])
                key = normalize_name(player)
                current = values.get(key, {})
                values[key] = {
                    "market_value_eur": parse_market_value(row["Market value"]),
                    "market_value_updated": current.get("market_value_updated", ""),
                    "detailed_position": detailed_position,
                }
    return values


def player_score(player: dict[str, Any]) -> float:
    value_score = math.log1p(float(player["market_value_eur"])) / math.log1p(200_000_000)
    caps_score = min(float(player["caps"]) / 80, 1.0)
    goal_score = min(float(player["international_goals"]) / (35 if player["position"] == "FW" else 20), 1.0)
    return (0.68 * value_score) + (0.22 * caps_score) + (0.10 * goal_score)


def inferred_lineup(players: list[dict[str, Any]]) -> tuple[str, set[str], float]:
    by_position = {
        position: sorted(
            [player for player in players if player["position"] == position],
            key=player_score,
            reverse=True,
        )
        for position in ("GK", "DF", "MF", "FW")
    }
    best: tuple[float, str, set[str]] | None = None
    total_score = sum(player_score(player) for player in players) or 1.0
    for formation, counts in FORMATIONS.items():
        selected = []
        for position, count in counts.items():
            selected.extend(by_position[position][:count])
        score = sum(player_score(player) for player in selected)
        if len(selected) < 11:
            score -= (11 - len(selected)) * 2
        if best is None or score > best[0]:
            best = score, formation, {player["player"] for player in selected}
    assert best is not None
    return best[1], best[2], max(0.0, min(1.0, best[0] / total_score))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_lineup_context() -> dict[str, dict[str, Any]]:
    fixture_rows: defaultdict[str, defaultdict[str, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    for row in read_csv(LINEUPS_PATH):
        if row.get("confirmed", "1") != "1":
            continue
        fixture_rows[row["team"]][row["fixture_id"]].append(row)

    contexts = {}
    for team, fixtures in fixture_rows.items():
        ordered = sorted(
            fixtures.values(),
            key=lambda rows: rows[0].get("match_date", ""),
            reverse=True,
        )
        starts: Counter[str] = Counter()
        formations: Counter[str] = Counter()
        total_weight = 0.0
        for index, rows in enumerate(ordered):
            weight = math.pow(0.86, index)
            total_weight += weight
            formation = rows[0].get("formation", "")
            if formation:
                formations[formation] += weight
            for row in rows:
                starts[normalize_name(row["player"])] += weight
        top_starts = sum(value for _, value in starts.most_common(11))
        common_formation, formation_weight = formations.most_common(1)[0] if formations else ("", 0.0)
        fixture_count = len(ordered)
        contexts[team] = {
            "fixture_count": fixture_count,
            "formation": common_formation,
            "formation_share": formation_weight / max(total_weight, 1e-9),
            "start_rates": {player: value / max(total_weight, 1e-9) for player, value in starts.items()},
            "continuity": top_starts / max(11 * total_weight, 1e-9),
            "confidence": min(1.0, fixture_count / 8),
            "latest_match_date": ordered[0][0].get("match_date", "") if ordered else "",
        }
    return contexts


def load_availability() -> dict[str, dict[str, str]]:
    unavailable = {}
    for row in read_csv(AVAILABILITY_PATH):
        if row.get("status") != "unavailable":
            continue
        unavailable[f"{row['team']}::{normalize_name(row['player'])}"] = row
    return unavailable


def projected_lineup(
    players: list[dict[str, Any]],
    observed: dict[str, Any] | None = None,
) -> tuple[str, set[str], float, str, dict[str, float], float, float]:
    fallback_formation, fallback_starters, fallback_fit = inferred_lineup(players)
    if not observed or observed.get("fixture_count", 0) < 1:
        return (
            fallback_formation,
            fallback_starters,
            fallback_fit,
            "market-value/caps positional projection",
            {},
            0.0,
            0.0,
        )

    roster_by_key = {normalize_name(player["player"]): player["player"] for player in players}
    rates = {
        roster_by_key[key]: float(value)
        for key, value in observed.get("start_rates", {}).items()
        if key in roster_by_key
    }
    starters = {player for player, _ in sorted(rates.items(), key=lambda item: item[1], reverse=True)[:11]}
    for player in sorted(fallback_starters, key=lambda name: player_score(next(row for row in players if row["player"] == name)), reverse=True):
        if len(starters) >= 11:
            break
        starters.add(player)
    source = "observed recent starting XI" if observed["fixture_count"] >= 3 else "limited observed lineup + projection"
    return (
        observed.get("formation") or fallback_formation,
        starters,
        float(observed.get("formation_share") or fallback_fit),
        source,
        rates,
        float(observed.get("confidence", 0.0)),
        float(observed.get("continuity", 0.0)),
    )


def percentile_scores(values: dict[str, float], low: float = 55.0, high: float = 96.0) -> dict[str, float]:
    ordered = sorted(values.values())
    if len(ordered) < 2:
        return {team: (low + high) / 2 for team in values}
    results = {}
    for team, value in values.items():
        lower = sum(candidate < value for candidate in ordered)
        equal = sum(candidate == value for candidate in ordered)
        rank = lower + ((equal - 1) / 2)
        results[team] = low + ((high - low) * rank / (len(ordered) - 1))
    return results


def build_outputs(players: list[dict[str, Any]], fetched_at: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    teams: dict[str, list[dict[str, Any]]] = {}
    for player in players:
        teams.setdefault(player["team"], []).append(player)

    lineup_context = load_lineup_context()
    unavailable = load_availability()
    team_raw: dict[str, dict[str, float]] = {}
    for team, squad in teams.items():
        formation, starters, fit, lineup_source, start_rates, lineup_confidence, continuity = projected_lineup(
            squad,
            lineup_context.get(team),
        )
        availability_by_player = {
            player["player"]: unavailable.get(f"{team}::{normalize_name(player['player'])}")
            for player in squad
        }
        expected_starters = set(starters)
        unavailable_starters = [
            player
            for player in squad
            if player["player"] in starters and availability_by_player[player["player"]]
        ]
        replacements = []
        for missing in unavailable_starters:
            candidates = [
                player
                for player in squad
                if player["player"] not in starters
                and not availability_by_player[player["player"]]
                and player["position"] == missing["position"]
            ]
            if not candidates:
                candidates = [
                    player
                    for player in squad
                    if player["player"] not in starters and not availability_by_player[player["player"]]
                ]
            if candidates:
                replacement = max(candidates, key=player_score)
                starters.remove(missing["player"])
                starters.add(replacement["player"])
                replacements.append(replacement["player"])
        if replacements:
            lineup_source = f"{lineup_source} + availability adjustment"

        for player in squad:
            unavailable_row = availability_by_player[player["player"]]
            player["projected_starter"] = int(player["player"] in starters)
            player["projected_formation"] = formation
            player["projection_method"] = lineup_source
            player["observed_start_rate"] = round(start_rates.get(player["player"], 0.0), 4)
            player["lineup_confidence"] = round(lineup_confidence, 4)
            player["lineup_updated_at"] = lineup_context.get(team, {}).get("latest_match_date", "")
            player["availability"] = 0.0 if unavailable_row else 1.0
            player["availability_status"] = unavailable_row.get("category", "") if unavailable_row else "available"
            player["source"] = SQUADS_URL
            player["fetched_at"] = fetched_at
        starter_rows = [player for player in squad if player["projected_starter"]]
        bench_rows = [player for player in squad if not player["projected_starter"]]
        position_counts = {position: sum(player["position"] == position for player in squad) for position in ("GK", "DF", "MF", "FW")}
        balance = min(position_counts["GK"] / 3, 1) + min(position_counts["DF"] / 8, 1) + min(position_counts["MF"] / 7, 1) + min(position_counts["FW"] / 5, 1)
        expected_starter_rows = [player for player in squad if player["player"] in expected_starters]
        expected_starter_weight = sum(player_score(player) for player in expected_starter_rows) or 1.0
        unavailable_starter_weight = sum(player_score(player) for player in expected_starter_rows if not player["availability"])
        team_raw[team] = {
            "roster_value": sum(float(player["market_value_eur"]) for player in squad),
            "xi_value": sum(float(player["market_value_eur"]) for player in starter_rows),
            "bench_value": sum(float(player["market_value_eur"]) for player in bench_rows),
            "experience": sum(float(player["caps"]) for player in squad) / max(len(squad), 1),
            "balance": balance / 4,
            "formation_fit": fit,
            "availability": 1 - (unavailable_starter_weight / expected_starter_weight),
            "lineup_continuity": continuity if lineup_confidence else (70.0 - 55.0) / 41.0,
            "lineup_confidence": lineup_confidence,
            "observed_lineups_count": float(lineup_context.get(team, {}).get("fixture_count", 0)),
        }

    scored = {
        name: percentile_scores({team: math.log1p(values[name]) for team, values in team_raw.items()})
        for name in ("roster_value", "xi_value", "bench_value", "experience")
    }
    features = []
    for team, values in team_raw.items():
        features.append(
            {
                "team": team,
                "roster_value_score": round(scored["roster_value"][team], 2),
                "projected_xi_score": round(scored["xi_value"][team], 2),
                "bench_value_score": round(scored["bench_value"][team], 2),
                "squad_experience": round(scored["experience"][team], 2),
                "squad_balance": round(55 + (41 * values["balance"]), 2),
                "squad_availability": round(55 + (45 * values["availability"]), 2),
                "formation_fit": round(55 + (41 * values["formation_fit"]), 2),
                "lineup_continuity": round(55 + (41 * values["lineup_continuity"]), 2),
                "lineup_confidence": round(100 * values["lineup_confidence"], 2),
                "observed_lineups_count": int(values["observed_lineups_count"]),
            }
        )
    return players, features


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = columns or list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_existing_squads() -> list[dict[str, Any]]:
    rows = []
    with SQUADS_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append(
                {
                    "team": row["team"],
                    "player": row["player"],
                    "position": row["position"],
                    "number": int(row["number"]) if row["number"] else "",
                    "age": int(row["age"]) if row["age"] else "",
                    "birth_date": row["birth_date"],
                    "caps": int(row["caps"]),
                    "international_goals": int(row["international_goals"]),
                    "club": row["club"],
                    "detailed_position": row["detailed_position"],
                    "market_value_eur": float(row["market_value_eur"]),
                    "market_value_updated": row["market_value_updated"],
                }
            )
    return rows


def existing_market_values() -> dict[str, dict[str, Any]]:
    if not SQUADS_PATH.exists():
        return {}
    output = {}
    for player in load_existing_squads():
        output[normalize_name(player["player"])] = {
            "market_value_eur": player["market_value_eur"],
            "market_value_updated": player["market_value_updated"],
            "detailed_position": player["detailed_position"],
        }
    return output


def player_candidates(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    penalty_takers = {}
    for team in {player["team"] for player in players}:
        candidates = [
            player
            for player in players
            if player["team"] == team and player["position"] != "GK" and player["projected_starter"]
        ]
        if candidates:
            penalty_takers[team] = max(
                candidates,
                key=lambda player: (player["international_goals"], player_score(player)),
            )["player"]
    for player in players:
        position_base = {"GK": 1, "DF": 10, "MF": 35, "FW": 65}.get(player["position"], 20)
        scoring_weight = position_base + (45 * player_score(player))
        if not float(player.get("availability", 1.0)):
            scoring_weight *= 0.15
        output.append(
            {
                "team": player["team"],
                "player": player["player"].replace(",", ""),
                "position": player["position"],
                "scoring_weight": round(scoring_weight, 2),
                "starter": player["projected_starter"],
                "penalty_taker": int(penalty_takers.get(player["team"]) == player["player"]),
            }
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch official World Cup squads and build squad-derived features.")
    parser.add_argument("--market-pages", type=int, default=10, help="Transfermarkt World Cup top-market-value pages to fetch.")
    parser.add_argument("--no-market-values", action="store_true", help="Skip optional Transfermarkt enrichment.")
    parser.add_argument("--skip-team-pages", action="store_true", help="Do not enrich from each team detail page.")
    parser.add_argument("--from-existing", action="store_true", help="Rebuild generated features without fetching.")
    args = parser.parse_args()

    if args.from_existing:
        players = load_existing_squads()
        matched = sum(player["market_value_eur"] > 0 for player in players)
    else:
        players = official_squads()
        values = {} if args.no_market_values else market_values(args.market_pages, not args.skip_team_pages)
        fallback_values = existing_market_values()
        matched = 0
        for player in players:
            value = values.get(normalize_name(player["player"])) or fallback_values.get(normalize_name(player["player"]), {})
            player.update(
                {
                    "detailed_position": value.get("detailed_position", ""),
                    "market_value_eur": value.get("market_value_eur", 0.0),
                    "market_value_updated": value.get("market_value_updated", ""),
                }
            )
            matched += int(bool(value))

    fetched_at = datetime.now(timezone.utc).isoformat()
    players, features = build_outputs(players, fetched_at)
    player_match_rows, player_match_team_features = build_player_match_outputs(players, fetched_at)
    write_csv(SQUADS_PATH, players)
    write_csv(SQUAD_FEATURES_PATH, features)
    write_csv(PLAYER_MATCH_STATS_PATH, player_match_rows, PLAYER_MATCH_STATS_COLUMNS)
    write_csv(PLAYER_MATCH_TEAM_FEATURES_PATH, player_match_team_features, PLAYER_MATCH_TEAM_FEATURE_COLUMNS)
    write_csv(
        PLAYER_CANDIDATES_PATH,
        player_candidates(players),
        ["team", "player", "position", "scoring_weight", "starter", "penalty_taker"],
    )
    roster_counts = Counter(player["team"] for player in players)
    open_slots = {team: 26 - count for team, count in roster_counts.items() if count < 26}
    print(f"Official squad players: {len(players)}")
    print(f"Teams: {len(features)}")
    if open_slots:
        print("Current roster slots below 26: " + ", ".join(f"{team}={slots}" for team, slots in sorted(open_slots.items())))
    print(f"Market-value matches: {matched}/{len(players)}")
    print(f"Saved {SQUADS_PATH}")
    print(f"Saved {SQUAD_FEATURES_PATH}")
    print(f"Saved {PLAYER_MATCH_STATS_PATH}")
    print(f"Saved {PLAYER_MATCH_TEAM_FEATURES_PATH}")
    print(f"Updated {PLAYER_CANDIDATES_PATH}")


if __name__ == "__main__":
    main()
