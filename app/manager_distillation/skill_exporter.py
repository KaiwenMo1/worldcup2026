"""Render distilled manager skills and export app-compatible tactical JSON."""

from __future__ import annotations

import json
from pathlib import Path

from app.manager_distillation.schemas import (
    ClaimType,
    DistilledClaim,
    DistilledManagerSkill,
    ManagerSkillValidationReport,
)
from app.manager_distillation.validation import validate_manager_skill
from app.tactics.schemas import (
    DecisionRule,
    EvidenceReference,
    ManagerSkill,
    SubstitutionPattern,
    TacticalIdentity,
)


ROOT = Path(__file__).resolve().parents[2]
GENERATED_SKILLS_DIR = ROOT / "data" / "manager_distillation" / "generated_skills"
TACTICAL_SKILLS_DIR = ROOT / "data" / "manager_skills"


def load_distilled_skill(path: Path) -> DistilledManagerSkill:
    return DistilledManagerSkill.model_validate_json(path.read_text(encoding="utf-8"))


def _claim_lines(claims: list[DistilledClaim]) -> list[str]:
    if not claims:
        return ["- None validated yet."]
    return [
        (
            f"- **{claim.claim_id}**: {claim.claim_text} "
            f"(confidence `{claim.confidence:.2f}`, evidence: {', '.join(claim.evidence_ids)})"
        )
        for claim in claims
    ]


def render_skill_markdown(skill: DistilledManagerSkill, report: ManagerSkillValidationReport) -> str:
    identity = skill.tactical_identity
    source_lines = [
        f"- `{source.source_id}`: {source.title}" + (f" ({source.url})" if source.url else "")
        for source in skill.sources
    ] or ["- No sources loaded."]
    return "\n".join(
        [
            "---",
            f"name: {skill.manager_id}-tactical-perspective",
            (
                f"description: Evidence-backed tactical perspective for {skill.manager_name} and {skill.team}. "
                f"Use when analyzing likely formations, game-state decisions, substitutions, and tactical matchups."
            ),
            "---",
            "",
            f"# {skill.manager_name}: Tactical Skill",
            "",
            f"Validation status: **{report.status}**",
            "",
            "This skill is a versioned public-evidence hypothesis, not a claim about private intent.",
            "",
            "## Tactical Identity",
            "",
            f"- Primary style: `{identity.primary_style}`",
            f"- Preferred formations: {', '.join(identity.preferred_formations)}",
            f"- Build-up: `{identity.build_up}`",
            f"- Defensive shape: `{identity.defensive_shape}`",
            f"- Pressing: `{identity.pressing}`",
            f"- Transition: `{identity.transition}`",
            f"- Set pieces: `{identity.set_pieces}`",
            "",
            "## Core Tactical Models",
            "",
            *_claim_lines(skill.core_tactical_models),
            "",
            "## Decision Heuristics",
            "",
            *_claim_lines(skill.decision_heuristics),
            "",
            "## Low-Confidence Heuristics",
            "",
            *_claim_lines(skill.low_confidence_heuristics),
            "",
            "## Player Archetype Preferences",
            "",
            *([f"- {item}" for item in skill.player_archetype_preferences] or ["- Insufficient evidence."]),
            "",
            "## Anti-Patterns",
            "",
            *([f"- {item}" for item in skill.anti_patterns] or ["- Insufficient evidence."]),
            "",
            "## Expression DNA",
            "",
            *([f"- {item}" for item in skill.expression_dna] or ["- Insufficient evidence."]),
            "",
            "## Honest Boundaries",
            "",
            *[f"- {item}" for item in skill.honest_boundaries],
            "",
            "## Sources",
            "",
            *source_lines,
            "",
        ]
    )


def render_validation_report(report: ManagerSkillValidationReport) -> str:
    lines = [
        f"# Validation Report: {report.manager_id}",
        "",
        f"Status: **{report.status}**",
        "",
        f"- Core tactical models: {report.core_tactical_models}",
        f"- Decision heuristics: {report.decision_heuristics}",
        f"- Low-confidence heuristics: {report.low_confidence_heuristics}",
        f"- Evidence records: {report.evidence_count}",
        f"- Sources: {report.source_count}",
        "",
        "## Checks",
        "",
    ]
    lines.extend(
        f"- [{'x' if check.passed else ' '}] **{check.name}** ({check.severity}): {check.detail}"
        for check in report.checks
    )
    return "\n".join(lines) + "\n"


