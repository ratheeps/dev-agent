"""Tests for BitbucketClient and GitHubSCMAdapter."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.integrations.scm.bitbucket_client import BitbucketClient
from src.integrations.scm.github_adapter import GitHubSCMAdapter
from src.integrations.scm.protocol import SCMClient
from src.schemas.scm import SCMPullRequest


def _make_client(workspace: str = "giftbee") -> BitbucketClient:
    return BitbucketClient(workspace=workspace)


def _mock_http_client(*responses: dict) -> MagicMock:
    """Build a mock httpx.AsyncClient that returns *responses* in order."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    resp_iter = iter(responses)

    def _make_resp(data: dict) -> MagicMock:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = data.get("status", 200)
        mock_resp.raise_for_status = MagicMock()
        if data.get("raise"):
            mock_resp.raise_for_status.side_effect = data["raise"]
        mock_resp.json.return_value = data.get("json", {})
        mock_resp.text = data.get("text", "")
        return mock_resp

    async def _get(*args: object, **kwargs: object) -> MagicMock:
        return _make_resp(next(resp_iter))

    async def _post(*args: object, **kwargs: object) -> MagicMock:
        return _make_resp(next(resp_iter))

    mock_client.get = _get
    mock_client.post = _post
    return mock_client


class TestBitbucketClientInit:
    def test_creates_instance(self) -> None:
        client = _make_client()
        assert client.workspace == "giftbee"

    def test_implements_protocol(self) -> None:
        client = _make_client()
        assert isinstance(client, SCMClient)


class TestBitbucketClientCreatePR:
    @pytest.mark.asyncio
    async def test_create_pr_success(self) -> None:
        client = _make_client()
        pr_data = {
            "id": 42,
            "links": {"html": {"href": "https://bitbucket.org/giftbee/wallet-service/pull-requests/42"}},
            "title": "feat: add balance API",
            "description": "Adds balance endpoint",
            "source": {"branch": {"name": "dev-ai/GIFT-1234"}},
            "destination": {"branch": {"name": "dev"}},
            "state": "OPEN",
        }
        mock_inner = _mock_http_client({"json": pr_data, "status": 201})

        @asynccontextmanager
        async def _mock_client_ctx() -> AsyncGenerator[AsyncMock, None]:
            yield mock_inner

        with patch.object(client, "_client", side_effect=_mock_client_ctx):
            pr = await client.create_pull_request(
                repo="wallet-service",
                title="feat: add balance API",
                body="Adds balance endpoint",
                head_branch="dev-ai/GIFT-1234",
                base_branch="dev",
            )

        assert pr.number == 42
        assert pr.head_branch == "dev-ai/GIFT-1234"
        assert pr.base_branch == "dev"
        assert pr.state == "open"

    @pytest.mark.asyncio
    async def test_create_pr_http_error(self) -> None:
        client = _make_client()
        req = httpx.Request("POST", "https://api.bitbucket.org/2.0/x")
        resp = httpx.Response(400, request=req)
        mock_inner = _mock_http_client({
            "status": 400,
            "raise": httpx.HTTPStatusError("400", request=req, response=resp),
            "json": {},
        })

        @asynccontextmanager
        async def _mock_client_ctx() -> AsyncGenerator[AsyncMock, None]:
            yield mock_inner

        with patch.object(client, "_client", side_effect=_mock_client_ctx):
            with pytest.raises(httpx.HTTPStatusError):
                await client.create_pull_request(
                    repo="wallet-service",
                    title="test",
                    body="",
                    head_branch="dev-ai/GIFT-1234",
                    base_branch="dev",
                )


class TestBitbucketClientGetPR:
    @pytest.mark.asyncio
    async def test_get_pr_success(self) -> None:
        client = _make_client()
        pr_data = {
            "id": 42,
            "links": {"html": {"href": "https://bitbucket.org/giftbee/wallet-service/pull-requests/42"}},
            "title": "feat: test",
            "description": "",
            "source": {"branch": {"name": "dev-ai/GIFT-1234"}},
            "destination": {"branch": {"name": "dev"}},
            "state": "MERGED",
        }
        mock_inner = _mock_http_client({"json": pr_data})

        @asynccontextmanager
        async def _mock_client_ctx() -> AsyncGenerator[AsyncMock, None]:
            yield mock_inner

        with patch.object(client, "_client", side_effect=_mock_client_ctx):
            pr = await client.get_pull_request(repo="wallet-service", pr_number=42)

        assert pr.number == 42
        assert pr.state == "merged"


