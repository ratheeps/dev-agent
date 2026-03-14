"""Tests for SlackApprovalAdapter — button click → ApprovalFlow bridge."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.integrations.slack.approval_adapter import SlackApprovalAdapter
from src.integrations.notifications.approval_flow import (
    ApprovalRequest,
    _PendingApproval,
)


def _make_adapter() -> tuple[SlackApprovalAdapter, MagicMock, MagicMock]:
    slack_mock = AsyncMock()
    slack_mock.update_approval_message = AsyncMock()

    req = ApprovalRequest(title="Deploy PR", description="Ready")
    pending = _PendingApproval(req)

    approval_mock = MagicMock()
    approval_mock.pending_count = 1
    approval_mock._pending = {req.id: pending}  # noqa: SLF001
    approval_mock.get_request = MagicMock(return_value=req)
    approval_mock.resolve = MagicMock()

    adapter = SlackApprovalAdapter(slack_client=slack_mock, approval_flow=approval_mock)
    return adapter, approval_mock, slack_mock


class TestApprovalAdapterApprove:
    @pytest.mark.asyncio
    async def test_approve_calls_resolve(self) -> None:
        adapter, approval_mock, _ = _make_adapter()
        result = await adapter.handle_approve(
            callback_id="cb1",
            user_id="U123",
            user_name="alice",
            channel_id="C01",
            message_ts="ts1",
        )
        assert result["ok"] is True
        assert result["action"] == "approved"
        approval_mock.resolve.assert_called_once_with(
            "cb1", approved=True, responder="alice"
        )

    @pytest.mark.asyncio
    async def test_approve_updates_slack_message(self) -> None:
        adapter, _, slack_mock = _make_adapter()
        await adapter.handle_approve(
            callback_id="cb1",
            user_id="U123",
            user_name="alice",
            channel_id="C01",
            message_ts="ts1",
        )
        slack_mock.update_approval_message.assert_called_once()
        call_kwargs = slack_mock.update_approval_message.call_args.kwargs
        assert call_kwargs["approved"] is True

    @pytest.mark.asyncio
    async def test_approve_not_found_returns_error(self) -> None:
        adapter, approval_mock, _ = _make_adapter()
        approval_mock.get_request = MagicMock(return_value=None)
        result = await adapter.handle_approve(
            callback_id="unknown",
            user_id="U123",
            user_name="alice",
            channel_id="C01",
            message_ts="ts1",
        )
        assert result["ok"] is False
        assert result["error"] == "not_found"
        approval_mock.resolve.assert_not_called()


class TestApprovalAdapterReject:
    @pytest.mark.asyncio
    async def test_reject_calls_resolve_with_false(self) -> None:
        adapter, approval_mock, _ = _make_adapter()
        result = await adapter.handle_reject(
            callback_id="cb1",
            user_id="U456",
            user_name="bob",
            channel_id="C01",
            message_ts="ts1",
        )
        assert result["ok"] is True
        assert result["action"] == "rejected"
        approval_mock.resolve.assert_called_once_with(
            "cb1", approved=False, responder="bob"
        )

    @pytest.mark.asyncio
    async def test_reject_updates_slack_message_as_rejected(self) -> None:
        adapter, _, slack_mock = _make_adapter()
        await adapter.handle_reject(
            callback_id="cb1",
            user_id="U456",
            user_name="bob",
            channel_id="C01",
            message_ts="ts1",
        )
        call_kwargs = slack_mock.update_approval_message.call_args.kwargs
        assert call_kwargs["approved"] is False
