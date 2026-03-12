"""Typed async wrapper around Microsoft Teams MCP tools.

Provides methods for sending channel messages, direct messages, and
interactive approval request cards.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Coroutine

from src.schemas.teams import TeamsApprovalResponse, TeamsMessageResponse

logger = logging.getLogger(__name__)

McpCallFn = Callable[[str, dict[str, Any]], Coroutine[Any, Any, Any]]


class TeamsNotificationClient:
    """High-level async Teams notification client backed by MCP tools.

    Parameters
    ----------
    mcp_call:
        Async callable ``(tool_name, arguments) -> Any`` provided by the
        agent runtime.
    tool_prefix:
        Prefix applied to Teams MCP tool names.
    """

    def __init__(
        self,
        mcp_call: McpCallFn,
        tool_prefix: str = "mcp__teams__",
    ) -> None:
        self._call = mcp_call
        self._prefix = tool_prefix

    def _tool(self, name: str) -> str:
        return f"{self._prefix}{name}"

    # ------------------------------------------------------------------
    # Channel messages
    # ------------------------------------------------------------------

    async def send_message(
        self,
        channel_id: str,
        message: str,
    ) -> TeamsMessageResponse:
        """Send a plain-text message to a Teams channel.

        Parameters
        ----------
        channel_id:
            The Teams channel ID.
        message:
            Plain-text or HTML message body.
        """
        raw = await self._call(
            self._tool("send_channel_message"),
            {
                "channelId": channel_id,
                "body": {"content": message, "contentType": "text"},
            },
        )
        return _parse_message_response(raw)

    # ------------------------------------------------------------------
    # Approval requests
    # ------------------------------------------------------------------

    async def send_approval_request(
        self,
        channel_id: str,
        title: str,
        description: str,
        callback_id: str | None = None,
    ) -> TeamsApprovalResponse:
        """Send an Adaptive Card approval request to a Teams channel.

        The card includes *Approve* and *Reject* action buttons.  The
        ``callback_id`` can be used by the agent runtime to correlate the
        user's response back to the originating workflow.

        Parameters
        ----------
        channel_id:
            Target channel.
        title:
            Short title displayed at the top of the card.
        description:
            Longer description shown in the card body.
        callback_id:
            Unique ID for correlating the approval response.  Auto-generated
            when not provided.
        """
        resolved_callback_id = callback_id or str(uuid.uuid4())

        adaptive_card = _build_approval_card(title, description, resolved_callback_id)

        raw = await self._call(
            self._tool("send_channel_message"),
            {
                "channelId": channel_id,
                "body": {"content": "", "contentType": "html"},
                "attachments": [
                    {
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": adaptive_card,
                    }
                ],
            },
        )

        message_id = ""
        if isinstance(raw, dict):
            message_id = str(raw.get("id", ""))

        return TeamsApprovalResponse(
            message_id=message_id,
            callback_id=resolved_callback_id,
            status="pending",
        )

    # ------------------------------------------------------------------
    # Direct messages
    # ------------------------------------------------------------------

    async def send_direct_message(
        self,
        user_id: str,
        message: str,
    ) -> TeamsMessageResponse:
        """Send a 1:1 direct message to a specific Teams user.

        Parameters
        ----------
        user_id:
            The Azure AD / Teams user ID.
        message:
            Plain-text or HTML message body.
        """
        raw = await self._call(
            self._tool("send_direct_message"),
            {
                "userId": user_id,
                "body": {"content": message, "contentType": "text"},
            },
        )
        return _parse_message_response(raw)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_message_response(raw: Any) -> TeamsMessageResponse:
    if isinstance(raw, dict):
        return TeamsMessageResponse.model_validate(raw)
    return TeamsMessageResponse.model_validate_json(str(raw))


def _build_approval_card(
    title: str,
    description: str,
    callback_id: str,
) -> dict[str, Any]:
    """Build an Adaptive Card JSON payload for an approval request."""
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": title,
                "size": "Large",
                "weight": "Bolder",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": description,
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Status", "value": "Pending Approval"},
                    {"title": "Request ID", "value": callback_id},
                ],
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Approve",
                "data": {
                    "action": "approve",
                    "callbackId": callback_id,
                },
            },
            {
                "type": "Action.Submit",
                "title": "Reject",
                "data": {
                    "action": "reject",
                    "callbackId": callback_id,
                },
            },
        ],
    }
