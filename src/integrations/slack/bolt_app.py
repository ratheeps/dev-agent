"""Slack Bolt async app — event registration and FastAPI integration.

Creates an AsyncApp with:
- app_mention: routes @mentions to SlackConversationHandler
- message (im): routes DMs to SlackConversationHandler
- block_actions (approve_button / reject_button): routes to SlackApprovalAdapter

The app is mounted into FastAPI via AsyncSlackRequestHandler at /slack/events.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp

from src.integrations.slack.approval_adapter import SlackApprovalAdapter
from src.integrations.slack.conversation_handler import SlackConversationHandler
from src.integrations.slack.notification_client import SlackNotificationClient
from src.settings import get_settings

logger = logging.getLogger(__name__)

_UNKNOWN_REPLY = (
    "🤖 Sorry, something went wrong processing your message. "
    "Please try again or contact the team."
)


def create_bolt_app(
    *,
    slack_client: SlackNotificationClient,
    conversation_handler: SlackConversationHandler,
    approval_adapter: SlackApprovalAdapter,
) -> AsyncApp:
    """Create and configure the Slack Bolt async application.

    Parameters
    ----------
    slack_client:
        Shared SlackNotificationClient for outgoing messages.
    conversation_handler:
        Routes @mentions and DMs to active pipelines.
    approval_adapter:
        Handles button click interactions for approval flow.
    """
    settings = get_settings()
    app = AsyncApp(
        token=settings.slack_bot_token,
        signing_secret=settings.slack_signing_secret,
    )

    # ------------------------------------------------------------------
    # @mentions in channels
    # ------------------------------------------------------------------

    @app.event("app_mention")
    async def handle_app_mention(event: dict[str, Any], say: Any) -> None:
        """Handle @mason mentions in any channel."""
        await _safe_ack_and_handle(
            "app_mention",
            lambda: _process_mention(event, conversation_handler),
        )

    # ------------------------------------------------------------------
    # Direct messages to the bot
    # ------------------------------------------------------------------

    @app.event("message")
    async def handle_dm(event: dict[str, Any], say: Any) -> None:
        """Handle direct messages sent to the bot (im channel type)."""
        channel_type = str(event.get("channel_type", ""))
        if channel_type != "im":
            return
        if not event.get("user") or event.get("bot_id"):
            return

        await _safe_ack_and_handle(
            "dm",
            lambda: _process_dm(event, conversation_handler),
        )

    # ------------------------------------------------------------------
    # Approve button action
    # ------------------------------------------------------------------

    @app.action("approve_button")
    async def handle_approve(ack: Any, body: dict[str, Any]) -> None:
        """Handle Approve button click on an approval Block Kit message."""
        await ack()
        try:
            action = (body.get("actions") or [{}])[0]
            callback_id = str(action.get("value", ""))
            user = body.get("user", {})
            user_id = str(user.get("id", ""))
            user_name = str(user.get("name", ""))
            channel_id = str((body.get("channel") or {}).get("id", ""))
            message_ts = str((body.get("message") or {}).get("ts", ""))
            title = str((body.get("message") or {}).get("text", ""))

            logger.info(
                "Bolt: approve_button callback_id=%s user=%s",
                callback_id,
                user_name or user_id,
            )
            await approval_adapter.handle_approve(
                callback_id=callback_id,
                user_id=user_id,
                user_name=user_name,
                channel_id=channel_id,
                message_ts=message_ts,
                title=title,
            )
        except Exception:
            logger.exception("Bolt: error handling approve_button")

    # ------------------------------------------------------------------
    # Reject button action
    # ------------------------------------------------------------------

    @app.action("reject_button")
    async def handle_reject(ack: Any, body: dict[str, Any]) -> None:
        """Handle Reject button click on an approval Block Kit message."""
        await ack()
        try:
            action = (body.get("actions") or [{}])[0]
            callback_id = str(action.get("value", ""))
            user = body.get("user", {})
            user_id = str(user.get("id", ""))
            user_name = str(user.get("name", ""))
            channel_id = str((body.get("channel") or {}).get("id", ""))
            message_ts = str((body.get("message") or {}).get("ts", ""))
            title = str((body.get("message") or {}).get("text", ""))

            logger.info(
                "Bolt: reject_button callback_id=%s user=%s",
                callback_id,
                user_name or user_id,
            )
            await approval_adapter.handle_reject(
                callback_id=callback_id,
                user_id=user_id,
                user_name=user_name,
                channel_id=channel_id,
                message_ts=message_ts,
                title=title,
            )
        except Exception:
            logger.exception("Bolt: error handling reject_button")

    return app


def create_bolt_handler(app: AsyncApp) -> AsyncSlackRequestHandler:
    """Wrap the Bolt app in a FastAPI-compatible request handler."""
    return AsyncSlackRequestHandler(app)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

async def _safe_ack_and_handle(event_type: str, handler: Any) -> None:
    """Execute handler, logging any exception. Bolt handles ack automatically for events."""
    try:
        await handler()
    except Exception:
        logger.exception("Bolt: unhandled error in %s handler", event_type)


async def _process_mention(
    event: dict[str, Any],
    handler: SlackConversationHandler,
) -> None:
    user = str(event.get("user", ""))
    raw_text = str(event.get("text", ""))
    channel = str(event.get("channel", ""))
    ts = str(event.get("ts", ""))
    thread_ts = str(event.get("thread_ts", ""))

    clean_text = re.sub(r"<@[A-Z0-9]+>", "", raw_text).strip()
    logger.info("Bolt: app_mention user=%s channel=%s text=%r", user, channel, clean_text[:80])

    await handler.handle_mention(
        user=user,
        text=clean_text,
        channel=channel,
        thread_ts=thread_ts,
        ts=ts,
    )


async def _process_dm(
    event: dict[str, Any],
    handler: SlackConversationHandler,
) -> None:
    user = str(event.get("user", ""))
    text = str(event.get("text", ""))
    channel = str(event.get("channel", ""))
    logger.info("Bolt: DM user=%s channel=%s text=%r", user, channel, text[:80])

    await handler.handle_dm(user=user, text=text, channel=channel)
