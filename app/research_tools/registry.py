"""Capability registry for optional research-agent tooling."""

from __future__ import annotations

import importlib.util
import shutil

from app.research_tools.schemas import (
    DetectedResearchTool,
    ResearchTool,
    ResearchToolCategory,
    ResearchToolScope,
)


def research_tool_catalog() -> list[ResearchTool]:
    """Return the supported optional tools without importing heavy dependencies."""
    return [
        ResearchTool(
            tool_id="agent_reach",
            name="Agent-Reach",
            category=ResearchToolCategory.CAPABILITY_ROUTER,
            package_name="agent-reach",
            module_name="agent_reach",
            command_name="agent-reach",
            install_hint="pip install -r requirements-research.txt && agent-reach install --safe",
            project_use="Local research scout for web, GitHub, RSS, video, and social evidence collection.",
            recommended_scope=ResearchToolScope.LOCAL_ONLY,
            risk_note="Cookie/login channels must stay local and should use secondary accounts only.",
        ),
        ResearchTool(
            tool_id="crawl4ai",
            name="Crawl4AI",
            category=ResearchToolCategory.WEB_CRAWLER,
            package_name="crawl4ai",
            module_name="crawl4ai",
            command_name="crwl",
            install_hint="pip install -r requirements-research.txt && crawl4ai-setup",
            project_use="Repeatable public-page crawling into clean Markdown for RAG and manager evidence.",
            recommended_scope=ResearchToolScope.HEAVY_OPTIONAL_SERVER,
            risk_note="Browser setup can be heavy; respect publisher terms and cache responsibly.",
        ),
        ResearchTool(
            tool_id="markitdown",
            name="Microsoft MarkItDown",
            category=ResearchToolCategory.DOCUMENT_CONVERTER,
            package_name="markitdown",
            module_name="markitdown",
            command_name="markitdown",
            install_hint="pip install -r requirements-research.txt",
            project_use="Convert lightweight PDFs, Word files, and office documents into Markdown evidence.",
            recommended_scope=ResearchToolScope.SAFE_FOR_SERVER_WITH_PUBLIC_URLS,
            risk_note="Review converted content before treating it as evidence; document layouts can be lossy.",
        ),
        ResearchTool(
            tool_id="docling",
            name="Docling",
            category=ResearchToolCategory.DOCUMENT_CONVERTER,
            package_name="docling",
            module_name="docling",
            command_name="docling",
            install_hint="pip install -r requirements-research.txt",
            project_use="Heavier document parsing for FIFA PDFs, technical reports, and table-rich evidence.",
            recommended_scope=ResearchToolScope.HEAVY_OPTIONAL_SERVER,
            risk_note="Large dependency footprint; use locally or in a separate worker before adding to deploy.",
        ),
        ResearchTool(
            tool_id="pydantic_ai",
            name="PydanticAI",
            category=ResearchToolCategory.AGENT_FRAMEWORK,
            package_name="pydantic-ai",
            module_name="pydantic_ai",
            command_name=None,
            install_hint="pip install -r requirements-research.txt",
            project_use="Typed future replacement path for Expert/Kevin/Upset/Skeptic agent orchestration.",
            recommended_scope=ResearchToolScope.SAFE_FOR_SERVER_WITH_PUBLIC_URLS,
            risk_note="Keep model calls evidence-grounded and preserve existing probability guardrails.",
        ),
        ResearchTool(
            tool_id="fastmcp",
            name="FastMCP",
            category=ResearchToolCategory.MCP_SERVER,
            package_name="fastmcp",
            module_name="fastmcp",
            command_name="fastmcp",
            install_hint="pip install -r requirements-research.txt",
            project_use="Expose forecast, tactical brief, player profile, and evaluation tools to Codex/Claude/Cursor.",
            recommended_scope=ResearchToolScope.SAFE_FOR_SERVER_WITH_PUBLIC_URLS,
            risk_note="Tool endpoints should be read-only by default; require approval for ingestion or publishing.",
        ),
    ]


def _module_available(module_name: str | None) -> bool:
    return bool(module_name and importlib.util.find_spec(module_name))


def _command_available(command_name: str | None) -> bool:
    return bool(command_name and shutil.which(command_name))


def detect_research_tools() -> list[DetectedResearchTool]:
    detections = []
    for tool in research_tool_catalog():
        package_available = _module_available(tool.module_name)
        command_available = _command_available(tool.command_name)
        ready = package_available or command_available
        detections.append(
            DetectedResearchTool(
                tool=tool,
                package_available=package_available,
                command_available=command_available,
                ready=ready,
                status_note="available" if ready else f"not installed; {tool.install_hint}",
            )
        )
    return detections


def research_tool_summary() -> dict[str, object]:
    detections = detect_research_tools()
    return {
        "ready": [item.tool.tool_id for item in detections if item.ready],
        "missing": [item.tool.tool_id for item in detections if not item.ready],
        "runtime_policy": "Optional research tools are local/worker dependencies, not required by the hosted predictor.",
        "tools": [item.model_dump(mode="json") for item in detections],
    }


def recommended_research_workflow() -> list[str]:
    return [
        "Install optional tools locally with: pip install -r requirements-research.txt",
        "Run: python scripts/research_tool_doctor.py",
        "Collect public web evidence with: python scripts/collect_research_evidence.py --url URL --title TITLE",
        "Review generated Markdown and source metadata before converting claims into tactical evidence CSV rows.",
        "Only human-reviewed, recurring, distinctive claims should refine manager skills or agent reasoning.",
    ]
