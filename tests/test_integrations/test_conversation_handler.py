"""Tests for AgentConversationHandler intent detection and dispatch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.integrations.teams.conversation_handler import (
    AgentConversationHandler,
    IntentType,
    detect_intent,
)


class TestDetectIntent:
    def test_status_query(self) -> None:
        assert detect_intent("what is the status?") == IntentType.STATUS_QUERY
        assert detect_intent("what are you working on?") == IntentType.STATUS_QUERY
        assert detect_intent("progress update") == IntentType.STATUS_QUERY

    def test_approve(self) -> None:
        assert detect_intent("approved, go ahead") == IntentType.APPROVE
        assert detect_intent("LGTM, ship it") == IntentType.APPROVE
        assert detect_intent("looks good") == IntentType.APPROVE

    def test_reject(self) -> None:
        assert detect_intent("reject this, wrong approach") == IntentType.REJECT
        assert detect_intent("don't proceed with this") == IntentType.REJECT

    def test_retry(self) -> None:
        assert detect_intent("please retry the tests") == IntentType.RETRY
        assert detect_intent("try again") == IntentType.RETRY

    def test_stop(self) -> None:
        assert detect_intent("stop for now") == IntentType.STOP
        assert detect_intent("pause and wait") == IntentType.STOP

    def test_explain(self) -> None:
        assert detect_intent("why did you choose this approach?") == IntentType.EXPLAIN
        assert detect_intent("explain the rationale") == IntentType.EXPLAIN

    def test_debug_help(self) -> None:
        assert detect_intent("the login tests are failing") == IntentType.DEBUG_HELP
        assert detect_intent("something is broken in checkout") == IntentType.DEBUG_HELP

    def test_clarify_instruction(self) -> None:
        assert detect_intent("use Composition API instead of Options API") == IntentType.CLARIFY
        assert detect_intent("should be a POST endpoint not GET") == IntentType.CLARIFY

    def test_unknown_short(self) -> None:
        assert detect_intent("hi") == IntentType.UNKNOWN

    def test_long_instruction_defaults_clarify(self) -> None:
        # Generic instruction — doesn't match any keyword pattern but long enough
        result = detect_intent("make the button red and centered")
        assert result == IntentType.CLARIFY


def _make_handler(pipelines: dict | None = None) -> tuple[AgentConversationHandler, MagicMock, MagicMock]:
    teams_mock = AsyncMock()
    teams_mock.send_message = AsyncMock()
    teams_mock.send_threaded_reply = AsyncMock()

    approval_mock = MagicMock()
    approval_mock.pending_count = 0
    approval_mock._pending = {}  # noqa: SLF001

    handler = AgentConversationHandler(
        teams_client=teams_mock,
        approval_flow=approval_mock,
        pipeline_registry=pipelines or {},
    )
    return handler, teams_mock, approval_mock


def _make_payload(
    text: str,
    sender: str = "alice",
    channel_id: str = "dev-ai",
    thread_id: str = "thread123",
) -> MagicMock:
    payload = MagicMock()
    payload.text = text
    payload.clean_text = text.replace("@DevAI", "").strip()
    payload.sender = sender
    payload.channel_id = channel_id
    payload.thread_id = thread_id
    return payload


class TestHandlerStatus:
    @pytest.mark.asyncio
    async def test_status_no_active_tasks(self) -> None:
        handler, teams_mock, _ = _make_handler()
        payload = _make_payload("@DevAI status")
        reply = await handler.handle_mention(payload)
        assert "No active tasks" in reply

    @pytest.mark.asyncio
    async def test_status_with_active_pipeline(self) -> None:
        pipeline = MagicMock()
        pipeline._context = MagicMock()
        pipeline._context.current_state = "implementing"
        pipeline._context.pr_url = ""

        handler, _, _ = _make_handler(pipelines={"GIFT-1234": pipeline})
        payload = _make_payload("@DevAI what's happening")
        reply = await handler.handle_mention(payload)
        assert "GIFT-1234" in reply

    @pytest.mark.asyncio
    async def test_reply_sent_in_thread(self) -> None:
        handler, teams_mock, _ = _make_handler()
        payload = _make_payload("@DevAI status", thread_id="thread-abc")
        await handler.handle_mention(payload)
        teams_mock.send_threaded_reply.assert_called_once()


class TestHandlerApprove:
    @pytest.mark.asyncio
    async def test_approve_no_pending(self) -> None:
        handler, _, approval_mock = _make_handler()
        approval_mock.pending_count = 0
        payload = _make_payload("@DevAI approved")
        reply = await handler.handle_mention(payload)
        assert "No pending" in reply

    @pytest.mark.asyncio
    async def test_approve_resolves_pending(self) -> None:
        from src.integrations.teams.approval_flow import ApprovalRequest, _PendingApproval

        req = ApprovalRequest(title="test", description="test")
        pending = _PendingApproval(req)

        handler, _, approval_mock = _make_handler()
        approval_mock.pending_count = 1
        approval_mock._pending = {req.id: pending}  # noqa: SLF001
        approval_mock.resolve = MagicMock()

        payload = _make_payload("@DevAI approved, go ahead", sender="alice")
        reply = await handler.handle_mention(payload)
        assert "Approved" in reply
        approval_mock.resolve.assert_called_once()


class TestHandlerFeedback:
    @pytest.mark.asyncio
    async def test_feedback_injected_into_pipeline(self) -> None:
        pipeline = MagicMock()
        pipeline.inject_feedback = MagicMock()
        pipeline._context = MagicMock()
        pipeline._context.current_state = "implementing"
        pipeline._context.pr_url = ""

        handler, _, _ = _make_handler(pipelines={"GIFT-1234": pipeline})
        payload = _make_payload("@DevAI use Composition API instead of Options API")
        reply = await handler.handle_mention(payload)

        pipeline.inject_feedback.assert_called_once()
        assert "Got it" in reply or "Feedback" in reply

    @pytest.mark.asyncio
    async def test_feedback_no_pipeline(self) -> None:
        handler, _, _ = _make_handler(pipelines={})
        payload = _make_payload("@DevAI use REST not GraphQL")
        reply = await handler.handle_mention(payload)
        assert "No active task" in reply


class TestHandlerRegister:
    def test_register_pipeline(self) -> None:
        handler, _, _ = _make_handler()
        pipeline = MagicMock()
        handler.register_pipeline("GIFT-9999", pipeline)
        assert "GIFT-9999" in handler._pipelines

    def test_unregister_pipeline(self) -> None:
        pipeline = MagicMock()
        handler, _, _ = _make_handler(pipelines={"GIFT-9999": pipeline})
        handler.unregister_pipeline("GIFT-9999")
        assert "GIFT-9999" not in handler._pipelines


class TestExtractJiraKey:
    def test_extracts_key(self) -> None:
        from src.integrations.teams.conversation_handler import _extract_jira_key

        assert _extract_jira_key("retry GIFT-1234 tests") == "GIFT-1234"
        assert _extract_jira_key("PROJ-42 is failing") == "PROJ-42"

    def test_returns_none_when_missing(self) -> None:
        from src.integrations.teams.conversation_handler import _extract_jira_key

        assert _extract_jira_key("retry the tests") is None
