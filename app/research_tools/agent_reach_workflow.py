"""Agent-Reach research planning and import workflow.

Agent-Reach is best used locally as an internet capability layer. This module
does not depend on Agent-Reach at runtime; it creates explicit research tasks
for an agent using Agent-Reach, then imports the resulting Markdown into the
repo's reviewable evidence pipeline.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from app.ingestion.normalizers import make_data_quality_issue, safe_read_csv, safe_write_csv
from app.ingestion.schemas import DataQualityIssue, DataQualitySeverity
from app.research_tools.football_research_scout import (
    RESEARCH_EVIDENCE_INDEX_PATH,
    RESEARCH_EVIDENCE_RAW_DIR,
    RESEARCH_EVIDENCE_INDEX_FIELDS,
    build_manager_evidence_template_row,
    write_research_documents,
)
from app.research_tools.schemas import AgentReachResearchTask, ResearchEvidenceDocument


ROOT = Path(__file__).resolve().parents[2]
MANAGERS_PATH = ROOT / "data" / "managers.csv"
AGENT_REACH_INBOX_DIR = RESEARCH_EVIDENCE_RAW_DIR / "agent_reach_inbox"
AGENT_REACH_PLAN_PATH = ROOT / "data" / "derived" / "agent_reach_manager_research_plan.csv"
AGENT_REACH_REVIEW_QUEUE_PATH = ROOT / "data" / "derived" / "agent_reach_tactical_review_queue.csv"
AGENT_REACH_PLAN_FIELDS = list(AgentReachResearchTask.model_fields)
AGENT_REACH_REVIEW_QUEUE_FIELDS = [
    "evidence_id",
    "evidence_path",
    "manager_id",
    "manager_name",
    "team",
    "evidence_type",
    "tactical_topic",
    "claim_text",
    "proposed_value",
    "source_id",
    "source_title",
    "source_url",
    "source_reliability",
    "directness",
    "content_origin",
    "reviewed_by_human",
    "extraction_prompt",
    "notes",
]


@dataclass
class AgentReachImportResult:
    documents: list[ResearchEvidenceDocument] = field(default_factory=list)
    imported_paths: list[Path] = field(default_factory=list)
    review_rows: list[dict[str, str]] = field(default_factory=list)
    issues: list[DataQualityIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity in {DataQualitySeverity.ERROR, DataQualitySeverity.CRITICAL} for issue in self.issues)


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip()).strip("_").lower()[:80] or uuid4().hex


def _manager_rows(path: Path = MANAGERS_PATH) -> list[dict[str, str]]:
    rows = safe_read_csv(path, {"manager_id", "manager_name", "team"}).rows
    return [row for row in rows if row.get("manager_id") and row.get("manager_name") and row.get("team")]


def _agent_prompt(
    *,
    manager_id: str,
    manager_name: str,
    team: str,
    channel: str,
    target_category: str,
    query: str,
    requires_login: bool,
) -> str:
    login_note = "Use only accounts/cookies that stay local; do not commit credentials." if requires_login else "Use public sources only."
    return (
        f"Use Agent-Reach to research {manager_name} ({team}) for the World Cup project.\n"
        f"Channel: {channel}. Query: {query}\n"
        f"{login_note}\n"
        "Save one Markdown file per useful source under "
        f"data/raw/research_evidence/agent_reach_inbox/{manager_id}/.\n"
        "Each Markdown file must start with these metadata lines:\n"
        f"manager_id: {manager_id}\n"
        f"manager_name: {manager_name}\n"
        f"team: {team}\n"
        f"category: {target_category}\n"
        "source_url: <original URL>\n"
        "source_title: <source title>\n"
        f"source_channel: {channel}\n"
        "Then include source-grounded notes only. Do not invent tactical claims."
    )


def build_agent_reach_research_tasks(
    *,
    team: str | None = None,
    manager_id: str | None = None,
    include_social: bool = False,
    limit: int | None = None,
    managers_path: Path = MANAGERS_PATH,
) -> list[AgentReachResearchTask]:
    """Build local Agent-Reach research tasks for manager-skill evidence."""
    rows = _manager_rows(managers_path)
    if team:
        rows = [row for row in rows if row.get("team", "").casefold() == team.casefold()]
    if manager_id:
        rows = [row for row in rows if row.get("manager_id") == manager_id]
    if limit is not None:
        rows = rows[:limit]

    channel_specs = [
        (
            "web_tactical_reports",
            1,
            False,
            "tactical_reports",
            "{manager} {team} tactical analysis formation pressing transitions World Cup 2026",
            "Core recurring tactical evidence from public tactical reports.",
        ),
        (
            "press_conferences",
            2,
            False,
            "press_conferences",
            "{manager} {team} press conference tactics lineup substitutions World Cup",
            "Direct manager quotes should be separated from journalist interpretation.",
        ),
        (
            "youtube_breakdowns",
            3,
            False,
            "external_views",
            "{team} {manager} tactical breakdown video analysis",
            "Use captions/transcripts when available; cite the video URL.",
        ),
        (
            "github_and_open_data",
            4,
            False,
            "decision_records",
            "{team} football open data lineups formations substitutions {manager}",
            "Prefer structured public data and transparent match records.",
        ),
    ]
    if include_social:
        channel_specs.append(
            (
                "social_discussion",
                5,
                True,
                "external_views",
                "{team} {manager} tactics discussion fan analysis reddit twitter",
                "Social evidence is weak context only and must not become a core rule by itself.",
            )
        )

    tasks: list[AgentReachResearchTask] = []
    for row in rows:
        for channel, priority, requires_login, category, query_template, policy in channel_specs:
            query = query_template.format(manager=row["manager_name"], team=row["team"])
            task_id = f"agent_reach_{_slug(row['manager_id'])}_{channel}"
            tasks.append(
                AgentReachResearchTask(
                    task_id=task_id,
                    manager_id=row["manager_id"],
                    manager_name=row["manager_name"],
                    team=row["team"],
                    channel=channel,
                    priority=priority,
                    requires_login=requires_login,
                    target_category=category,
                    query=query,
                    agent_prompt=_agent_prompt(
                        manager_id=row["manager_id"],
                        manager_name=row["manager_name"],
                        team=row["team"],
                        channel=channel,
                        target_category=category,
                        query=query,
                        requires_login=requires_login,
                    ),
                    output_path_hint=f"data/raw/research_evidence/agent_reach_inbox/{row['manager_id']}/",
                    evidence_policy=policy,
                )
            )
    return tasks


def write_agent_reach_plan(
    tasks: Iterable[AgentReachResearchTask],
    path: Path = AGENT_REACH_PLAN_PATH,
) -> list[DataQualityIssue]:
    rows = [task.model_dump(mode="json") for task in tasks]
    result = safe_write_csv(path, rows, AGENT_REACH_PLAN_FIELDS)
    return result.issues


def _metadata_and_body(markdown: str) -> tuple[dict[str, str], str]:
    metadata: dict[str, str] = {}
    body_lines = []
    in_metadata = True
    for line in markdown.splitlines():
        if in_metadata and re.match(r"^[a-zA-Z_]+:\s*", line):
            key, value = line.split(":", 1)
            metadata[key.strip().casefold()] = value.strip()
            continue
        in_metadata = False
        body_lines.append(line)
    return metadata, "\n".join(body_lines).strip() or markdown.strip()


def _first_heading(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip() or fallback
    return fallback


def document_from_agent_reach_markdown(path: Path) -> ResearchEvidenceDocument:
    raw = path.read_text(encoding="utf-8")
    metadata, body = _metadata_and_body(raw)
    title = metadata.get("source_title") or _first_heading(body, path.stem)
    words = re.findall(r"\b\w+\b", body)
    manager_id = metadata.get("manager_id") or None
    evidence_id = f"agent_reach_{_slug(manager_id or path.stem)}_{uuid4().hex[:8]}"
    return ResearchEvidenceDocument(
        evidence_id=evidence_id,
        source_id="agent_reach_local",
        source_tool=f"agent_reach_{metadata.get('source_channel') or 'manual_import'}",
        title=title,
        url=metadata.get("source_url") or None,
        manager_id=manager_id,
        team=metadata.get("team") or None,
        category=metadata.get("category") or "external_views",
        markdown=body,
        collected_at=datetime.now(timezone.utc),
        word_count=max(len(words), 1),
        data_quality="raw_unreviewed_agent_reach_evidence",
        notes="Imported from local Agent-Reach collection; requires human review before model use.",
    )


def _review_row(document: ResearchEvidenceDocument, evidence_path: Path) -> dict[str, str]:
    row = build_manager_evidence_template_row(document)
    manager_name = ""
    if document.manager_id:
        manager = next((item for item in _manager_rows() if item["manager_id"] == document.manager_id), None)
        manager_name = (manager or {}).get("manager_name", "")
    return {
        "evidence_id": document.evidence_id,
        "evidence_path": str(evidence_path),
        "manager_id": row["manager_id"],
        "manager_name": manager_name,
        "team": row["team"],
        "evidence_type": row["evidence_type"],
        "tactical_topic": row["tactical_topic"],
        "claim_text": row["claim_text"],
        "proposed_value": row["proposed_value"],
        "source_id": row["source_id"],
        "source_title": row["source_title"],
        "source_url": row["source_url"],
        "source_reliability": "0.5",
        "directness": "0.4",
        "content_origin": "manual",
        "reviewed_by_human": "false",
        "extraction_prompt": (
            "Read the Markdown. Extract one narrow tactical claim only if it is explicit, source-grounded, "
            "and useful for future match prediction; otherwise leave claim_text blank."
        ),
        "notes": row["notes"],
    }


def import_agent_reach_markdown(
    input_dir: Path = AGENT_REACH_INBOX_DIR,
    *,
    output_dir: Path = RESEARCH_EVIDENCE_RAW_DIR,
    index_path: Path = RESEARCH_EVIDENCE_INDEX_PATH,
    review_queue_path: Path = AGENT_REACH_REVIEW_QUEUE_PATH,
) -> AgentReachImportResult:
    if not input_dir.exists():
        return AgentReachImportResult(
            issues=[
                make_data_quality_issue(
                    file=input_dir,
                    severity=DataQualitySeverity.WARNING,
                    problem="Agent-Reach inbox directory does not exist",
                    suggested_fix="Run plan_agent_reach_research.py, collect Markdown locally, then import it.",
                )
            ]
        )

    documents: list[ResearchEvidenceDocument] = []
    imported_paths: list[Path] = []
    issues: list[DataQualityIssue] = []
    for path in sorted(input_dir.rglob("*.md")):
        try:
            documents.append(document_from_agent_reach_markdown(path))
            imported_paths.append(path)
        except (OSError, ValueError) as exc:
            issues.append(
                make_data_quality_issue(
                    file=path,
                    severity=DataQualitySeverity.ERROR,
                    problem=f"Agent-Reach Markdown could not be imported: {exc}",
                )
            )

    issues.extend(write_research_documents(documents, output_dir=output_dir, index_path=index_path))
    review_rows = []
    for document in documents:
        evidence_path = output_dir / f"{document.evidence_id}.md"
        review_rows.append(_review_row(document, evidence_path))
    queue_result = safe_write_csv(review_queue_path, review_rows, AGENT_REACH_REVIEW_QUEUE_FIELDS, append=True)
    issues.extend(queue_result.issues)
    return AgentReachImportResult(
        documents=documents,
        imported_paths=imported_paths,
        review_rows=review_rows,
        issues=issues,
    )
