"""Async Slack notification client implementing the NotificationClient protocol.

Uses slack-sdk AsyncWebClient for all Slack API calls. Builds Block Kit
messages instead of Adaptive Cards (Teams equivalent).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from src.resilience.circuit_breaker import CircuitBreaker
from src.resilience.rate_limiter import TokenBucketRateLimiter
from src.schemas.slack import SlackApprovalResponse, SlackMessageResponse

logger = logging.getLogger(__name__)


class SlackClientError(Exception):
    """Raised when a Slack API call fails after circuit-breaker / rate-limit checks."""

    def __init__(self, message: str, *, api_error: SlackApiError | None = None) -> None:
        super().__init__(message)
        self.api_error = api_error


class SlackNotificationClient:
    """High-level async Slack notification client backed by slack-sdk.

    Satisfies the ``NotificationClient`` protocol — no subclassing required.

    Includes a per-instance circuit breaker and rate limiter so that
    transient Slack API failures degrade gracefully rather than cascading.

    Parameters
    ----------
    bot_token:
        Slack bot OAuth token (xoxb-...). Required for all API calls.
    requests_per_minute:
        Outgoing API call rate limit (default: 30 rpm).
    """

    def __init__(self, bot_token: str, *, requests_per_minute: int = 30) -> None:
        self._client = AsyncWebClient(token=bot_token)
        self._circuit = CircuitBreaker(service="slack", failure_threshold=5, recovery_timeout=60.0)
        self._rate_limiter = TokenBucketRateLimiter(
            service="slack",
            max_tokens=float(requests_per_minute),
            refill_rate=float(requests_per_minute) / 60.0,
        )

    # ------------------------------------------------------------------
    # Channel messages
    # ------------------------------------------------------------------

    async def send_message(
        self,
        channel_id: str,
        message: str,
    ) -> SlackMessageResponse:
        """Send a plain-text message to a Slack channel or DM.

        Parameters
        ----------
        channel_id:
            The Slack channel ID (C...) or DM channel ID (D...).
        message:
            Plain-text message body. Supports Slack mrkdwn formatting.
        """
        await self._rate_limiter.acquire()
        try:
            resp = await self._circuit.call(
                self._client.chat_postMessage,
                channel=channel_id,
                text=message,
                mrkdwn=True,
            )
        except SlackApiError as exc:
            logger.error("Slack send_message failed channel=%s: %s", channel_id, exc)
            raise SlackClientError(
                f"Failed to send message to {channel_id}", api_error=exc
            ) from exc
        return _parse_message_response(resp.data)

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
    ) -> SlackApprovalResponse:
        """Send an interactive Block Kit approval message to a Slack channel.

        The message includes *Approve* and *Reject* buttons. ``callback_id``
        is embedded in button values so the webhook can correlate the response.

        Parameters
        ----------
        channel_id:
            Target channel.
        title:
            Short title shown at the top of the message.
        description:
            Longer description in the message body.
        callback_id:
            Unique ID for correlating the approval response. Auto-generated
            when not provided.
        extra_facts:
            Optional key/value pairs shown as context (e.g. repo, branch, cost).
        """
        resolved_callback_id = callback_id or str(uuid.uuid4())
        blocks = _build_approval_blocks(
            title, description, resolved_callback_id, extra_facts=extra_facts
        )

        await self._rate_limiter.acquire()
        try:
            resp = await self._circuit.call(
                self._client.chat_postMessage,
                channel=channel_id,
                text=f"🤖 Approval Required: {title}",
                blocks=blocks,
            )
        except SlackApiError as exc:
            logger.error("Slack send_approval_request failed channel=%s: %s", channel_id, exc)
            raise SlackClientError(
                f"Failed to send approval request to {channel_id}", api_error=exc
            ) from exc

        data = resp.data if isinstance(resp.data, dict) else {}
        return SlackApprovalResponse(
            ok=bool(data.get("ok", True)),
            ts=str(data.get("ts", "")),
            channel=str(data.get("channel", channel_id)),
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
    ) -> SlackMessageResponse:
        """Send a direct message to a Slack user.

        Opens a DM conversation if one doesn't exist, then posts the message.

        Parameters
        ----------
        user_id:
            The Slack user ID (U...).
        message:
            Message body.
        """
        await self._rate_limiter.acquire()
        try:
            conv = await self._circuit.call(self._client.conversations_open, users=user_id)
        except SlackApiError as exc:
            logger.error("Slack conversations_open failed user=%s: %s", user_id, exc)
            raise SlackClientError(f"Failed to open DM with {user_id}", api_error=exc) from exc

        conv_data = conv.data if isinstance(conv.data, dict) else {}
        channel_id = str(conv_data.get("channel", {}).get("id", user_id))

        await self._rate_limiter.acquire()
        try:
            resp = await self._circuit.call(
                self._client.chat_postMessage,
                channel=channel_id,
                text=message,
                mrkdwn=True,
            )
        except SlackApiError as exc:
            logger.error("Slack DM send failed user=%s: %s", user_id, exc)
            raise SlackClientError(f"Failed to send DM to {user_id}", api_error=exc) from exc
        return _parse_message_response(resp.data)

    # ------------------------------------------------------------------
    # Threaded replies
    # ------------------------------------------------------------------

    async def send_threaded_reply(
        self,
        channel_id: str,
        thread_id: str,
        message: str,
    ) -> SlackMessageResponse:
        """Reply in an existing Slack thread.

        Parameters
        ----------
        channel_id:
            The channel containing the thread.
        thread_id:
            The ``ts`` of the parent message.
        message:
            Reply text (mrkdwn supported).
        """
        await self._rate_limiter.acquire()
        try:
            resp = await self._circuit.call(
                self._client.chat_postMessage,
                channel=channel_id,
                thread_ts=thread_id,
                text=message,
                mrkdwn=True,
            )
        except SlackApiError as exc:
            logger.error(
                "Slack send_threaded_reply failed channel=%s thread=%s: %s",
                channel_id, thread_id, exc,
            )
            raise SlackClientError(
                f"Failed to reply in thread {thread_id}", api_error=exc
            ) from exc
        return _parse_message_response(resp.data)

    # ------------------------------------------------------------------
    # Status cards
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
    ) -> SlackMessageResponse:
        """Send a rich Block Kit status message to a Slack channel.

        Shows the current state of the agent's work on a Jira ticket.
        """
        blocks = _build_status_blocks(
            jira_key=jira_key,
            current_state=current_state,
            task_title=task_title,
            pr_url=pr_url,
            repo=repo,
            branch=branch,
            cost_usd=cost_usd,
            progress_pct=progress_pct,
        )
        await self._rate_limiter.acquire()
        try:
            resp = await self._circuit.call(
                self._client.chat_postMessage,
                channel=channel_id,
                text=f"🤖 Mason Status: {jira_key} — {current_state}",
                blocks=blocks,
            )
        except SlackApiError as exc:
            logger.error("Slack send_status_card failed channel=%s: %s", channel_id, exc)
            raise SlackClientError(
                f"Failed to send status card to {channel_id}", api_error=exc
            ) from exc
        return _parse_message_response(resp.data)

    # ------------------------------------------------------------------
    # Approval message update (replace buttons with result)
    # ------------------------------------------------------------------

    async def update_approval_message(
        self,
        channel_id: str,
        message_ts: str,
        title: str,
        approved: bool,
        responder: str = "",
    ) -> None:
        """Replace an approval message's buttons with the final result.

        Called after a user clicks Approve or Reject to prevent double-clicks.
        Best-effort — logs but does not raise on failure.
        """
        result_emoji = "✅" if approved else "❌"
        result_text = "Approved" if approved else "Rejected"
        by_text = f" by *{responder}*" if responder else ""

        blocks: list[dict[str, Any]] = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🤖 *Approval Required: {title}*",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{result_emoji} *{result_text}*{by_text}",
                },
            },
        ]

        await self._rate_limiter.acquire()
        try:
            await self._circuit.call(
                self._client.chat_update,
                channel=channel_id,
                ts=message_ts,
                text=f"{result_emoji} {result_text}{by_text}: {title}",
                blocks=blocks,
            )
        except (SlackApiError, Exception):
            logger.exception("Failed to update approval message ts=%s", message_ts)


# ---------------------------------------------------------------------------
# Block Kit builder helpers
# ---------------------------------------------------------------------------


def _parse_message_response(data: Any) -> SlackMessageResponse:
    if isinstance(data, dict):
        return SlackMessageResponse(
            ok=bool(data.get("ok", True)),
            ts=str(data.get("ts", "")),
            channel=str(data.get("channel", "")),
            message_text=str((data.get("message") or {}).get("text", "")),
        )
    return SlackMessageResponse()


def _build_approval_blocks(
    title: str,
    description: str,
    callback_id: str,
    extra_facts: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Build Slack Block Kit JSON for an approval request."""
    facts_text = f"*Request ID:* `{callback_id}`"
    if extra_facts:
        facts_text += "\n" + "\n".join(
            f"*{f['title']}:* {f['value']}" for f in extra_facts
        )

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🤖 Approval Required: {title}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": description},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": facts_text},
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Approve", "emoji": True},
                    "style": "primary",
                    "action_id": "approve_button",
                    "value": callback_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Reject", "emoji": True},
                    "style": "danger",
                    "action_id": "reject_button",
                    "value": callback_id,
                },
            ],
        },
    ]
    return blocks