class TestBitbucketClientAddComment:
    @pytest.mark.asyncio
    async def test_add_comment_success(self) -> None:
        client = _make_client()
        mock_inner = _mock_http_client({"json": {"id": 1}, "status": 201})

        @asynccontextmanager
        async def _mock_client_ctx() -> AsyncGenerator[AsyncMock, None]:
            yield mock_inner

        with patch.object(client, "_client", side_effect=_mock_client_ctx):
            # add_pr_comment returns None on success, should not raise
            await client.add_pr_comment(repo="wallet-service", pr_number=42, body="Test comment")


class TestBitbucketClientCreateBranch:
    @pytest.mark.asyncio
    async def test_create_branch_success(self) -> None:
        client = _make_client()
        # create_branch calls GET (resolve SHA) then POST (create branch)
        source_ref_data = {"target": {"hash": "abc123"}}
        branch_data = {"name": "dev-ai/GIFT-1234", "target": {"hash": "abc123"}}
        mock_inner = _mock_http_client(
            {"json": source_ref_data},   # GET /refs/branches/dev
            {"json": branch_data, "status": 201},  # POST /refs/branches
        )

        @asynccontextmanager
        async def _mock_client_ctx() -> AsyncGenerator[AsyncMock, None]:
            yield mock_inner

        with patch.object(client, "_client", side_effect=_mock_client_ctx):
            branch = await client.create_branch(
                repo="wallet-service",
                branch="dev-ai/GIFT-1234",
                from_ref="dev",
            )

        assert branch.name == "dev-ai/GIFT-1234"
        assert branch.sha == "abc123"


class TestGitHubSCMAdapter:
    def test_implements_protocol(self) -> None:
        mock_client = MagicMock()
        adapter = GitHubSCMAdapter(client=mock_client, org="giftbee")
        assert isinstance(adapter, SCMClient)

    @pytest.mark.asyncio
    async def test_create_pr_delegates_to_github(self) -> None:
        mock_client = MagicMock()
        mock_pr = MagicMock()
        mock_pr.number = 10
        mock_pr.html_url = "https://github.com/giftbee/repo/pull/10"
        mock_pr.title = "test PR"
        mock_pr.body = "body"
        mock_pr.state = "open"
        mock_pr.head = MagicMock(ref="feature-branch")
        mock_pr.base = MagicMock(ref="main")
        mock_client.create_pull_request = AsyncMock(return_value=mock_pr)

        adapter = GitHubSCMAdapter(client=mock_client, org="giftbee")
        pr = await adapter.create_pull_request(
            repo="store-front",
            title="test PR",
            body="body",
            head_branch="feature-branch",
            base_branch="main",
        )

        assert pr.number == 10
        assert pr.state == "open"
        mock_client.create_pull_request.assert_called_once()


class TestSCMProtocolConformance:
    """Ensure both clients structurally conform to SCMClient Protocol."""

    def test_bitbucket_has_required_methods(self) -> None:
        client = _make_client()
        assert hasattr(client, "create_pull_request")
        assert hasattr(client, "get_pull_request")
        assert hasattr(client, "add_pr_comment")
        assert hasattr(client, "get_file_contents")
        assert hasattr(client, "create_branch")

    def test_github_adapter_has_required_methods(self) -> None:
        adapter = GitHubSCMAdapter(client=MagicMock(), org="giftbee")
        assert hasattr(adapter, "create_pull_request")
        assert hasattr(adapter, "get_pull_request")
        assert hasattr(adapter, "add_pr_comment")
        assert hasattr(adapter, "get_file_contents")
        assert hasattr(adapter, "create_branch")
