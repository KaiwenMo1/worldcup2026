#!/usr/bin/env python3
"""Build stable player identities across squads and optional provider exports."""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from pathlib import Path
from typing import Any

from predict_worldcup import ROOT


SQUADS_PATH = ROOT / "data" / "worldcup_squads.csv"
OUTPUT_PATH = ROOT / "data" / "player_identity_map.csv"
FIELDS = [
    "player_id",
    "team",
    "canonical_name",
    "normalized_name",
    "club",
    "birth_date",
    "provider",
    "provider_player_id",
    "source",
    "match_confidence",
    "status",
]


def normalized(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def player_id(team: str, player: str) -> str:
    text = unicodedata.normalize("NFKD", f"{team}_{player}").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_map(squads: list[dict[str, str]], provider_rows: list[dict[str, str]], provider: str) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    by_team_name = {}
    for squad in squads:
        key = player_id(squad.get("team", ""), squad.get("player", ""))
        row = {
            "player_id": key,
            "team": squad.get("team", ""),
            "canonical_name": squad.get("player", ""),
            "normalized_name": normalized(squad.get("player", "")),
            "club": squad.get("club", ""),
            "birth_date": squad.get("birth_date", ""),
            "provider": "",
            "provider_player_id": "",
            "source": squad.get("source") or "worldcup_squads",
            "match_confidence": 1.0,
            "status": "canonical_squad_identity",
        }
        rows[key] = row
        by_team_name[(normalized(row["team"]), row["normalized_name"])] = key

    for item in provider_rows:
        key = by_team_name.get((normalized(item.get("team", "")), normalized(item.get("player", ""))))
        if not key:
            continue
        rows[key].update(
            {
                "provider": provider,
                "provider_player_id": item.get("provider_player_id") or item.get("player_id") or "",
                "source": item.get("source") or provider,
                "match_confidence": 1.0,
                "status": "provider_linked",
            }
        )
    return sorted(rows.values(), key=lambda row: (row["team"], row["canonical_name"]))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build stable player identities from squads and provider data.")
    parser.add_argument("--provider-csv", type=Path)
    parser.add_argument("--provider", default="provider")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    rows = build_map(read_csv(SQUADS_PATH), read_csv(args.provider_csv) if args.provider_csv else [], args.provider)
    write_csv(args.output, rows)
    linked = sum(bool(row["provider_player_id"]) for row in rows)
    print(f"Saved {args.output} ({linked}/{len(rows)} provider-linked identities)")


if __name__ == "__main__":
    main()
