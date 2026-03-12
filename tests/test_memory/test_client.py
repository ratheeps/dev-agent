"""Tests for the unified memory client.

All DynamoDB calls are mocked via ``unittest.mock`` so that tests run without
any AWS credentials or a local DynamoDB instance.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.memory.client import MemoryClient
from src.memory.config import MemoryConfig
from src.memory.episodic import Episode
from src.memory.semantic import SemanticEntry
from src.memory.short_term import SessionEntry


def _make_config() -> MemoryConfig:
    """Return a config pointing at a fake local endpoint."""
    return MemoryConfig(
        dynamodb_endpoint_url="http://localhost:8000",
        aws_region="us-east-1",
    )


def _mock_dynamo_client() -> MagicMock:
    """Create a mock boto3 DynamoDB client."""
    return MagicMock()


# ---------------------------------------------------------------------------
# Session memory
# ---------------------------------------------------------------------------


class TestSessionMemory:
    @pytest.fixture()
    def client(self) -> MemoryClient:
        return MemoryClient(config=_make_config())

    @patch("src.memory.short_term.boto3.client")
    async def test_store_session(self, mock_boto: MagicMock, client: MemoryClient) -> None:
        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo
        mock_dynamo.put_item.return_value = {}

        entry = await client.store_session("sess-1", {"task": "implement feature"})

        assert isinstance(entry, SessionEntry)
        assert entry.session_id == "sess-1"
        assert entry.data == {"task": "implement feature"}
        assert entry.ttl > 0
        mock_dynamo.put_item.assert_called_once()

    @patch("src.memory.short_term.boto3.client")
    async def test_get_session(self, mock_boto: MagicMock, client: MemoryClient) -> None:
        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo
        mock_dynamo.query.return_value = {
            "Items": [
                {
                    "session_id": {"S": "sess-1"},
                    "timestamp": {"N": "1700000000.0"},
                    "data": {"S": json.dumps({"task": "fix bug"})},
                    "ttl": {"N": "1700086400"},
                }
            ]
        }

        entries = await client.get_session("sess-1")

        assert len(entries) == 1
        assert entries[0].session_id == "sess-1"
        assert entries[0].data["task"] == "fix bug"

    @patch("src.memory.short_term.boto3.client")
    async def test_get_session_dynamo_unavailable(
        self, mock_boto: MagicMock, client: MemoryClient
    ) -> None:
        from botocore.exceptions import ClientError

        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo
        mock_dynamo.query.side_effect = ClientError(
            {"Error": {"Code": "ServiceUnavailable", "Message": "down"}}, "Query"
        )

        entries = await client.get_session("sess-1")
        assert entries == []

    @patch("src.memory.short_term.boto3.client")
    async def test_clear_session(self, mock_boto: MagicMock, client: MemoryClient) -> None:
        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo

        # First call is for get (to find items to delete), second for delete
        mock_dynamo.query.return_value = {
            "Items": [
                {
                    "session_id": {"S": "sess-1"},
                    "timestamp": {"N": "1700000000.0"},
                    "data": {"S": "{}"},
                    "ttl": {"N": "0"},
                }
            ]
        }
        mock_dynamo.delete_item.return_value = {}

        count = await client.clear_session("sess-1")
        assert count == 1
        mock_dynamo.delete_item.assert_called_once()


# ---------------------------------------------------------------------------
# Episodic memory
# ---------------------------------------------------------------------------


class TestEpisodicMemory:
    @pytest.fixture()
    def client(self) -> MemoryClient:
        return MemoryClient(config=_make_config())

    @patch("src.memory.episodic.boto3.client")
    async def test_store_episode(self, mock_boto: MagicMock, client: MemoryClient) -> None:
        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo
        mock_dynamo.put_item.return_value = {}

        episode = Episode(
            agent_id="agent-1",
            task_id="task-42",
            jira_key="PROJ-100",
            action_taken="Fixed null pointer in auth module",
            outcome="success",
            feedback="LGTM",
            tags=["bugfix", "auth"],
        )

        result = await client.store_episode("agent-1", episode)

        assert isinstance(result, Episode)
        assert result.agent_id == "agent-1"
        assert result.jira_key == "PROJ-100"
        mock_dynamo.put_item.assert_called_once()

    @patch("src.memory.episodic.boto3.client")
    async def test_search_episodes_by_tag(self, mock_boto: MagicMock, client: MemoryClient) -> None:
        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo
        mock_dynamo.query.return_value = {
            "Items": [
                {
                    "agent_id": {"S": "agent-1"},
                    "episode_id": {"S": "ep-1"},
                    "task_id": {"S": "task-1"},
                    "jira_key": {"S": "PROJ-10"},
                    "action_taken": {"S": "Fixed auth bug"},
                    "outcome": {"S": "success"},
                    "feedback": {"S": ""},
                    "timestamp": {"N": "1700000000"},
                    "tags": {"S": json.dumps(["bugfix", "auth"])},
                },
                {
                    "agent_id": {"S": "agent-1"},
                    "episode_id": {"S": "ep-2"},
                    "task_id": {"S": "task-2"},
                    "jira_key": {"S": "PROJ-20"},
                    "action_taken": {"S": "Added new API endpoint"},
                    "outcome": {"S": "success"},
                    "feedback": {"S": ""},
                    "timestamp": {"N": "1700001000"},
                    "tags": {"S": json.dumps(["feature", "api"])},
                },
            ]
        }

        results = await client.search_episodes("agent-1", tags=["auth"])
        assert len(results) == 1
        assert results[0].episode_id == "ep-1"

    @patch("src.memory.episodic.boto3.client")
    async def test_search_episodes_by_query(
        self, mock_boto: MagicMock, client: MemoryClient
    ) -> None:
        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo
        mock_dynamo.query.return_value = {
            "Items": [
                {
                    "agent_id": {"S": "agent-1"},
                    "episode_id": {"S": "ep-1"},
                    "task_id": {"S": "task-1"},
                    "jira_key": {"S": "PROJ-10"},
                    "action_taken": {"S": "Fixed null pointer in auth"},
                    "outcome": {"S": "success"},
                    "feedback": {"S": ""},
                    "timestamp": {"N": "1700000000"},
                    "tags": {"S": "[]"},
                },
            ]
        }

        results = await client.search_episodes("agent-1", query="null pointer")
        assert len(results) == 1

    @patch("src.memory.episodic.boto3.client")
    async def test_get_episode(self, mock_boto: MagicMock, client: MemoryClient) -> None:
        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo
        mock_dynamo.get_item.return_value = {
            "Item": {
                "agent_id": {"S": "agent-1"},
                "episode_id": {"S": "ep-1"},
                "task_id": {"S": "task-1"},
                "jira_key": {"S": "PROJ-10"},
                "action_taken": {"S": "Fixed bug"},
                "outcome": {"S": "success"},
                "feedback": {"S": "great"},
                "timestamp": {"N": "1700000000"},
                "tags": {"S": "[]"},
            }
        }

        ep = await client.get_episode("agent-1", "ep-1")
        assert ep is not None
        assert ep.feedback == "great"

    @patch("src.memory.episodic.boto3.client")
    async def test_get_episode_not_found(
        self, mock_boto: MagicMock, client: MemoryClient
    ) -> None:
        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo
        mock_dynamo.get_item.return_value = {}

        ep = await client.get_episode("agent-1", "nonexistent")
        assert ep is None


# ---------------------------------------------------------------------------
# Semantic memory
# ---------------------------------------------------------------------------


class TestSemanticMemory:
    @pytest.fixture()
    def client(self) -> MemoryClient:
        return MemoryClient(config=_make_config())

    @patch("src.memory.semantic.boto3.client")
    async def test_store_semantic(self, mock_boto: MagicMock, client: MemoryClient) -> None:
        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo
        mock_dynamo.put_item.return_value = {}

        entry = await client.store_semantic(
            "conventions", "import_style", "Use absolute imports from src."
        )

        assert isinstance(entry, SemanticEntry)
        assert entry.namespace == "conventions"
        assert entry.key == "import_style"
        mock_dynamo.put_item.assert_called_once()

    @patch("src.memory.semantic.boto3.client")
    async def test_get_semantic(self, mock_boto: MagicMock, client: MemoryClient) -> None:
        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo
        mock_dynamo.get_item.return_value = {
            "Item": {
                "namespace": {"S": "conventions"},
                "key": {"S": "import_style"},
                "value": {"S": "Use absolute imports from src."},
                "metadata": {"S": "{}"},
                "updated_at": {"N": "1700000000"},
            }
        }

        entry = await client.get_semantic("conventions", "import_style")
        assert entry is not None
        assert entry.value == "Use absolute imports from src."

    @patch("src.memory.semantic.boto3.client")
    async def test_get_semantic_not_found(
        self, mock_boto: MagicMock, client: MemoryClient
    ) -> None:
        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo
        mock_dynamo.get_item.return_value = {}

        entry = await client.get_semantic("conventions", "nonexistent")
        assert entry is None

    @patch("src.memory.semantic.boto3.client")
    async def test_search_semantic(self, mock_boto: MagicMock, client: MemoryClient) -> None:
        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo
        mock_dynamo.query.return_value = {
            "Items": [
                {
                    "namespace": {"S": "conventions"},
                    "key": {"S": "import_style"},
                    "value": {"S": "Use absolute imports from src."},
                    "metadata": {"S": "{}"},
                    "updated_at": {"N": "1700000000"},
                },
                {
                    "namespace": {"S": "conventions"},
                    "key": {"S": "naming"},
                    "value": {"S": "Use snake_case for variables"},
                    "metadata": {"S": "{}"},
                    "updated_at": {"N": "1700001000"},
                },
            ]
        }

        results = await client.search_semantic("conventions", query="import")
        assert len(results) == 1
        assert results[0].key == "import_style"

    @patch("src.memory.semantic.boto3.client")
    async def test_seed_from_claude_md(
        self, mock_boto: MagicMock, client: MemoryClient, tmp_path: Any
    ) -> None:
        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo
        mock_dynamo.put_item.return_value = {}

        md_file = tmp_path / "CLAUDE.md"
        md_file.write_text(
            "# Dev-AI\n\n"
            "## Project Overview\n"
            "This is a multi-agent system.\n\n"
            "## Conventions\n"
            "Use ruff for linting.\n\n"
            "## Tech Stack\n"
            "Python 3.12, AWS, CDK.\n"
        )

        count = await client.seed_from_claude_md(str(md_file))
        assert count >= 2
        assert mock_dynamo.put_item.call_count == count

    async def test_seed_from_claude_md_missing_file(self, client: MemoryClient) -> None:
        count = await client.seed_from_claude_md("/nonexistent/CLAUDE.md")
        assert count == 0


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    @pytest.fixture()
    def client(self) -> MemoryClient:
        return MemoryClient(config=_make_config())

    @patch("src.memory.short_term.boto3.client")
    async def test_store_session_dynamo_down(
        self, mock_boto: MagicMock, client: MemoryClient
    ) -> None:
        from botocore.exceptions import ClientError

        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo
        mock_dynamo.put_item.side_effect = ClientError(
            {"Error": {"Code": "ServiceUnavailable", "Message": "down"}}, "PutItem"
        )

        # Should not raise — graceful fallback
        entry = await client.store_session("sess-fail", {"x": 1})
        assert isinstance(entry, SessionEntry)

    @patch("src.memory.episodic.boto3.client")
    async def test_store_episode_dynamo_down(
        self, mock_boto: MagicMock, client: MemoryClient
    ) -> None:
        from botocore.exceptions import ClientError

        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo
        mock_dynamo.put_item.side_effect = ClientError(
            {"Error": {"Code": "ServiceUnavailable", "Message": "down"}}, "PutItem"
        )

        episode = Episode(agent_id="a", action_taken="test")
        result = await client.store_episode("a", episode)
        assert isinstance(result, Episode)

    @patch("src.memory.semantic.boto3.client")
    async def test_search_semantic_dynamo_down(
        self, mock_boto: MagicMock, client: MemoryClient
    ) -> None:
        from botocore.exceptions import ClientError

        mock_dynamo = _mock_dynamo_client()
        mock_boto.return_value = mock_dynamo
        mock_dynamo.query.side_effect = ClientError(
            {"Error": {"Code": "ServiceUnavailable", "Message": "down"}}, "Query"
        )

        results = await client.search_semantic("conventions", query="anything")
        assert results == []