def _build_status_blocks(
    *,
    jira_key: str,
    current_state: str,
    task_title: str = "",
    pr_url: str = "",
    repo: str = "",
    branch: str = "",
    cost_usd: float = 0.0,
    progress_pct: int = 0,
) -> list[dict[str, Any]]:
    """Build Slack Block Kit JSON for an agent status update."""
    state_emoji = {
        "implementing": "⚙️",
        "testing": "🧪",
        "awaiting_approval": "⏳",
        "pr_created": "📬",
        "reviewing": "👀",
        "done": "✅",
        "failed": "❌",
    }.get(current_state, "🔄")

    fields_text = f"*Jira:* {jira_key}\n*State:* {state_emoji} {current_state}"
    if task_title:
        fields_text += f"\n*Task:* {task_title}"
    if repo:
        fields_text += f"\n*Repo:* `{repo}`"
    if branch:
        fields_text += f"\n*Branch:* `{branch}`"
    if pr_url:
        fields_text += f"\n*PR:* <{pr_url}|View PR>"
    if cost_usd > 0:
        fields_text += f"\n*Cost:* ${cost_usd:.4f}"
    if progress_pct > 0:
        fields_text += f"\n*Progress:* {progress_pct}%"

    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🤖 Mason Status: {jira_key}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": fields_text},
        },
    ]
