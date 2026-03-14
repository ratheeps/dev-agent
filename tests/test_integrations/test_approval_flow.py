"""Tests for ApprovalFlow with asyncio.Event."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.integrations.notifications.approval_flow import (
    ApprovalFlow,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalTrigger,
    _PendingApproval,
)


def _make_flow(timeout: int = 60) -> ApprovalFlow:
    notifier_mock = AsyncMock()
    notifier_mock.send_approval_request = AsyncMock(
        return_value=MagicMock(ts="ts1", callback_id="cb1", status="pending")
    )
    notifier_mock.send_message = AsyncMock()
    return ApprovalFlow(notification_client=notifier_mock, timeout=timeout)


class TestApprovalFlowResolve:
    @pytest.mark.asyncio
    async def test_resolve_unblocks_request(self) -> None:
        flow = _make_flow()

        async def _approve_after_short_delay() -> None:
            await asyncio.sleep(0.05)
            for req_id in list(flow._pending.keys()):  # noqa: SLF001
                flow.resolve(req_id, approved=True, responder="alice")

        task = asyncio.create_task(_approve_after_short_delay())
        result = await flow.request_approval(
            trigger=ApprovalTrigger.PRE_MERGE,
            title="Test approval",
            description="Test",
        )
        await task

        assert result.status == ApprovalStatus.APPROVED
        assert result.response_by == "alice"
        assert result.resolved_at is not None

    @pytest.mark.asyncio
    async def test_reject_sets_status(self) -> None:
        flow = _make_flow()

        async def _reject_after_delay() -> None:
            await asyncio.sleep(0.05)
            for req_id in list(flow._pending.keys()):  # noqa: SLF001
                flow.resolve(req_id, approved=False, responder="bob")

        task = asyncio.create_task(_reject_after_delay())
        result = await flow.request_approval(
            trigger=ApprovalTrigger.PRE_MERGE,
            title="Test rejection",
            description="Test",
        )
        await task

        assert result.status == ApprovalStatus.REJECTED
        assert result.response_by == "bob"

    @pytest.mark.asyncio
    async def test_timeout_sets_timed_out_status(self) -> None:
        flow = _make_flow(timeout=1)  # 1 second timeout
        result = await flow.request_approval(
            trigger=ApprovalTrigger.PRE_MERGE,
            title="Timeout test",
            description="Will time out",
        )
        assert result.status == ApprovalStatus.TIMED_OUT

    def test_resolve_unknown_id_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        flow = _make_flow()
        import logging

        with caplog.at_level(logging.WARNING):
            flow.resolve("nonexistent", approved=True)

        assert "unknown or already resolved" in caplog.text

    def test_pending_count_tracks_active(self) -> None:
        flow = _make_flow()
        assert flow.pending_count == 0

        req = ApprovalRequest(title="test", description="test")
        flow._pending[req.id] = _PendingApproval(req)  # noqa: SLF001
        assert flow.pending_count == 1

        flow._pending.pop(req.id)  # noqa: SLF001
        assert flow.pending_count == 0

    def test_get_request_returns_pending(self) -> None:
        flow = _make_flow()
        req = ApprovalRequest(title="test", description="test")
        flow._pending[req.id] = _PendingApproval(req)  # noqa: SLF001

        found = flow.get_request(req.id)
        assert found is not None
        assert found.id == req.id

    def test_get_request_missing_returns_none(self) -> None:
        flow = _make_flow()
        assert flow.get_request("doesnotexist") is None

    @pytest.mark.asyncio
    async def test_pending_removed_after_resolve(self) -> None:
        flow = _make_flow()

        async def _resolve() -> None:
            await asyncio.sleep(0.05)
            for req_id in list(flow._pending.keys()):  # noqa: SLF001
                flow.resolve(req_id, approved=True)

        task = asyncio.create_task(_resolve())
        await flow.request_approval(
            trigger=ApprovalTrigger.PRE_MERGE,
            title="Cleanup test",
            description="Test",
        )
        await task
        assert flow.pending_count == 0


class TestApprovalFlowConcurrent:
    @pytest.mark.asyncio
    async def test_multiple_concurrent_requests(self) -> None:
        """Multiple concurrent approval requests resolve independently."""
        flow = _make_flow()
        results: list[str] = []

        async def _request_and_record(title: str, approved: bool, delay: float) -> None:
            async def _resolve() -> None:
                await asyncio.sleep(delay)
                for req_id in list(flow._pending.keys()):  # noqa: SLF001
                    p = flow._pending[req_id]  # noqa: SLF001
                    if p.request.title == title:
                        flow.resolve(req_id, approved=approved)
                        return

            asyncio.create_task(_resolve())
            result = await flow.request_approval(
                trigger=ApprovalTrigger.PRE_MERGE,
                title=title,
                description="test",
            )
            results.append(f"{title}={result.status.value}")

        await asyncio.gather(
            _request_and_record("req-A", True, 0.05),
            _request_and_record("req-B", False, 0.1),
        )

        assert "req-A=approved" in results
        assert "req-B=rejected" in results
