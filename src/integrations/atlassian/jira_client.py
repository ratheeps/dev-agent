"""Typed async wrapper around the Atlassian MCP Jira tools.

Every public method delegates to the injected ``mcp_call`` callable, which is
the agent-runtime's MCP tool invocation function.  Raw MCP responses are parsed
into Pydantic models for downstream consumption.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

from src.schemas.atlassian import (
    JiraComment,
    JiraCreateIssueResponse,
    JiraIssue,
    JiraIssueType,
    JiraSearchResult,
    JiraTransition,
)

logger = logging.getLogger(__name__)

McpCallFn = Callable[[str, dict[str, Any]], Coroutine[Any, Any, Any]]


class JiraClient:
    """High-level async Jira client backed by MCP tools.

    Parameters
    ----------
    mcp_call:
        Async callable ``(tool_name, arguments) -> Any`` provided by the
        agent runtime.
    """

    def __init__(self, mcp_call: McpCallFn) -> None:
        self._call = mcp_call

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    async def get_issue(self, key: str) -> JiraIssue:
        """Fetch a single Jira issue by its key (e.g. ``PROJ-42``)."""
        raw = await self._call(
            "mcp__claude_ai_Atlassian__getJiraIssue",
            {"issueIdOrKey": key},
        )
        return _parse_issue(raw)

    async def create_subtask(
        self,
        parent_key: str,
        summary: str,
        description: str = "",
        *,
        project_key: str | None = None,
        issue_type: str = "Sub-task",
        labels: list[str] | None = None,
    ) -> JiraCreateIssueResponse:
        """Create a sub-task underneath *parent_key*.

        If *project_key* is not provided it is derived from the parent key.
        """
        derived_project = project_key or parent_key.rsplit("-", 1)[0]

        fields: dict[str, Any] = {
            "project": {"key": derived_project},
            "parent": {"key": parent_key},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type},
        }
        if labels:
            fields["labels"] = labels

        raw = await self._call(
            "mcp__claude_ai_Atlassian__createJiraIssue",
            {"fields": fields},
        )
        return _parse_create_response(raw)

    async def transition_issue(self, key: str, transition_name: str) -> None:
        """Move an issue through a workflow transition by name.

        First resolves the transition name to an ID via
        ``getTransitionsForJiraIssue``, then executes the transition.

        Raises
        ------
        ValueError
            If the requested transition name is not available for the issue.
        """
        transitions = await self.get_transitions(key)
        matched = [t for t in transitions if t.name.lower() == transition_name.lower()]
        if not matched:
            available = ", ".join(t.name for t in transitions)
            msg = (
                f"Transition '{transition_name}' not found for {key}. "
                f"Available: {available}"
            )
            raise ValueError(msg)

        transition_id = matched[0].id
        await self._call(
            "mcp__claude_ai_Atlassian__transitionJiraIssue",
            {"issueIdOrKey": key, "transition": {"id": transition_id}},
        )
        logger.info("Transitioned %s via '%s' (id=%s)", key, transition_name, transition_id)

    async def get_transitions(self, key: str) -> list[JiraTransition]:
        """Return available workflow transitions for an issue."""
        raw = await self._call(
            "mcp__claude_ai_Atlassian__getTransitionsForJiraIssue",
            {"issueIdOrKey": key},
        )
        raw_transitions: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            raw_transitions = raw.get("transitions", [])
        elif isinstance(raw, list):
            raw_transitions = raw

        return [
            JiraTransition(
                id=str(t.get("id", "")),
                name=t.get("name", ""),
                **{"to.name": t.get("to", {}).get("name", "")},
            )
            for t in raw_transitions
        ]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_jql(
        self,
        jql: str,
        max_results: int = 50,
    ) -> JiraSearchResult:
        """Execute a JQL query and return parsed results."""
        raw = await self._call(
            "mcp__claude_ai_Atlassian__searchJiraIssuesUsingJql",
            {"jql": jql, "maxResults": max_results},
        )
        return _parse_search_result(raw)

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    async def add_comment(self, key: str, body: str) -> JiraComment:
        """Add a plain-text comment to an issue."""
        raw = await self._call(
            "mcp__claude_ai_Atlassian__addCommentToJiraIssue",
            {"issueIdOrKey": key, "body": body},
        )
        return _parse_comment(raw)

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    async def get_issue_types(self, project_key: str) -> list[JiraIssueType]:
        """Return available issue types for a project."""
        raw = await self._call(
            "mcp__claude_ai_Atlassian__getJiraProjectIssueTypesMetadata",
            {"projectKey": project_key},
        )
        items: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            items = raw.get("issueTypes", raw.get("values", []))
        elif isinstance(raw, list):
            items = raw

        return [
            JiraIssueType(
                id=str(it.get("id", "")),
                name=it.get("name", ""),
                subtask=bool(it.get("subtask", False)),
                description=it.get("description", ""),
            )
            for it in items
        ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_issue(raw: Any) -> JiraIssue:
    """Normalise a raw MCP response into a ``JiraIssue``."""
    if isinstance(raw, dict):
        return JiraIssue.model_validate(raw)
    # If the MCP tool returned a JSON string, Pydantic handles it.
    return JiraIssue.model_validate_json(str(raw))


def _parse_create_response(raw: Any) -> JiraCreateIssueResponse:
    if isinstance(raw, dict):
        return JiraCreateIssueResponse.model_validate(raw)
    return JiraCreateIssueResponse.model_validate_json(str(raw))


def _parse_search_result(raw: Any) -> JiraSearchResult:
    if isinstance(raw, dict):
        return JiraSearchResult.model_validate(raw)
    return JiraSearchResult.model_validate_json(str(raw))


def _parse_comment(raw: Any) -> JiraComment:
    if isinstance(raw, dict):
        return JiraComment.model_validate(raw)
    return JiraComment.model_validate_json(str(raw))
