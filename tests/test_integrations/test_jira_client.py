"""Unit tests for the Jira MCP client wrapper."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.integrations.atlassian.jira_client import JiraClient
from src.schemas.atlassian import (
    JiraComment,
    JiraCreateIssueResponse,
    JiraIssue,
    JiraIssueType,
    JiraSearchResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mcp_call() -> AsyncMock:
    """Return a mock MCP callable."""
    return AsyncMock()


@pytest.fixture()
def client(mcp_call: AsyncMock) -> JiraClient:
    return JiraClient(mcp_call=mcp_call)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _issue_payload(key: str = "PROJ-1", summary: str = "Test issue") -> dict[str, Any]:
    return {
        "id": "10001",
        "key": key,
        "self": f"https://jira.example.com/rest/api/2/issue/{key}",
        "fields": {
            "summary": summary,
            "description": "A test issue",
            "status": {"id": "1", "name": "To Do"},
            "issuetype": {"id": "10", "name": "Task", "subtask": False},
            "priority": {"id": "3", "name": "Medium"},
            "labels": ["backend"],
        },
    }


# ---------------------------------------------------------------------------
# Tests — get_issue
# ---------------------------------------------------------------------------

class TestGetIssue:
    async def test_returns_parsed_issue(
        self, client: JiraClient, mcp_call: AsyncMock
    ) -> None:
        mcp_call.return_value = _issue_payload("DEV-42", "Login bug")

        issue = await client.get_issue("DEV-42")

        assert isinstance(issue, JiraIssue)
        assert issue.key == "DEV-42"
        assert issue.fields.summary == "Login bug"
        mcp_call.assert_awaited_once_with(
            "mcp__claude_ai_Atlassian__getJiraIssue",
            {"issueIdOrKey": "DEV-42"},
        )

    async def test_parses_minimal_payload(
        self, client: JiraClient, mcp_call: AsyncMock
    ) -> None:
        mcp_call.return_value = {"id": "1", "key": "X-1", "fields": {}}
        issue = await client.get_issue("X-1")
        assert issue.key == "X-1"
        assert issue.fields.summary == ""


# ---------------------------------------------------------------------------
# Tests — create_subtask
# ---------------------------------------------------------------------------

class TestCreateSubtask:
    async def test_creates_subtask_with_derived_project(
        self, client: JiraClient, mcp_call: AsyncMock
    ) -> None:
        mcp_call.return_value = {
            "id": "10002",
            "key": "PROJ-2",
            "self": "https://jira.example.com/rest/api/2/issue/PROJ-2",
        }

        result = await client.create_subtask(
            parent_key="PROJ-1",
            summary="Implement login",
            description="Add OAuth flow",
        )

        assert isinstance(result, JiraCreateIssueResponse)
        assert result.key == "PROJ-2"

        call_args = mcp_call.call_args
        fields = call_args[0][1]["fields"]
        assert fields["project"]["key"] == "PROJ"
        assert fields["parent"]["key"] == "PROJ-1"
        assert fields["summary"] == "Implement login"
        assert fields["issuetype"]["name"] == "Sub-task"

    async def test_creates_subtask_with_explicit_project(
        self, client: JiraClient, mcp_call: AsyncMock
    ) -> None:
        mcp_call.return_value = {"id": "10003", "key": "OTHER-1", "self": ""}

        await client.create_subtask(
            parent_key="PROJ-1",
            summary="Task",
            project_key="OTHER",
        )

        fields = mcp_call.call_args[0][1]["fields"]
        assert fields["project"]["key"] == "OTHER"


# ---------------------------------------------------------------------------
# Tests — transition_issue
# ---------------------------------------------------------------------------

class TestTransitionIssue:
    async def test_transitions_by_name(
        self, client: JiraClient, mcp_call: AsyncMock
    ) -> None:
        # First call returns transitions, second performs the transition.
        mcp_call.side_effect = [
            {
                "transitions": [
                    {"id": "21", "name": "In Progress", "to": {"name": "In Progress"}},
                    {"id": "31", "name": "Done", "to": {"name": "Done"}},
                ]
            },
            None,
        ]

        await client.transition_issue("PROJ-1", "Done")

        assert mcp_call.await_count == 2
        transition_call = mcp_call.call_args_list[1]
        assert transition_call[0][1]["transition"]["id"] == "31"

    async def test_raises_on_unknown_transition(
        self, client: JiraClient, mcp_call: AsyncMock
    ) -> None:
        mcp_call.return_value = {
            "transitions": [
                {"id": "21", "name": "In Progress", "to": {"name": "In Progress"}},
            ]
        }

        with pytest.raises(ValueError, match="Transition 'Done' not found"):
            await client.transition_issue("PROJ-1", "Done")

    async def test_transition_name_case_insensitive(
        self, client: JiraClient, mcp_call: AsyncMock
    ) -> None:
        mcp_call.side_effect = [
            {"transitions": [{"id": "21", "name": "In Progress", "to": {"name": "In Progress"}}]},
            None,
        ]
        await client.transition_issue("PROJ-1", "in progress")
        assert mcp_call.await_count == 2


# ---------------------------------------------------------------------------
# Tests — search_jql
# ---------------------------------------------------------------------------

class TestSearchJql:
    async def test_returns_parsed_search_result(
        self, client: JiraClient, mcp_call: AsyncMock
    ) -> None:
        mcp_call.return_value = {
            "startAt": 0,
            "maxResults": 50,
            "total": 1,
            "issues": [_issue_payload()],
        }

        result = await client.search_jql('project = PROJ AND status = "To Do"')

        assert isinstance(result, JiraSearchResult)
        assert result.total == 1
        assert len(result.issues) == 1
        assert result.issues[0].key == "PROJ-1"

    async def test_passes_max_results(
        self, client: JiraClient, mcp_call: AsyncMock
    ) -> None:
        mcp_call.return_value = {"startAt": 0, "maxResults": 10, "total": 0, "issues": []}

        await client.search_jql("project = X", max_results=10)

        call_args = mcp_call.call_args[0][1]
        assert call_args["maxResults"] == 10


# ---------------------------------------------------------------------------
# Tests — add_comment
# ---------------------------------------------------------------------------

class TestAddComment:
    async def test_returns_parsed_comment(
        self, client: JiraClient, mcp_call: AsyncMock
    ) -> None:
        mcp_call.return_value = {
            "id": "100",
            "body": "Agent comment",
            "author": {"accountId": "abc", "displayName": "Bot"},
        }

        comment = await client.add_comment("PROJ-1", "Agent comment")

        assert isinstance(comment, JiraComment)
        assert comment.id == "100"
        assert comment.body == "Agent comment"


# ---------------------------------------------------------------------------
# Tests — get_issue_types
# ---------------------------------------------------------------------------

class TestGetIssueTypes:
    async def test_parses_issue_types(
        self, client: JiraClient, mcp_call: AsyncMock
    ) -> None:
        mcp_call.return_value = [
            {"id": "1", "name": "Task", "subtask": False, "description": "A task"},
            {"id": "2", "name": "Sub-task", "subtask": True, "description": ""},
        ]

        types = await client.get_issue_types("PROJ")

        assert len(types) == 2
        assert all(isinstance(t, JiraIssueType) for t in types)
        assert types[1].subtask is True

    async def test_handles_dict_response(
        self, client: JiraClient, mcp_call: AsyncMock
    ) -> None:
        mcp_call.return_value = {
            "issueTypes": [
                {"id": "1", "name": "Bug", "subtask": False},
            ]
        }

        types = await client.get_issue_types("PROJ")
        assert len(types) == 1
        assert types[0].name == "Bug"
