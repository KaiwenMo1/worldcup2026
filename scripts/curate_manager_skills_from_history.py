#!/usr/bin/env python3
"""Enrich manager skills with observed historical manager-match evidence."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from app.ingestion.normalizers import safe_write_csv  # noqa: E402
from app.tactics.schemas import EvidenceReference, ManagerSkill, TacticalIdentity  # noqa: E402
from scripts.distill_manager_profiles import distill, read_csv, write_csv as write_manager_features  # noqa: E402


MANAGERS_PATH = ROOT / "data" / "managers.csv"
HISTORY_PATH = ROOT / "data" / "manager_match_history.csv"
FEATURES_PATH = ROOT / "data" / "manager_features.csv"
SKILLS_DIR = ROOT / "data" / "manager_skills"
COVERAGE_PATH = ROOT / "data" / "derived" / "manager_curation_coverage.csv"
COVERAGE_FIELDS = [
    "manager_id",
    "manager_name",
    "team",
    "observed_matches",
    "evidence_confidence",
    "curation_status",
    "skill_version",
    "latest_observation",
    "source",
    "next_action",
]


def number(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key) or default)
    except (TypeError, ValueError):
        return default


def unique_notes(notes: list[str]) -> list[str]:
    """Preserve note order while keeping repeated curation runs idempotent."""
    return list(dict.fromkeys(note for note in notes if note))


def identity_from_observed(feature: dict[str, str], fallback: TacticalIdentity) -> TacticalIdentity:
    pressing = number(feature, "pressing_score", 50)
    possession = number(feature, "possession_score", 50)
    directness = number(feature, "build_up_directness_score", 50)
    transition = number(feature, "transition_score", 50)
    line = number(feature, "defensive_line_score", 50)
    set_piece = number(feature, "set_piece_score", 25)
    if pressing >= 70 and transition >= 60:
        style = "observed_high_press_transition"
    elif possession >= 57 and directness < 58:
        style = "observed_controlled_possession"
    elif directness >= 65 or transition >= 68:
        style = "observed_direct_transition"
    else:
        style = "observed_balanced_adaptive"
    formation = feature.get("preferred_formation") or fallback.preferred_formations[0]
    return TacticalIdentity(
        primary_style=style,
        preferred_formations=[formation],
        build_up=(
            "patient_progression_from_observed_matches"
            if directness < 45
            else "mixed_progression_from_observed_matches"
            if directness < 65
            else "direct_progression_from_observed_matches"
        ),
        defensive_shape=(
            "observed_high_line" if line >= 62 else "observed_mid_block" if line >= 45 else "observed_deeper_block"
        ),
        pressing="observed_high" if pressing >= 70 else "observed_selective" if pressing >= 45 else "observed_low",
        transition="observed_fast" if transition >= 65 else "observed_balanced" if transition >= 40 else "observed_controlled",
        set_pieces="observed_positive_emphasis" if set_piece >= 40 else "observed_balanced_emphasis",
        in_possession=[
            *fallback.in_possession[:1],
            f"observed possession profile score {possession:.1f} and build-up directness score {directness:.1f}",
        ],
        out_of_possession=[
            *fallback.out_of_possession[:1],
            f"observed pressing score {pressing:.1f} and defensive-line score {line:.1f}",
        ],
        transition_actions=[
            *fallback.transition_actions[:1],
            f"observed transition score {transition:.1f}",
        ],
        set_piece_actions=[
            *fallback.set_piece_actions[:1],
            f"observed set-piece score {set_piece:.1f}",
        ],
    )


def curate_skill(skill: ManagerSkill, feature: dict[str, str]) -> ManagerSkill:
    sample_size = int(number(feature, "sample_size"))
    if sample_size <= 0:
        return skill
    confidence = number(feature, "evidence_confidence")
    source = EvidenceReference(
        source_id=f"statsbomb_manager_history_{skill.manager_id}",
        title=f"{skill.manager_name} observed manager-match sample",
        url="https://github.com/statsbomb/open-data",
        observed_at=date.fromisoformat(feature["last_observed"]) if feature.get("last_observed") else None,
        note=(
            f"Transparent aggregate from {sample_size} observed historical matches. Historical clubs or national teams "
            "may differ from the manager's current World Cup squad."
        ),
    )
    decision_rules = [
        rule.model_copy(
            update={
                "evidence_confidence": round(min(rule.evidence_confidence, max(0.35, confidence)), 3),
                "source_refs": [source],
                "sample_size": sample_size,
                "last_verified": source.observed_at,
            }
        )
        for rule in skill.decision_rules
    ]
    substitution_patterns = [
        pattern.model_copy(
            update={
                "evidence_confidence": round(min(pattern.evidence_confidence, max(0.35, confidence)), 3),
                "source_refs": [source],
            }
        )
        for pattern in skill.substitution_patterns
    ]
    status = "evidence_backed" if sample_size >= 10 else "manual_prototype"
    return skill.model_copy(
        update={
            "skill_name": f"{skill.team} observed-history manager tactical skill",
            "version": "0.2-statsbomb-observed",
            "status": status,
            "last_verified": source.observed_at,
            "source_refs": [source],
            "tactical_identity": identity_from_observed(feature, skill.tactical_identity),
            "decision_rules": decision_rules,
            "substitution_patterns": substitution_patterns,
            "evidence_notes": unique_notes([
                f"Observed history contains {sample_size} StatsBomb Open Data matches; evidence confidence {confidence:.3f}.",
                "Observed aggregate metrics support the tactical identity, but conditional decision rules remain hypotheses.",
                "Historical team context may not transfer fully to the current World Cup squad.",
                *skill.evidence_notes,
            ]),
        }
    )


def curate(*, apply: bool) -> list[dict[str, Any]]:
    managers = read_csv(MANAGERS_PATH)
    history = read_csv(HISTORY_PATH)
    features = distill(managers, history)
    write_manager_features(FEATURES_PATH, features)
    by_id = {row["manager_id"]: row for row in features}
    coverage = []
    for manager in managers:
        feature = by_id[manager["manager_id"]]
        path = SKILLS_DIR / f"{manager['manager_id']}.json"
        skill = ManagerSkill.model_validate_json(path.read_text(encoding="utf-8"))
        curated = curate_skill(skill, feature)
        sample_size = int(number(feature, "sample_size"))
        if apply and sample_size:
            path.write_text(json.dumps(curated.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
        coverage.append(
            {
                "manager_id": manager["manager_id"],
                "manager_name": manager["manager_name"],
                "team": manager["team"],
                "observed_matches": sample_size,
                "evidence_confidence": feature["evidence_confidence"],
                "curation_status": (
                    "evidence_backed" if sample_size >= 10 else "limited_observed" if sample_size else "research_gap"
                ),
                "skill_version": curated.version if sample_size else skill.version,
                "latest_observation": feature["last_observed"],
                "source": feature["source"],
                "next_action": (
                    "review observed tactical identity and add public tactical sources"
                    if sample_size
                    else "acquire manager-specific match events and public tactical sources"
                ),
            }
        )
    result = safe_write_csv(COVERAGE_PATH, coverage, COVERAGE_FIELDS)
    if not result.ok:
        raise RuntimeError("; ".join(issue.problem for issue in result.issues))
    return coverage


def main() -> None:
    parser = argparse.ArgumentParser(description="Curate manager skills from observed manager-match history.")
    parser.add_argument("--apply", action="store_true", help="Apply observed enrichments to manager-skill JSON files.")
    args = parser.parse_args()
    coverage = curate(apply=args.apply)
    evidence_backed = sum(row["curation_status"] == "evidence_backed" for row in coverage)
    limited = sum(row["curation_status"] == "limited_observed" for row in coverage)
    gaps = sum(row["curation_status"] == "research_gap" for row in coverage)
    print(f"Manager curation coverage: {evidence_backed} evidence-backed, {limited} limited observed, {gaps} research gaps")
    if not args.apply:
        print("Dry run only. Pass --apply to update manager-skill JSON files.")


if __name__ == "__main__":
    main()
