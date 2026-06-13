"""Validate whether a distilled manager skill is ready for use."""

from __future__ import annotations

from app.manager_distillation.schemas import (
    DistilledManagerSkill,
    ManagerSkillValidationReport,
    ValidationCheck,
)
from app.manager_distillation.skill_builder import HONEST_BOUNDARIES


def validate_manager_skill(skill: DistilledManagerSkill) -> ManagerSkillValidationReport:
    core_evidence = all(claim.evidence_ids for claim in [*skill.core_tactical_models, *skill.decision_heuristics])
    boundaries = all(boundary in skill.honest_boundaries for boundary in HONEST_BOUNDARIES)
    checks = [
        ValidationCheck(
            name="core_tactical_models",
            passed=len(skill.core_tactical_models) >= 3,
            severity="warning",
            detail=f"Found {len(skill.core_tactical_models)}; at least 3 are required for PASS.",
        ),
        ValidationCheck(
            name="decision_heuristics",
            passed=len(skill.decision_heuristics) >= 5,
            severity="warning",
            detail=f"Found {len(skill.decision_heuristics)}; at least 5 are required for PASS.",
        ),
        ValidationCheck(
            name="core_rule_evidence",
            passed=core_evidence,
            severity="error",
            detail="Every core tactical rule must reference evidence IDs.",
        ),
        ValidationCheck(
            name="honest_boundaries",
            passed=boundaries,
            severity="error",
            detail="All required honest boundaries must be present.",
        ),
        ValidationCheck(
            name="sources",
            passed=bool(skill.sources),
            severity="error",
            detail="At least one evidence source is required.",
        ),
    ]
    if any(not check.passed and check.severity == "error" for check in checks):
        status = "FAIL"
    elif any(not check.passed for check in checks):
        status = "WARN"
    else:
        status = "PASS"
    evidence_ids = {
        evidence_id
        for claim in [*skill.core_tactical_models, *skill.decision_heuristics, *skill.low_confidence_heuristics]
        for evidence_id in claim.evidence_ids
    }
    return ManagerSkillValidationReport(
        manager_id=skill.manager_id,
        status=status,
        checks=checks,
        core_tactical_models=len(skill.core_tactical_models),
        decision_heuristics=len(skill.decision_heuristics),
        low_confidence_heuristics=len(skill.low_confidence_heuristics),
        source_count=len(skill.sources),
        evidence_count=len(evidence_ids),
    )
