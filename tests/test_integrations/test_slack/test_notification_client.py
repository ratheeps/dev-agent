"""Tests for SlackNotificationClient Block Kit message building."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.integrations.slack.notification_client import (
    SlackNotificationClient,
    _build_approval_blocks,
    _build_status_blocks,
)


def _make_client() -> SlackNotificationClient:
    client = SlackNotificationClient(bot_token="xoxb-test")
    mock_web = AsyncMock()
    mock_web.chat_postMessage = AsyncMock(
        return_value=MagicMock(data={"ok": True, "ts": "111.222", "channel": "C01"})
    )
    mock_web.conversations_open = AsyncMock(
        return_value=MagicMock(data={"channel": {"id": "D01"}})
    )
    mock_web.chat_update = AsyncMock(return_value=MagicMock(data={"ok": True}))
    client._client = mock_web
    return client


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_message_calls_chat_post(self) -> None:
        client = _make_client()
        resp = await client.send_message(channel_id="C01", message="hello")
        assert resp.ok is True
        client._client.chat_postMessage.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_passes_channel(self) -> None:
        client = _make_client()
        await client.send_message(channel_id="C01", message="test")
        call_kwargs = client._client.chat_postMessage.call_args
        assert call_kwargs.kwargs["channel"] == "C01"


class TestSendApprovalRequest:
    @pytest.mark.asyncio
    async def test_approval_request_returns_callback_id(self) -> None:
        client = _make_client()
        resp = await client.send_approval_request(
            channel_id="C01",
            title="Deploy to prod",
            description="Ready to deploy",
            callback_id="test-callback-id",
        )
        assert resp.callback_id == "test-callback-id"
        assert resp.status == "pending"

    @pytest.mark.asyncio
    async def test_approval_auto_generates_callback_id(self) -> None:
        client = _make_client()
        resp = await client.send_approval_request(
            channel_id="C01",
            title="Test",
            description="Test",
        )
        assert resp.callback_id != ""

    @pytest.mark.asyncio
    async def test_approval_includes_extra_facts_in_blocks(self) -> None:
        client = _make_client()
        await client.send_approval_request(
            channel_id="C01",
            title="Test",
            description="Test",
            callback_id="cb1",
            extra_facts=[{"title": "Repo", "value": "my-repo"}],
        )
        call_kwargs = client._client.chat_postMessage.call_args.kwargs
        blocks_str = str(call_kwargs.get("blocks", ""))
        assert "my-repo" in blocks_str


class TestSendDirectMessage:
    @pytest.mark.asyncio
    async def test_dm_opens_conversation_first(self) -> None:
        client = _make_client()
        await client.send_direct_message(user_id="U123", message="hello")
        client._client.conversations_open.assert_called_once_with(users="U123")
        client._client.chat_postMessage.assert_called_once()


class TestSendThreadedReply:
    @pytest.mark.asyncio
    async def test_threaded_reply_passes_thread_ts(self) -> None:
        client = _make_client()
        await client.send_threaded_reply(
            channel_id="C01", thread_id="parent-ts", message="reply"
        )
        call_kwargs = client._client.chat_postMessage.call_args.kwargs
        assert call_kwargs["thread_ts"] == "parent-ts"


class TestUpdateApprovalMessage:
    @pytest.mark.asyncio
    async def test_update_shows_approved(self) -> None:
        client = _make_client()
        await client.update_approval_message(
            channel_id="C01",
            message_ts="ts1",
            title="Deploy to prod",
            approved=True,
            responder="alice",
        )
        client._client.chat_update.assert_called_once()
        call_kwargs = client._client.chat_update.call_args.kwargs
        assert "✅" in call_kwargs["text"] or "Approved" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_update_shows_rejected(self) -> None:
        client = _make_client()
        await client.update_approval_message(
            channel_id="C01",
            message_ts="ts1",
            title="Deploy to prod",
            approved=False,
            responder="bob",
        )
        call_kwargs = client._client.chat_update.call_args.kwargs
        assert "❌" in call_kwargs["text"] or "Rejected" in call_kwargs["text"]


class TestBuildApprovalBlocks:
    def test_blocks_have_approve_and_reject_buttons(self) -> None:
        blocks = _build_approval_blocks("Title", "Description", "cb-1")
        actions = next(b for b in blocks if b.get("type") == "actions")
        action_ids = [e["action_id"] for e in actions["elements"]]
        assert "approve_button" in action_ids
        assert "reject_button" in action_ids

    def test_callback_id_embedded_in_button_values(self) -> None:
        blocks = _build_approval_blocks("Title", "Description", "my-callback")
        actions = next(b for b in blocks if b.get("type") == "actions")
        values = [e["value"] for e in actions["elements"]]
        assert all(v == "my-callback" for v in values)

    def test_extra_facts_appear_in_blocks(self) -> None:
        blocks = _build_approval_blocks(
            "Title", "Desc", "cb", extra_facts=[{"title": "Cost", "value": "$2.50"}]
        )
        blocks_str = str(blocks)
        assert "$2.50" in blocks_str


class TestBuildStatusBlocks:
    def test_status_blocks_include_jira_key(self) -> None:
        blocks = _build_status_blocks(
            jira_key="GIFT-1234",
            current_state="implementing",
        )
        blocks_str = str(blocks)
        assert "GIFT-1234" in blocks_str

    def test_status_blocks_include_pr_url(self) -> None:
        blocks = _build_status_blocks(
            jira_key="GIFT-1",
            current_state="pr_created",
            pr_url="https://github.com/org/repo/pull/42",
        )
        blocks_str = str(blocks)
        assert "https://github.com/org/repo/pull/42" in blocks_str
