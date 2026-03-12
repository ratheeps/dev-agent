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
        extra_facts: list[dict[str, str]] | None = None,
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
            Unique ID for correlating the approval response. Auto-generated when not provided.
        extra_facts:
            Optional extra key/value facts (e.g., repo, branch, PR link, cost) to include in the card.
        """
        resolved_callback_id = callback_id or str(uuid.uuid4())

        adaptive_card = _build_approval_card(
            title, description, resolved_callback_id, extra_facts=extra_facts
        )

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

    # ------------------------------------------------------------------
    # Status cards and threaded replies
    # ------------------------------------------------------------------

    async def send_status_card(
        self,
        channel_id: str,
        *,
        jira_key: str,
        current_state: str,
        task_title: str = "",
        pr_url: str = "",
        repo: str = "",
        branch: str = "",
        cost_usd: float = 0.0,
        progress_pct: int = 0,
    ) -> TeamsMessageResponse:
        """Send a rich status Adaptive Card to a Teams channel.

        Shows the current state of the agent's work on a Jira ticket.
        """
        card = _build_status_card(
            jira_key=jira_key,
            current_state=current_state,
            task_title=task_title,
            pr_url=pr_url,
            repo=repo,
            branch=branch,
            cost_usd=cost_usd,
            progress_pct=progress_pct,
        )
        raw = await self._call(
            self._tool("send_channel_message"),
            {
                "channelId": channel_id,
                "body": {"content": str(card), "contentType": "html"},
                "attachments": [
                    {
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": card,
                    }
                ],
            },
        )
        return _parse_message_response(raw)

    async def send_threaded_reply(
        self,
        channel_id: str,
        thread_id: str,
        message: str,
    ) -> TeamsMessageResponse:
        """Reply in an existing Teams thread (keeps conversation coherent)."""
        raw = await self._call(
            self._tool("reply_to_message"),
            {
                "channelId": channel_id,
                "messageId": thread_id,
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
    extra_facts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build an Adaptive Card JSON payload for an approval request."""
    facts: list[dict[str, str]] = [
        {"title": "Status", "value": "Pending Approval"},
        {"title": "Request ID", "value": callback_id},
    ]
    if extra_facts:
        facts.extend(extra_facts)

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": f"🤖 Approval Required: {title}",
                "size": "Large",
                "weight": "Bolder",
                "wrap": True,
                "color": "Attention",
            },
            {
                "type": "TextBlock",
                "text": description,
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": facts,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "✅ Approve",
                "style": "positive",
                "data": {
                    "action": "approve",
                    "callbackId": callback_id,
                },
            },
            {
                "type": "Action.Submit",
                "title": "❌ Reject",
                "style": "destructive",
                "data": {
                    "action": "reject",
                    "callbackId": callback_id,
                },
            },
        ],
    }


def _build_status_card(
    *,
    jira_key: str,
    current_state: str,
    task_title: str = "",
    pr_url: str = "",
    repo: str = "",
    branch: str = "",
    cost_usd: float = 0.0,
    progress_pct: int = 0,
) -> dict[str, Any]:
    """Build an Adaptive Card showing current agent task status."""
    state_emoji = {
        "implementing": "⚙️",
        "testing": "🧪",
        "awaiting_approval": "⏳",
        "pr_created": "📬",
        "reviewing": "👀",
        "done": "✅",
        "failed": "❌",
    }.get(current_state, "🔄")

    facts: list[dict[str, str]] = [
        {"title": "Jira", "value": jira_key},
        {"title": "State", "value": f"{state_emoji} {current_state}"},
    ]
    if task_title:
        facts.append({"title": "Task", "value": task_title})
    if repo:
        facts.append({"title": "Repo", "value": repo})
    if branch:
        facts.append({"title": "Branch", "value": branch})
    if pr_url:
        facts.append({"title": "PR", "value": pr_url})
    if cost_usd > 0:
        facts.append({"title": "Cost", "value": f"${cost_usd:.4f}"})

    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": f"🤖 Dev-AI Status: {jira_key}",
            "size": "Large",
            "weight": "Bolder",
            "wrap": True,
        },
        {"type": "FactSet", "facts": facts},
    ]

    if progress_pct > 0:
        body.append({
            "type": "ColumnSet",
            "columns": [
                {
                    "type": "Column",
                    "width": "stretch",
                    "items": [{
                        "type": "TextBlock",
                        "text": f"Progress: {progress_pct}%",
                        "isSubtle": True,
                    }],
                }
            ],
        })

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
    }