def write_generated_skill(
    skill: DistilledManagerSkill,
    report: ManagerSkillValidationReport | None = None,
    output_root: Path = GENERATED_SKILLS_DIR,
) -> Path:
    report = report or validate_manager_skill(skill)
    output = output_root / skill.manager_id
    output.mkdir(parents=True, exist_ok=True)
    (output / "manager_skill_draft.json").write_text(skill.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (output / "SKILL.md").write_text(render_skill_markdown(skill, report), encoding="utf-8")
    (output / "validation_report.md").write_text(render_validation_report(report), encoding="utf-8")
    return output


def _source_refs(skill: DistilledManagerSkill, claim: DistilledClaim | None = None) -> list[EvidenceReference]:
    allowed = set(claim.source_ids) if claim else {source.source_id for source in skill.sources}
    return [
        EvidenceReference(
            source_id=source.source_id,
            title=source.title,
            url=source.url,
            observed_at=source.observed_at,
            note="Public evidence used by the manager distillation pipeline.",
        )
        for source in skill.sources
        if source.source_id in allowed
    ]


def _actions(skill: DistilledManagerSkill, claim_type: ClaimType) -> list[str]:
    return [claim.claim_text for claim in skill.core_tactical_models if claim.claim_type == claim_type]


def to_tactical_manager_skill(
    skill: DistilledManagerSkill,
    report: ManagerSkillValidationReport | None = None,
) -> ManagerSkill:
    report = report or validate_manager_skill(skill)
    identity = skill.tactical_identity
    decisions = [
        DecisionRule(
            condition_code=claim.condition_code,
            parameters=claim.parameters,
            recommendation=claim.claim_text,
            evidence_confidence=claim.confidence,
            source_refs=_source_refs(skill, claim),
            sample_size=len(claim.evidence_ids),
        )
        for claim in skill.decision_heuristics
        if claim.condition_code is not None
    ]
    substitutions = [
        SubstitutionPattern(
            match_state=claim.match_state,
            likely_sub_type=claim.normalized_value or claim.claim_text,
            minute_window=claim.minute_window,
            evidence_confidence=claim.confidence,
            source_refs=_source_refs(skill, claim),
        )
        for claim in skill.core_tactical_models
        if claim.claim_type == ClaimType.SUBSTITUTION_PATTERN and claim.match_state and claim.minute_window
    ]
    low_notes = [f"Low-confidence {claim.claim_id}: {claim.claim_text}" for claim in skill.low_confidence_heuristics]
    return ManagerSkill(
        manager_id=skill.manager_id,
        manager_name=skill.manager_name,
        team=skill.team,
        skill_name=f"{skill.team} evidence-backed manager tactical skill",
        version=skill.version,
        status="evidence_backed" if report.status == "PASS" else "manual_prototype",
        source_refs=_source_refs(skill),
        tactical_identity=TacticalIdentity(
            primary_style=identity.primary_style,
            preferred_formations=identity.preferred_formations,
            build_up=identity.build_up,
            defensive_shape=identity.defensive_shape,
            pressing=identity.pressing,
            transition=identity.transition,
            set_pieces=identity.set_pieces,
            in_possession=_actions(skill, ClaimType.IN_POSSESSION_RULE),
            out_of_possession=_actions(skill, ClaimType.OUT_OF_POSSESSION_RULE),
            transition_actions=_actions(skill, ClaimType.TRANSITION_RULE),
            set_piece_actions=_actions(skill, ClaimType.SET_PIECE_TENDENCY),
        ),
        decision_rules=decisions,
        substitution_patterns=substitutions,
        evidence_notes=[
            f"Distillation validation status: {report.status}.",
            *skill.honest_boundaries,
            *skill.evidence_notes,
            *low_notes,
        ],
    )


def export_tactical_json(
    skill: DistilledManagerSkill,
    *,
    apply: bool = False,
    target_dir: Path = TACTICAL_SKILLS_DIR,
    generated_root: Path = GENERATED_SKILLS_DIR,
) -> Path:
    tactical = to_tactical_manager_skill(skill)
    target = target_dir / f"{skill.manager_id}.json"
    if target.exists() and not apply:
        target = generated_root / skill.manager_id / "manager_skill.preview.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(tactical.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return target
