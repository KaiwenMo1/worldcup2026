#!/usr/bin/env python3
"""Build transparent derived manager-skill baselines for the 48-team field."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MANAGERS_PATH = ROOT / "data" / "managers.csv"
TACTICAL_PROFILES_PATH = ROOT / "data" / "tactical_profiles.csv"
TEAM_FEATURES_PATH = ROOT / "data" / "team_features.csv"
TEAM_ADVANCED_PATH = ROOT / "data" / "team_advanced_features.csv"
SQUAD_FEATURES_PATH = ROOT / "data" / "squad_features.csv"
MANAGER_SKILLS_DIR = ROOT / "data" / "manager_skills"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key) or default)
    except (TypeError, ValueError):
        return default


def level(value: float, *, high: float = 78, low: float = 62) -> str:
    return "high" if value >= high else "selective" if value >= low else "low"


def primary_style(pressing: float, build_up: float, transition: float, flexibility: float) -> str:
    if transition >= 82 and pressing >= 75:
        return "high_press_transition"
    if build_up >= 78 and flexibility >= 78:
        return "controlled_adaptive_build_up"
    if transition >= 82:
        return "direct_transition"
    if pressing >= 78:
        return "front_foot_pressing"
    return "balanced_adaptive"


def identity(profile: dict[str, str], advanced: dict[str, str]) -> dict[str, Any]:
    pressing = number(profile, "pressing", number(advanced, "pressing_intensity", 65))
    build_up = number(profile, "build_up", 65)
    transition = number(profile, "transition", number(advanced, "transition_speed", 68))
    defensive_line = number(profile, "defensive_line", 65)
    width = number(profile, "width", 68)
    set_piece = number(advanced, "set_piece_attack", 65)
    flexibility = number(advanced, "tactical_flexibility", 65)
    press_level = level(pressing)
    formation = profile.get("formation") or "4-3-3"
    return {
        "primary_style": primary_style(pressing, build_up, transition, flexibility),
        "preferred_formations": [formation],
        "build_up": "progressive_short_build_up" if build_up >= 75 else "mixed_build_up" if build_up >= 60 else "direct_build_up",
        "defensive_shape": "high_defensive_line" if defensive_line >= 78 else "compact_mid_block" if defensive_line >= 62 else "deep_compact_block",
        "pressing": press_level,
        "transition": "fast_vertical_attack" if transition >= 78 else "balanced_transition" if transition >= 62 else "controlled_rest_defense",
        "set_pieces": "positive_set_piece_emphasis" if set_piece >= 78 else "balanced_set_piece_plan",
        "in_possession": [
            "progress through the strongest available player-role combinations",
            "use wide overloads" if width >= 72 else "protect central connections before accelerating",
        ],
        "out_of_possession": [
            f"use a {press_level} press derived from the current team profile",
            "hold an aggressive line" if defensive_line >= 78 else "protect central space in a compact block",
        ],
        "transition_actions": [
            "attack quickly after regains" if transition >= 75 else "secure the first pass after regains",
            "preserve rest-defense coverage behind attacks",
        ],
        "set_piece_actions": [
            "commit aerial threats to high-value delivery zones" if set_piece >= 78 else "use balanced dead-ball routines",
            "retain counterattack protection",
        ],
    }


def decision_rules(profile: dict[str, str], advanced: dict[str, str]) -> list[dict[str, Any]]:
    transition = number(profile, "transition", number(advanced, "transition_speed", 68))
    flexibility = number(advanced, "tactical_flexibility", 65)
    rules = [
        {
            "condition_code": "opponent_high_press",
            "parameters": {},
            "recommendation": "create a first-line spare and use the strongest progressive passers before playing direct",
            "evidence_confidence": 0.32,
            "source_refs": [],
            "last_verified": None,
            "sample_size": None,
        },
        {
            "condition_code": "leading_after_minute",
            "parameters": {"minute": 70},
            "recommendation": "reduce avoidable possession risk and protect central transition lanes",
            "evidence_confidence": 0.28,
            "source_refs": [],
            "last_verified": None,
            "sample_size": None,
        },
        {
            "condition_code": "trailing_after_minute",
            "parameters": {"minute": 55},
            "recommendation": "increase attacking occupation and introduce the highest-impact available creator or scorer",
            "evidence_confidence": 0.28,
            "source_refs": [],
            "last_verified": None,
            "sample_size": None,
        },
    ]
    if transition >= 72:
        rules.append(
            {
                "condition_code": "opponent_high_line",
                "parameters": {"recovery_defender_score_max": 75},
                "recommendation": "release the fastest transition runners behind the opponent line",
                "evidence_confidence": 0.34,
                "source_refs": [],
                "last_verified": None,
                "sample_size": None,
            }
        )
    if flexibility >= 75:
        rules.append(
            {
                "condition_code": "knockout_match",
                "parameters": {},
                "recommendation": "keep a flexible shape and preserve a credible late-game formation switch",
                "evidence_confidence": 0.30,
                "source_refs": [],
                "last_verified": None,
                "sample_size": None,
            }
        )
    return rules


def baseline(manager: dict[str, str], sources: dict[str, dict[str, dict[str, str]]]) -> dict[str, Any]:
    team = manager["team"]
    profile = sources["tactical"].get(team, {})
    advanced = sources["advanced"].get(team, {})
    squad = sources["squad"].get(team, {})
    bench = number(squad, "bench_value_score", 65)
    flexibility = number(advanced, "tactical_flexibility", 65)
    source_ref = {
        "source_id": f"derived_team_profile_{team.lower().replace(' ', '_')}",
        "title": f"{team} derived tactical and player profile",
        "url": None,
        "observed_at": date(2026, 6, 5).isoformat(),
        "note": "Derived from projected squad and team feature files; not observed manager-match evidence.",
    }
    return {
        "manager_id": manager["manager_id"],
        "manager_name": manager["manager_name"],
        "team": team,
        "skill_name": f"{team} derived manager-team tactical baseline",
        "version": "0.1-derived",
        "status": "manual_prototype",
        "last_verified": manager.get("last_verified") or None,
        "source_refs": [source_ref],
        "tactical_identity": identity(profile, advanced),
        "decision_rules": decision_rules(profile, advanced),
        "substitution_patterns": [
            {
                "match_state": "leading",
                "likely_sub_type": "defensive stabilizer or fresh transition runner",
                "minute_window": "65-80",
                "evidence_confidence": 0.25,
                "source_refs": [],
            },
            {
                "match_state": "tied",
                "likely_sub_type": "highest-impact creator or role-specific replacement",
                "minute_window": "60-75",
                "evidence_confidence": round(0.24 + min(flexibility, 100) / 1000, 3),
                "source_refs": [],
            },
            {
                "match_state": "trailing",
                "likely_sub_type": "additional scorer or attacking creator",
                "minute_window": "50-70" if bench >= 75 else "55-75",
                "evidence_confidence": round(0.24 + min(bench, 100) / 1000, 3),
                "source_refs": [],
            },
        ],
        "evidence_notes": [
            "Derived manager-team baseline for AI reasoning coverage.",
            "This is not observed manager behavior and must remain manual_prototype until recurring manager-match evidence is ingested.",
            "Player-role and team-profile deductions can explain forecasts but do not independently prove managerial intent.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build derived tactical baselines for managers missing a skill.")
    parser.add_argument("--apply", action="store_true", help="Write generated manager-skill JSON files.")
    parser.add_argument("--replace-derived", action="store_true", help="Replace only existing 0.1-derived baselines.")
    args = parser.parse_args()

    from app.tactics.schemas import ManagerSkill

    managers = read_csv(MANAGERS_PATH)
    sources = {
        "tactical": {row["team"]: row for row in read_csv(TACTICAL_PROFILES_PATH)},
        "team": {row["team"]: row for row in read_csv(TEAM_FEATURES_PATH)},
        "advanced": {row["team"]: row for row in read_csv(TEAM_ADVANCED_PATH)},
        "squad": {row["team"]: row for row in read_csv(SQUAD_FEATURES_PATH)},
    }
    MANAGER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    generated = skipped = 0
    for manager in managers:
        path = MANAGER_SKILLS_DIR / f"{manager['manager_id']}.json"
        if path.exists():
            current = json.loads(path.read_text(encoding="utf-8"))
            if not (args.replace_derived and current.get("version") == "0.1-derived"):
                skipped += 1
                continue
        payload = baseline(manager, sources)
        try:
            validated = ManagerSkill.model_validate(payload)
        except ValidationError as exc:
            raise SystemExit(f"Could not validate {manager['manager_id']}: {exc}") from exc
        generated += 1
        if args.apply:
            path.write_text(json.dumps(validated.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    action = "wrote" if args.apply else "would write"
    print(f"{action} {generated} derived manager baselines; preserved {skipped} existing skills")


if __name__ == "__main__":
    main()
