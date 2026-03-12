"""Human-in-the-loop approval flow via Microsoft Teams.

Sends approval requests to a Teams channel and waits for human response
before allowing the workflow to proceed.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from src.integrations.teams.notification_client import TeamsNotificationClient

logger = logging.getLogger(__name__)

DEFAULT_APPROVAL_TIMEOUT = 3600  # 1 hour


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"


class ApprovalRequest(BaseModel):
    """An approval request sent to Teams."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str
    description: str
    requester: str = "dev-ai"
    channel_id: str = "dev-ai-approvals"
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


class ApprovalFlow:
    """Manages the human-in-the-loop approval workflow.

    Sends a structured approval request to Teams, then polls for a response.
    The workflow is paused until approval is received, rejected, or timed out.
    """

    def __init__(
        self,
        *,
        teams_client: TeamsNotificationClient,
        timeout: int = DEFAULT_APPROVAL_TIMEOUT,
        poll_interval: int = 15,
    ) -> None:
        self._teams = teams_client
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._pending: dict[str, ApprovalRequest] = {}

    async def request_approval(
        self,
        *,
        trigger: ApprovalTrigger,
        title: str,
        description: str,
        channel_id: str = "dev-ai-approvals",
    ) -> ApprovalRequest:
        """Send an approval request and wait for a human response.

        Returns the resolved ApprovalRequest with final status.
        """
        request = ApprovalRequest(
            title=title,
            description=description,
            channel_id=channel_id,
        )
        self._pending[request.id] = request

        # Send the request to Teams
        await self._teams.send_approval_request(
            channel_id=channel_id,
            title=f"[{trigger.value}] {title}",
            description=description,
            callback_id=request.id,
        )

        logger.info(
            "ApprovalFlow: sent request %s (%s) — waiting for response",
            request.id,
            trigger.value,
        )

        # Poll for response
        elapsed = 0
        while elapsed < self._timeout:
            # In production, this would check a callback endpoint or webhook
            # For now, the approval is simulated via the pending dict
            if request.status != ApprovalStatus.PENDING:
                break

            await asyncio.sleep(self._poll_interval)
            elapsed += self._poll_interval

        # Handle timeout
        if request.status == ApprovalStatus.PENDING:
            request.status = ApprovalStatus.TIMED_OUT
            request.resolved_at = datetime.now(timezone.utc)
            logger.warning(
                "ApprovalFlow: request %s timed out after %ds",
                request.id,
                self._timeout,
            )
            await self._teams.send_message(
                channel_id=channel_id,
                message=f"Approval request **{title}** timed out after {self._timeout // 60} minutes.",
            )

        self._pending.pop(request.id, None)
        return request

    def resolve(
        self,
        request_id: str,
        *,
        approved: bool,
        responder: str = "",
    ) -> None:
        """Resolve a pending approval request (called by webhook/callback)."""
        request = self._pending.get(request_id)
        if request is None:
            logger.warning("ApprovalFlow: unknown request %s", request_id)
            return

        request.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        request.response_by = responder
        request.resolved_at = datetime.now(timezone.utc)

        logger.info(
            "ApprovalFlow: request %s %s by %s",
            request_id,
            request.status.value,
            responder,
        )

    @property
    def pending_count(self) -> int:
        return len(self._pending)
