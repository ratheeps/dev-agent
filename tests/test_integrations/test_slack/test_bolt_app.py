"""Tests for Slack Bolt app event handlers.

Uses AsyncMock to simulate Bolt event dispatching without a real Slack connection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.integrations.slack.bolt_app import (
    _process_dm,
    _process_mention,
    _safe_ack_and_handle,
    create_bolt_app,
    create_bolt_handler,
)
from src.integrations.slack.conversation_handler import SlackConversationHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conv_handler() -> SlackConversationHandler:
    mock = MagicMock(spec=SlackConversationHandler)
    mock.handle_mention = AsyncMock(return_value="Got it!")
    mock.handle_dm = AsyncMock(return_value="Sure!")
    return mock


def _make_approval_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.handle_approve = AsyncMock()
    adapter.handle_reject = AsyncMock()
    return adapter


# ---------------------------------------------------------------------------
# create_bolt_app / create_bolt_handler
# ---------------------------------------------------------------------------


class TestCreateBoltApp:
    def test_returns_async_app(self) -> None:
        from slack_bolt.async_app import AsyncApp

        slack_client = MagicMock()
        conv_handler = _make_conv_handler()
        approval_adapter = _make_approval_adapter()

        with patch("src.integrations.slack.bolt_app.get_settings") as mock_settings:
            mock_settings.return_value.slack_bot_token = "xoxb-test"
            mock_settings.return_value.slack_signing_secret = "secret"
            app = create_bolt_app(
                slack_client=slack_client,
                conversation_handler=conv_handler,
                approval_adapter=approval_adapter,
            )
        assert isinstance(app, AsyncApp)

    def test_create_bolt_handler(self) -> None:
        from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
        from slack_bolt.async_app import AsyncApp

        mock_app = MagicMock(spec=AsyncApp)
        handler = create_bolt_handler(mock_app)
        assert isinstance(handler, AsyncSlackRequestHandler)


# ---------------------------------------------------------------------------
# _process_mention
# ---------------------------------------------------------------------------


class TestProcessMention:
    @pytest.mark.asyncio
    async def test_strips_bot_mention_and_calls_handler(self) -> None:
        handler = _make_conv_handler()
        event = {
            "user": "U123",
            "text": "<@UBOT> please show status",
            "channel": "C456",
            "ts": "111.222",
            "thread_ts": "",
        }
        await _process_mention(event, handler)
        handler.handle_mention.assert_called_once_with(
            user="U123",
            text="please show status",
            channel="C456",
            thread_ts="",
            ts="111.222",
        )

    @pytest.mark.asyncio
    async def test_multiple_bot_ids_stripped(self) -> None:
        handler = _make_conv_handler()
        event = {
            "user": "U999",
            "text": "<@UBOT1> <@UBOT2> approve",
            "channel": "C001",
            "ts": "1.0",
            "thread_ts": "0.9",
        }
        await _process_mention(event, handler)
        call_kwargs = handler.handle_mention.call_args[1]
        assert call_kwargs["text"] == "approve"
        assert call_kwargs["thread_ts"] == "0.9"

    @pytest.mark.asyncio
    async def test_empty_text_passes_through(self) -> None:
        handler = _make_conv_handler()
        event = {"user": "U1", "text": "<@UBOT>", "channel": "C1", "ts": "1", "thread_ts": ""}
        await _process_mention(event, handler)
        call_kwargs = handler.handle_mention.call_args[1]
        assert call_kwargs["text"] == ""


# ---------------------------------------------------------------------------
# _process_dm
# ---------------------------------------------------------------------------


class TestProcessDm:
    @pytest.mark.asyncio
    async def test_calls_handle_dm(self) -> None:
        handler = _make_conv_handler()
        event = {"user": "U789", "text": "retry please", "channel": "D001"}
        await _process_dm(event, handler)
        handler.handle_dm.assert_called_once_with(
            user="U789", text="retry please", channel="D001"
        )

    @pytest.mark.asyncio
    async def test_empty_event_fields_default_to_empty_string(self) -> None:
        handler = _make_conv_handler()
        await _process_dm({}, handler)
        handler.handle_dm.assert_called_once_with(user="", text="", channel="")


# ---------------------------------------------------------------------------
# _safe_ack_and_handle
# ---------------------------------------------------------------------------


class TestSafeAckAndHandle:
    @pytest.mark.asyncio
    async def test_calls_handler(self) -> None:
        called = []

        async def handler() -> None:
            called.append(True)

        await _safe_ack_and_handle("test", handler)
        assert called == [True]

    @pytest.mark.asyncio
    async def test_logs_exception_without_propagating(self) -> None:
        """Handler exceptions should be swallowed and logged, not propagated."""

        async def bad_handler() -> None:
            raise ValueError("boom")

        # Should not raise
        await _safe_ack_and_handle("test", bad_handler)
