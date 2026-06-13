"""Report observed-versus-estimated tactical data coverage."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from app.tactics.manager_skills import load_team_manager_record, load_team_manager_skill
from app.tactics.player_profiles import load_player_availability, load_player_profiles, load_projected_lineup
from app.tactics.schemas import TacticalDataCoverage


ROOT = Path(__file__).resolve().parents[2]
MANAGER_FEATURES_PATH = ROOT / "data" / "manager_features.csv"
PLAYER_IDENTITY_MAP_PATH = ROOT / "data" / "player_identity_map.csv"
FEATURE_GATE_PATH = ROOT / "data" / "context_feature_gate.json"


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_context_feature_gate() -> dict[str, Any]:
    if not FEATURE_GATE_PATH.exists():
        return {
            "enabled": False,
            "reason": "Context feature gate file is missing.",
            "coverage": 0.0,
        }
    try:
        return json.loads(FEATURE_GATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "enabled": False,
            "reason": "Context feature gate could not be validated.",
            "coverage": 0.0,
        }


def team_data_coverage(team: str, match_id: str | None = None) -> TacticalDataCoverage:
    registry = load_team_manager_record(team)
    manager_skill = load_team_manager_skill(team)
    manager_feature = next(
        (row for row in _rows(MANAGER_FEATURES_PATH) if row.get("team", "").casefold() == team.casefold()),
        None,
    )
    profiles = [profile for profile in load_player_profiles().values() if profile.team.casefold() == team.casefold()]
    observed = [
        profile
        for profile in profiles
        if profile.data_quality in {"observed", "observed_provider", "evidence_backed"}
        or profile.source not in {"estimated_from_squad_profile", "derived_player_match_stats"}
        and not profile.source.startswith("manual")
    ]
    estimated = [profile for profile in profiles if profile not in observed]
    lineup = load_projected_lineup(team, match_id)
    availability = [
        item for item in load_player_availability().values() if item.team.casefold() == team.casefold()
    ]
    identities = [
        row for row in _rows(PLAYER_IDENTITY_MAP_PATH) if row.get("team", "").casefold() == team.casefold()
    ]
    provider_linked = sum(bool(row.get("provider_player_id")) for row in identities)
    gate = load_context_feature_gate()
    manager_quality = (manager_feature or {}).get("data_quality")
    if not manager_quality:
        manager_quality = manager_skill.status if manager_skill else "registry_only" if registry else "missing"
    notes = []
    if registry and not manager_skill:
        notes.append("Current manager is registered, but no validated tactical skill profile is available.")
    if not observed:
        notes.append("Player matchup profiles are currently estimated or manually curated, not provider-observed.")
    if not gate.get("enabled"):
        notes.append("Observed manager/player context is explanation-only until the chronological feature gate passes.")
    return TacticalDataCoverage(
        team=team,
        manager_registered=registry is not None,
        manager_skill_available=manager_skill is not None,
        manager_history_matches=int((manager_feature or {}).get("sample_size") or 0),
        manager_data_quality=manager_quality,
        player_profiles=len(profiles),
        observed_player_profiles=len(observed),
        estimated_player_profiles=len(estimated),
        player_observed_coverage=round(len(observed) / len(profiles), 3) if profiles else 0.0,
        projected_lineup_players=len(lineup),
        availability_entries=len(availability),
        identity_mapped_players=len(identities),
        provider_linked_identities=provider_linked,
        context_feature_gate_enabled=bool(gate.get("enabled")),
        context_feature_gate_reason=str(gate.get("reason") or "No gate reason available."),
        notes=notes,
    )
