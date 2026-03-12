"""Pydantic models for Atlassian (Jira & Confluence) data structures."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Jira
# ---------------------------------------------------------------------------


class JiraUser(BaseModel):
    """Minimal Jira user representation."""

    account_id: str = Field(..., alias="accountId")
    display_name: str = Field("", alias="displayName")
    email_address: str | None = Field(None, alias="emailAddress")

    model_config = {"populate_by_name": True}


class JiraIssueType(BaseModel):
    """Jira issue type metadata."""

    id: str
    name: str
    subtask: bool = False
    description: str = ""


class JiraStatus(BaseModel):
    """Jira workflow status."""

    id: str
    name: str
    category_key: str = Field("", alias="statusCategory.key")


class JiraTransition(BaseModel):
    """Available workflow transition."""

    id: str
    name: str
    to_status: str = Field("", alias="to.name")


class JiraPriority(BaseModel):
    """Jira priority level."""

    id: str
    name: str


class JiraComment(BaseModel):
    """Single Jira comment."""

    id: str
    body: str
    author: JiraUser | None = None
    created: datetime | None = None
    updated: datetime | None = None


class JiraIssueFields(BaseModel):
    """Core fields present on every Jira issue."""

    summary: str = ""
    description: str | None = None
    status: JiraStatus | None = None
    issue_type: JiraIssueType | None = Field(None, alias="issuetype")
    priority: JiraPriority | None = None
    assignee: JiraUser | None = None
    reporter: JiraUser | None = None
    labels: list[str] = Field(default_factory=list)
    components: list[dict[str, Any]] = Field(default_factory=list)
    parent: dict[str, Any] | None = None
    created: datetime | None = None
    updated: datetime | None = None

    model_config = {"populate_by_name": True}


class JiraIssue(BaseModel):
    """Full Jira issue returned by the API."""

    id: str
    key: str
    self_url: str = Field("", alias="self")
    fields: JiraIssueFields = Field(default_factory=JiraIssueFields)

    model_config = {"populate_by_name": True}


class JiraSearchResult(BaseModel):
    """Result set from a JQL search."""

    start_at: int = Field(0, alias="startAt")
    max_results: int = Field(50, alias="maxResults")
    total: int = 0
    issues: list[JiraIssue] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class JiraCreateIssueRequest(BaseModel):
    """Payload for creating a Jira issue via the MCP tool."""

    project_key: str
    summary: str
    description: str = ""
    issue_type: str = "Task"
    parent_key: str | None = None
    labels: list[str] = Field(default_factory=list)
    priority: str | None = None
    assignee_account_id: str | None = None


class JiraCreateIssueResponse(BaseModel):
    """Response after successful issue creation."""

    id: str
    key: str
    self_url: str = Field("", alias="self")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Confluence
# ---------------------------------------------------------------------------


class ConfluenceUser(BaseModel):
    """Confluence user representation."""

    account_id: str = Field(..., alias="accountId")
    display_name: str = Field("", alias="displayName")

    model_config = {"populate_by_name": True}


class ConfluencePageBody(BaseModel):
    """Body content of a Confluence page."""

    storage: dict[str, str] = Field(default_factory=dict)
    """Typically {"value": "<html>...", "representation": "storage"}."""


class ConfluencePage(BaseModel):
    """Confluence page object."""

    id: str
    title: str = ""
    status: str = ""
    space_key: str = ""
    body: ConfluencePageBody | None = None
    version: dict[str, Any] | None = None
    links: dict[str, str] = Field(default_factory=dict, alias="_links")

    model_config = {"populate_by_name": True}


class ConfluenceSearchResult(BaseModel):
    """Result set from a Confluence CQL search."""

    start: int = 0
    limit: int = 25
    total_size: int = Field(0, alias="totalSize")
    results: list[ConfluencePage] = Field(default_factory=list)

    model_config = {"populate_by_name": True}
