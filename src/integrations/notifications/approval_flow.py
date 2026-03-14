"""Human-in-the-loop approval flow — platform-agnostic.

Sends approval requests via any ``NotificationClient`` and waits for human
response before allowing the workflow to proceed. Uses asyncio.Event for
efficient blocking — no polling loop.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from src.integrations.notifications.protocol import NotificationClient
from src.settings import get_settings

logger = logging.getLogger(__name__)

DEFAULT_APPROVAL_TIMEOUT = 3600  # 1 hour


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"


class ApprovalRequest(BaseModel):
    """An approval request sent to a notification platform."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str
    description: str
    requester: str = "mason"
    channel_id: str = ""
    status: ApprovalStatus = ApprovalStatus.PENDING
    response_by: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None


class ApprovalTrigger(str, Enum):
    """Events that trigger an approval request."""

    PRE_MERGE = "pre_merge"
    ARCHITECTURE_DECISION = "architecture_decision"
    COST_THRESHOLD = "cost_threshold"
    DESTRUCTIVE_OPERATION = "destructive_operation"


class _PendingApproval:
    """Internal holder that pairs a request with its asyncio.Event."""

    def __init__(self, request: ApprovalRequest) -> None:
        self.request = request
        self.event: asyncio.Event = asyncio.Event()


class ApprovalFlow:
    """Manages the human-in-the-loop approval workflow.

    Sends a structured approval request via the provided notification client,
    then waits on an asyncio.Event. The event is set by ``resolve()`` which is
    called by the webhook server when a human clicks Approve/Reject.
    """

    def __init__(
        self,
        *,
        notification_client: NotificationClient,
        timeout: int = DEFAULT_APPROVAL_TIMEOUT,
    ) -> None:
        self._notifier = notification_client
        self._timeout = timeout
        self._pending: dict[str, _PendingApproval] = {}

    async def request_approval(
        self,
        *,
        trigger: ApprovalTrigger,
        title: str,
        description: str,
        channel_id: str = "",
    ) -> ApprovalRequest:
        """Send an approval request and wait (non-polling) for a human response.

        Returns the resolved ApprovalRequest with final status.
        The coroutine is suspended until ``resolve()`` is called or timeout.
        """
        if not channel_id:
            channel_id = get_settings().slack_approval_channel
        request = ApprovalRequest(
            title=title,
            description=description,
            channel_id=channel_id,
        )
        pending = _PendingApproval(request)
        self._pending[request.id] = pending

        await self._notifier.send_approval_request(
            channel_id=channel_id,
            title=f"[{trigger.value}] {title}",
            description=description,
            callback_id=request.id,
        )

        logger.info(
            "ApprovalFlow: sent request %s (%s) — waiting for response (timeout=%ds)",
            request.id,
            trigger.value,
            self._timeout,
        )

        try:
            await asyncio.wait_for(pending.event.wait(), timeout=self._timeout)
        except asyncio.TimeoutError:
            request.status = ApprovalStatus.TIMED_OUT
            request.resolved_at = datetime.now(timezone.utc)
            logger.warning("ApprovalFlow: request %s timed out after %ds", request.id, self._timeout)
            await self._notifier.send_message(
                channel_id=channel_id,
                message=f"Approval request **{title}** timed out after {self._timeout // 60} minutes.",
            )
        finally:
            self._pending.pop(request.id, None)

        return request

    def resolve(
        self,
        request_id: str,
        *,
        approved: bool,
        responder: str = "",
    ) -> None:
        """Resolve a pending approval request (called by webhook receiver).

        Sets the asyncio.Event so the waiting coroutine unblocks immediately.
        """
        pending = self._pending.get(request_id)
        if pending is None:
            logger.warning("ApprovalFlow: unknown or already resolved request %s", request_id)
            return

        pending.request.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        pending.request.response_by = responder
        pending.request.resolved_at = datetime.now(timezone.utc)

        logger.info(
            "ApprovalFlow: request %s %s by %s",
            request_id,
            pending.request.status.value,
            responder,
        )
        pending.event.set()

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        """Return the ApprovalRequest for a pending id, or None."""
        pending = self._pending.get(request_id)
        return pending.request if pending else None

    @property
    def pending_count(self) -> int:
        return len(self._pending)
