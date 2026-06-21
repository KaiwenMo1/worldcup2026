"""Schemas for optional research tools and collected evidence."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResearchToolCategory(StrEnum):
    CAPABILITY_ROUTER = "capability_router"
    WEB_CRAWLER = "web_crawler"
    DOCUMENT_CONVERTER = "document_converter"
    AGENT_FRAMEWORK = "agent_framework"
    MCP_SERVER = "mcp_server"


class ResearchToolScope(StrEnum):
    LOCAL_ONLY = "local_only"
    SAFE_FOR_SERVER_WITH_PUBLIC_URLS = "safe_for_server_with_public_urls"
    HEAVY_OPTIONAL_SERVER = "heavy_optional_server"


class ResearchTool(StrictModel):
    tool_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1)
    category: ResearchToolCategory
    package_name: str | None = None
    module_name: str | None = None
    command_name: str | None = None
    install_hint: str = Field(min_length=1)
    project_use: str = Field(min_length=1)
    recommended_scope: ResearchToolScope
    risk_note: str = Field(min_length=1)
    enabled_for_runtime: bool = False


class DetectedResearchTool(StrictModel):
    tool: ResearchTool
    package_available: bool
    command_available: bool
    ready: bool
    status_note: str


class ResearchEvidenceDocument(StrictModel):
    evidence_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    source_id: str = Field(min_length=1)
    source_tool: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str | None = None
    manager_id: str | None = None
    team: str | None = None
    category: str = "external_views"
    markdown: str = Field(min_length=1)
    collected_at: datetime
    word_count: int = Field(ge=1)
    data_quality: str = Field(min_length=1)
    notes: str | None = None

    @field_validator("collected_at")
    @classmethod
    def validate_collected_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at must include a timezone")
        return value


class AgentReachResearchTask(StrictModel):
    task_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    manager_id: str = Field(pattern=r"^[a-z0-9_]+$")
    manager_name: str = Field(min_length=1)
    team: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    priority: int = Field(ge=1, le=5)
    requires_login: bool = False
    target_category: str = Field(min_length=1)
    query: str = Field(min_length=1)
    agent_prompt: str = Field(min_length=1)
    output_path_hint: str = Field(min_length=1)
    evidence_policy: str = Field(min_length=1)
