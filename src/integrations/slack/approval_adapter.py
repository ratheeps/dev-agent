"""Slack button interaction → ApprovalFlow bridge.

Called by the Slack Bolt app when a user clicks Approve or Reject on
a Block Kit message. Resolves the pending approval and updates the
original message to show the result (prevents double-clicks).
"""

from __future__ import annotations

import logging
from typing import Any

from src.integrations.slack.notification_client import SlackNotificationClient

logger = logging.getLogger(__name__)


class SlackApprovalAdapter:
    """Bridges Slack block_actions interactions with the ApprovalFlow.

    Parameters
    ----------
    slack_client:
        For updating the original approval message after resolution.
    approval_flow:
        The shared ApprovalFlow instance used by the pipeline.
    """

    def __init__(
        self,
        *,
        slack_client: SlackNotificationClient,
        approval_flow: Any,
    ) -> None:
        self._slack = slack_client
        self._approval_flow = approval_flow

    async def handle_approve(
        self,
        callback_id: str,
        user_id: str,
        user_name: str,
        channel_id: str,
        message_ts: str,
        title: str = "",
    ) -> dict[str, Any]:
        """Handle an Approve button click.

        Resolves the pending approval and updates the Slack message.

        Parameters
        ----------
        callback_id:
            The approval request ID embedded in the button value.
        user_id:
            Slack user ID of the approver.
        user_name:
            Display name of the approver (for logging / message update).
        channel_id:
            Channel where the approval message was posted.
        message_ts:
            Timestamp of the original approval message (for chat.update).
        title:
            Original approval title (used when updating message text).
        """
        request = self._approval_flow.get_request(callback_id)
        if request is None:
            logger.warning(
                "SlackApprovalAdapter: approval %s not found or already resolved", callback_id
            )
            return {"ok": False, "error": "not_found"}

        self._approval_flow.resolve(
            callback_id,
            approved=True,
            responder=user_name or user_id,
        )

        logger.info(
            "SlackApprovalAdapter: %s approved request %s", user_name or user_id, callback_id
        )

        # Update the original Slack message so buttons disappear
        if channel_id and message_ts:
            await self._slack.update_approval_message(
                channel_id=channel_id,
                message_ts=message_ts,
                title=title or request.title,
                approved=True,
                responder=user_name or user_id,
            )

        return {"ok": True, "action": "approved", "request_id": callback_id}

    async def handle_reject(
        self,
        callback_id: str,
        user_id: str,
        user_name: str,
        channel_id: str,
        message_ts: str,
        title: str = "",
    ) -> dict[str, Any]:
        """Handle a Reject button click.

        Resolves the pending approval (as rejected) and updates the Slack message.
        """
        request = self._approval_flow.get_request(callback_id)
        if request is None:
            logger.warning(
                "SlackApprovalAdapter: approval %s not found or already resolved", callback_id
            )
            return {"ok": False, "error": "not_found"}

        self._approval_flow.resolve(
            callback_id,
            approved=False,
            responder=user_name or user_id,
        )

        logger.info(
            "SlackApprovalAdapter: %s rejected request %s", user_name or user_id, callback_id
        )

        if channel_id and message_ts:
            await self._slack.update_approval_message(
                channel_id=channel_id,
                message_ts=message_ts,
                title=title or request.title,
                approved=False,
                responder=user_name or user_id,
            )

        return {"ok": True, "action": "rejected", "request_id": callback_id}
