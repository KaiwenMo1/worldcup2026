"""Optional research-agent tooling for local evidence collection."""

from app.research_tools.football_research_scout import (
    RESEARCH_EVIDENCE_INDEX_PATH,
    RESEARCH_EVIDENCE_RAW_DIR,
    ResearchCollectionResult,
    build_manager_evidence_template_row,
    collect_public_evidence,
    extract_markdown_from_html,
    write_research_documents,
)
from app.research_tools.registry import (
    detect_research_tools,
    recommended_research_workflow,
    research_tool_catalog,
    research_tool_summary,
)
from app.research_tools.schemas import (
    DetectedResearchTool,
    ResearchEvidenceDocument,
    ResearchTool,
    ResearchToolCategory,
    ResearchToolScope,
)

__all__ = [
    "DetectedResearchTool",
    "RESEARCH_EVIDENCE_INDEX_PATH",
    "RESEARCH_EVIDENCE_RAW_DIR",
    "ResearchCollectionResult",
    "ResearchEvidenceDocument",
    "ResearchTool",
    "ResearchToolCategory",
    "ResearchToolScope",
    "build_manager_evidence_template_row",
    "collect_public_evidence",
    "detect_research_tools",
    "extract_markdown_from_html",
    "recommended_research_workflow",
    "research_tool_catalog",
    "research_tool_summary",
    "write_research_documents",
]
