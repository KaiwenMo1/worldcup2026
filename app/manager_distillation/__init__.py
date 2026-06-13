"""Nuwa-inspired, evidence-backed football manager skill distillation."""

from app.manager_distillation.evidence_loader import (
    EvidenceLoadResult,
    load_csv_evidence,
    load_evidence_directory,
    load_markdown_document,
)
from app.manager_distillation.schemas import (
    ClaimType,
    DistilledClaim,
    DistilledManagerSkill,
    EvidenceCategory,
    EvidenceDocument,
    EvidenceRecord,
    ManagerSkillValidationReport,
)
from app.manager_distillation.skill_builder import HONEST_BOUNDARIES, build_manager_skill
from app.manager_distillation.skill_exporter import (
    export_tactical_json,
    load_distilled_skill,
    render_skill_markdown,
    render_validation_report,
    to_tactical_manager_skill,
    write_generated_skill,
)
from app.manager_distillation.validation import validate_manager_skill

__all__ = [
    "ClaimType",
    "DistilledClaim",
    "DistilledManagerSkill",
    "EvidenceCategory",
    "EvidenceDocument",
    "EvidenceLoadResult",
    "EvidenceRecord",
    "HONEST_BOUNDARIES",
    "ManagerSkillValidationReport",
    "build_manager_skill",
    "export_tactical_json",
    "load_csv_evidence",
    "load_distilled_skill",
    "load_evidence_directory",
    "load_markdown_document",
    "render_skill_markdown",
    "render_validation_report",
    "to_tactical_manager_skill",
    "validate_manager_skill",
    "write_generated_skill",
]
