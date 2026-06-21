"""Local research evidence collection helpers.

This module is intentionally conservative: it can use simple public HTTP reads
without requiring heavy optional packages, while the registry documents where
Agent-Reach, Crawl4AI, MarkItDown, Docling, PydanticAI, and FastMCP fit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

import requests
from bs4 import BeautifulSoup

from app.ingestion import (
    CsvWriteResult,
    DataQualityIssue,
    DataQualitySeverity,
    make_data_quality_issue,
    safe_write_csv,
)
from app.research_tools.registry import detect_research_tools
from app.research_tools.schemas import ResearchEvidenceDocument


ROOT = Path(__file__).resolve().parents[2]
RESEARCH_EVIDENCE_RAW_DIR = ROOT / "data" / "raw" / "research_evidence"
RESEARCH_EVIDENCE_INDEX_PATH = RESEARCH_EVIDENCE_RAW_DIR / "research_evidence_index.csv"
RESEARCH_EVIDENCE_INDEX_FIELDS = [
    "evidence_id",
    "source_id",
    "source_tool",
    "title",
    "url",
    "manager_id",
    "team",
    "category",
    "path",
    "collected_at",
    "word_count",
    "data_quality",
    "notes",
]


@dataclass
class ResearchCollectionResult:
    documents: list[ResearchEvidenceDocument] = field(default_factory=list)
    issues: list[DataQualityIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity in {DataQualitySeverity.ERROR, DataQualitySeverity.CRITICAL} for issue in self.issues)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip()).strip("_").lower()
    return cleaned[:80] or uuid4().hex


def _source_tool() -> str:
    ready = {item.tool.tool_id for item in detect_research_tools() if item.ready}
    if "crawl4ai" in ready:
        return "crawl4ai_available_fallback_parser_used"
    if "agent_reach" in ready:
        return "agent_reach_available_fallback_parser_used"
    return "requests_beautifulsoup"


def extract_markdown_from_html(html: str, *, title: str | None = None) -> tuple[str, str]:
    """Extract readable Markdown-ish content from HTML for reviewable evidence."""
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()

    detected_title = title
    if not detected_title:
        heading = soup.find(["h1", "title"])
        detected_title = heading.get_text(" ", strip=True) if heading else "Untitled research evidence"

    lines = [f"# {detected_title}", ""]
    for node in soup.find_all(["h2", "h3", "p", "li", "blockquote"]):
        text = " ".join(node.get_text(" ", strip=True).split())
        if not text:
            continue
        if node.name == "h2":
            lines.extend(["", f"## {text}", ""])
        elif node.name == "h3":
            lines.extend(["", f"### {text}", ""])
        elif node.name == "li":
            lines.append(f"- {text}")
        elif node.name == "blockquote":
            lines.append(f"> {text}")
        else:
            lines.extend([text, ""])

    markdown = "\n".join(lines).strip()
    return detected_title, markdown


def collect_public_evidence(
    *,
    url: str | None = None,
    html: str | None = None,
    title: str | None = None,
    source_id: str = "research_scout_public_web",
    manager_id: str | None = None,
    team: str | None = None,
    category: str = "external_views",
    notes: str | None = None,
    fetcher: Callable[[str], str] | None = None,
) -> ResearchCollectionResult:
    if not url and html is None:
        return ResearchCollectionResult(
            issues=[
                make_data_quality_issue(
                    file="research_scout",
                    severity=DataQualitySeverity.ERROR,
                    problem="Either url or html is required",
                    suggested_fix="Pass --url or --input-html.",
                )
            ]
        )

    try:
        content = html
        if content is None and url:
            if fetcher:
                content = fetcher(url)
            else:
                response = requests.get(url, timeout=30, headers={"User-Agent": "worldcup2026-research-scout/1.0"})
                response.raise_for_status()
                content = response.text
        assert content is not None
        detected_title, markdown = extract_markdown_from_html(content, title=title)
    except (AssertionError, OSError, requests.RequestException, UnicodeError) as exc:
        return ResearchCollectionResult(
            issues=[
                make_data_quality_issue(
                    file=url or "research_scout",
                    severity=DataQualitySeverity.ERROR,
                    problem=f"Research evidence could not be collected: {exc}",
                    suggested_fix="Check the URL, network access, and publisher restrictions.",
                )
            ]
        )

    words = re.findall(r"\b\w+\b", markdown)
    if not words:
        return ResearchCollectionResult(
            issues=[
                make_data_quality_issue(
                    file=url or "research_scout",
                    severity=DataQualitySeverity.ERROR,
                    problem="Collected page did not yield readable text",
                    suggested_fix="Use Crawl4AI/Agent-Reach locally or supply reviewed text manually.",
                )
            ]
        )

    source_slug = _slug(title or url or detected_title)
    document = ResearchEvidenceDocument(
        evidence_id=f"research_{source_slug}_{uuid4().hex[:8]}",
        source_id=source_id,
        source_tool=_source_tool(),
        title=detected_title,
        url=url,
        manager_id=manager_id,
        team=team,
        category=category,
        markdown=markdown,
        collected_at=datetime.now(timezone.utc),
        word_count=len(words),
        data_quality="raw_unreviewed_public_evidence",
        notes=notes,
    )
    return ResearchCollectionResult(documents=[document])


def _index_row(document: ResearchEvidenceDocument, path: Path) -> dict[str, object]:
    payload = document.model_dump(mode="json")
    return {
        "evidence_id": payload["evidence_id"],
        "source_id": payload["source_id"],
        "source_tool": payload["source_tool"],
        "title": payload["title"],
        "url": payload.get("url") or "",
        "manager_id": payload.get("manager_id") or "",
        "team": payload.get("team") or "",
        "category": payload["category"],
        "path": str(path),
        "collected_at": payload["collected_at"],
        "word_count": payload["word_count"],
        "data_quality": payload["data_quality"],
        "notes": payload.get("notes") or "",
    }


def write_research_documents(
    documents: list[ResearchEvidenceDocument],
    *,
    output_dir: Path = RESEARCH_EVIDENCE_RAW_DIR,
    index_path: Path = RESEARCH_EVIDENCE_INDEX_PATH,
) -> list[DataQualityIssue]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    issues: list[DataQualityIssue] = []
    for document in documents:
        path = output_dir / f"{document.evidence_id}.md"
        try:
            path.write_text(document.markdown + "\n", encoding="utf-8")
        except OSError as exc:
            issues.append(
                make_data_quality_issue(
                    file=path,
                    severity=DataQualitySeverity.ERROR,
                    problem=f"Research evidence markdown could not be written: {exc}",
                )
            )
            continue
        rows.append(_index_row(document, path))
    write_result: CsvWriteResult = safe_write_csv(index_path, rows, RESEARCH_EVIDENCE_INDEX_FIELDS, append=True)
    return [*issues, *write_result.issues]


def build_manager_evidence_template_row(document: ResearchEvidenceDocument) -> dict[str, str]:
    """Create a review template row for manual tactical-evidence curation."""
    return {
        "manager_id": document.manager_id or "",
        "manager_name": "",
        "team": document.team or "",
        "evidence_type": "article",
        "tactical_topic": "",
        "claim_text": "",
        "proposed_value": "",
        "source_id": document.source_id,
        "source_title": document.title,
        "source_url": document.url or "",
        "source_reliability": "0.65",
        "directness": "0.5",
        "content_origin": "manual",
        "reviewed_by_human": "false",
        "notes": f"Drafted from {document.evidence_id}; review Markdown before extracting claims.",
    }
