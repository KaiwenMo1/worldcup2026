"""Optional research-agent tooling for local evidence collection."""

from app.research_tools.agent_reach_workflow import (
    AGENT_REACH_INBOX_DIR,
    AGENT_REACH_PLAN_PATH,
    AGENT_REACH_REVIEW_QUEUE_PATH,
    AgentReachImportResult,
    build_agent_reach_research_tasks,
    document_from_agent_reach_markdown,
    import_agent_reach_markdown,
    write_agent_reach_plan,
)
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
    AgentReachResearchTask,
    DetectedResearchTool,
    ResearchEvidenceDocument,
    ResearchTool,
    ResearchToolCategory,
    ResearchToolScope,
)

__all__ = [
    "AGENT_REACH_INBOX_DIR",
    "AGENT_REACH_PLAN_PATH",
    "AGENT_REACH_REVIEW_QUEUE_PATH",
    "AgentReachImportResult",
    "AgentReachResearchTask",
    "DetectedResearchTool",
    "RESEARCH_EVIDENCE_INDEX_PATH",
    "RESEARCH_EVIDENCE_RAW_DIR",
    "ResearchCollectionResult",
    "ResearchEvidenceDocument",
    "ResearchTool",
    "ResearchToolCategory",
    "ResearchToolScope",
    "build_manager_evidence_template_row",
    "build_agent_reach_research_tasks",
    "collect_public_evidence",
    "detect_research_tools",
    "document_from_agent_reach_markdown",
    "extract_markdown_from_html",
    "import_agent_reach_markdown",
    "recommended_research_workflow",
    "research_tool_catalog",
    "research_tool_summary",
    "write_agent_reach_plan",
    "write_research_documents",
]
