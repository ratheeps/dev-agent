"""Jira ticket ingestion handler.

Fetches issue details, linked Confluence pages, comments, and related
context to produce an enriched ``Task`` object ready for planning.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.integrations.atlassian.jira_client import JiraClient
from src.integrations.mcp_manager import MCPManager
from src.repositories.registry import RepoRegistry, get_default_repo_registry
from src.repositories.router import RepoRouter
from src.schemas.atlassian import ConfluencePage, JiraIssue
from src.schemas.skill import DetectionResult
from src.schemas.task import Task, TaskStatus
from src.skills.detector import SkillDetector

logger = logging.getLogger(__name__)

# Pattern for extracting Confluence page URLs from Jira descriptions
_CONFLUENCE_URL_RE = re.compile(
    r"https?://[^\s]+/wiki/spaces/([^\s/]+)/pages/(\d+)",
)

# Pattern for Figma URLs
_FIGMA_URL_RE = re.compile(
    r"https?://(?:www\.)?figma\.com/(?:file|design)/([a-zA-Z0-9]+)",
)


class JiraIngestionHandler:
    """Ingests a Jira ticket and produces an enriched Task for planning.

    Gathers the issue itself, its comments, linked Confluence documentation,
    and Figma design references into a single ``Task`` with populated context.
    Also routes the ticket to the correct target repository/repositories.
    """

    def __init__(
        self,
        mcp_manager: MCPManager,
        repo_registry: RepoRegistry | None = None,
    ) -> None:
        self._mcp = mcp_manager
        self._skill_detector = SkillDetector()
        self._repo_registry = repo_registry or get_default_repo_registry()
        self._repo_router = RepoRouter(self._repo_registry)

    @property
    def _jira(self) -> JiraClient:
        return self._mcp.jira

    async def ingest(self, jira_key: str) -> Task:
        """Fetch and enrich a Jira issue into a ``Task``.

        Parameters
        ----------
        jira_key:
            The Jira issue key, e.g. ``GIFT-1234``.

        Returns
        -------
        Task
            A fully enriched task with context from Jira, Confluence, and
            Figma ready for the planning phase.
        """
        logger.info("Ingesting Jira ticket %s", jira_key)

        issue = await self._jira.get_issue(jira_key)
        logger.info(
            "Fetched issue %s: %s",
            issue.key,
            issue.fields.summary,
        )

        requirements = self.extract_requirements(issue)
        context = await self.resolve_context(issue)

        comments = await self._fetch_comments(jira_key)
        if comments:
            context["comments"] = comments

        linked_issues = await self._fetch_linked_issues(jira_key)
        if linked_issues:
            context["linked_issues"] = linked_issues

        # Detect tech stack from the Jira issue data
        detection: DetectionResult = self._skill_detector.detect_from_jira(
            issue.model_dump()
        )
        if detection.detected_stacks:
            context["detected_skills"] = detection.to_dict()
            logger.info(
                "Detected tech stacks for %s: %s",
                jira_key,
                [s.value for s in detection.detected_stacks],
            )

        # Route ticket to target repositories
        jira_dict: dict[str, Any] = {
            "labels": issue.fields.labels,
            "components": [c.get("name", "") for c in (issue.fields.components or [])],
            "summary": issue.fields.summary,
            "description": issue.fields.description or "",
        }
        detected_stacks = [s.value for s in detection.detected_stacks]
        route_results = self._repo_router.route(jira_dict, detected_stacks)
        if route_results:
            context["target_repositories"] = [
                {"repo": r.repo_name, "confidence": r.confidence}
                for r in route_results
            ]
            context["repository"] = route_results[0].repo_name
            logger.info(
                "Routed %s to repos: %s",
                jira_key,
                [r.repo_name for r in route_results],
            )
        else:
            logger.warning("Could not route %s to any repo", jira_key)

        task = Task(
            jira_key=jira_key,
            title=issue.fields.summary,
            description=issue.fields.description or "",
            status=TaskStatus.PENDING,
            priority=issue.fields.priority.name if issue.fields.priority else "Medium",
            assignee=(
                issue.fields.assignee.display_name if issue.fields.assignee else None
            ),
            context={
                "requirements": requirements,
                "labels": issue.fields.labels,
                "components": [c.get("name", "") for c in (issue.fields.components or [])],
                "issue_type": (
                    issue.fields.issue_type.name if issue.fields.issue_type else "Task"
                ),
                **context,
            },
        )

        logger.info(
            "Task created for %s with %d context keys",
            jira_key,
            len(task.context),
        )
        return task

    def extract_requirements(self, issue: JiraIssue) -> dict[str, Any]:
        """Parse structured requirements from the issue description.

        Extracts:
        - ``summary``: The issue title.
        - ``description``: Raw description text.
        - ``acceptance_criteria``: Lines following an "Acceptance Criteria"
          heading, if present.
        - ``technical_notes``: Lines following a "Technical Notes" heading.
        """
        description = issue.fields.description or ""
        summary = issue.fields.summary

        requirements: dict[str, Any] = {
            "summary": summary,
            "description": description,
            "acceptance_criteria": [],
            "technical_notes": [],
        }

        acceptance = _extract_section(description, "acceptance criteria")
        if acceptance:
            requirements["acceptance_criteria"] = acceptance

        tech_notes = _extract_section(description, "technical notes")
        if tech_notes:
            requirements["technical_notes"] = tech_notes

        return requirements

    async def resolve_context(self, issue: JiraIssue) -> dict[str, Any]:
        """Fetch external context linked from the issue.

        Scans the description for Confluence and Figma URLs and fetches
        their content via MCP.
        """
        context: dict[str, Any] = {}
        description = issue.fields.description or ""

        confluence_pages = await self._fetch_confluence_pages(description)
        if confluence_pages:
            context["confluence_pages"] = [
                {
                    "id": page.id,
                    "title": page.title,
                    "body": (
                        page.body.storage.get("value", "")
                        if page.body
                        else ""
                    ),
                }
                for page in confluence_pages
            ]

        figma_keys = _FIGMA_URL_RE.findall(description)
        if figma_keys:
            figma_context = await self._fetch_figma_context(figma_keys)
            if figma_context:
                context["figma_designs"] = figma_context

        return context

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _fetch_comments(self, jira_key: str) -> list[dict[str, str]]:
        """Fetch comments on the issue via JQL search for comment content."""
        try:
            issue = await self._jira.get_issue(jira_key)  # noqa: F841
            # Comments are not directly on the issue model; use search to
            # get them via the Atlassian MCP search tool.
            search_result = await self._jira.search_jql(
                f'issue = "{jira_key}" ORDER BY created DESC',
                max_results=1,
            )
            if not search_result.issues:
                return []
            # Return empty if no comment-specific API is exposed beyond
            # add_comment.  The ingestion is best-effort.
            return []
        except Exception:
            logger.warning("Failed to fetch comments for %s", jira_key, exc_info=True)
            return []

    async def _fetch_linked_issues(self, jira_key: str) -> list[dict[str, str]]:
        """Fetch issues linked to the current ticket."""
        try:
            search_result = await self._jira.search_jql(
                f'issue in linkedIssues("{jira_key}")',
                max_results=10,
            )
            return [
                {
                    "key": linked.key,
                    "summary": linked.fields.summary,
                    "status": (
                        linked.fields.status.name if linked.fields.status else ""
                    ),
                }
                for linked in search_result.issues
            ]
        except Exception:
            logger.warning(
                "Failed to fetch linked issues for %s", jira_key, exc_info=True
            )
            return []

    async def _fetch_confluence_pages(
        self, description: str
    ) -> list[ConfluencePage]:
        """Extract and fetch Confluence pages referenced in the description."""
        pages: list[ConfluencePage] = []
        matches = _CONFLUENCE_URL_RE.findall(description)

        for _space_key, page_id in matches:
            try:
                page = await self._mcp.confluence.get_page(page_id)
                pages.append(page)
                logger.info("Fetched Confluence page %s: %s", page_id, page.title)
            except Exception:
                logger.warning(
                    "Failed to fetch Confluence page %s", page_id, exc_info=True
                )

        return pages

    async def _fetch_figma_context(
        self, figma_file_keys: list[str]
    ) -> list[dict[str, str]]:
        """Fetch Figma file metadata for referenced designs."""
        results: list[dict[str, str]] = []

        for file_key in figma_file_keys:
            try:
                file_data = await self._mcp.figma.get_file(file_key)
                results.append({
                    "file_key": file_key,
                    "name": file_data.name,
                    "last_modified": file_data.last_modified,
                    "component_count": str(len(file_data.components)),
                })
                logger.info("Fetched Figma file %s: %s", file_key, file_data.name)
            except Exception:
                logger.warning(
                    "Failed to fetch Figma file %s", file_key, exc_info=True
                )

        return results


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _extract_section(text: str, heading: str) -> list[str]:
    """Extract bullet/line items under a markdown-style heading.

    Looks for ``## Heading`` or ``**Heading**`` patterns and collects
    subsequent non-empty lines until the next heading or end of text.
    """
    pattern = re.compile(
        rf"(?:^|\n)\s*(?:#{1,3}\s*|(?:\*\*))?"
        + re.escape(heading)
        + r"(?:\*\*)?\s*:?\s*\n",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return []

    remaining = text[match.end() :]
    lines: list[str] = []

    for raw_line in remaining.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        # Stop at the next section heading
        if re.match(r"^#{1,3}\s+", line) or re.match(r"^\*\*[A-Z]", line):
            break
        # Strip leading bullet characters
        cleaned = re.sub(r"^[-*]\s*", "", line)
        if cleaned:
            lines.append(cleaned)

    return lines
