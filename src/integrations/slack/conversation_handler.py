"""Handles incoming Slack @mentions and dispatches intents to the agent pipeline.

Reuses the platform-agnostic IntentType and detect_intent from
src.integrations.notifications.intent.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.integrations.notifications.intent import IntentType, detect_intent, extract_jira_key
from src.integrations.slack.notification_client import SlackNotificationClient
from src.settings import get_settings

logger = logging.getLogger(__name__)


class SlackConversationHandler:
    """Handles incoming Slack @mentions and routes them to the running pipeline.

    Parameters
    ----------
    slack_client:
        For sending replies.
    approval_flow:
        For resolving pending approval requests via APPROVE/REJECT intents.
    pipeline_registry:
        Dict mapping jira_key → WorkflowPipeline. Used to inject feedback.
    """

    def __init__(
        self,
        *,
        slack_client: SlackNotificationClient,
        approval_flow: Any,
        pipeline_registry: dict[str, Any] | None = None,
    ) -> None:
        self._slack = slack_client
        self._approval_flow = approval_flow
        self._pipelines: dict[str, Any] = pipeline_registry or {}

    def register_pipeline(self, jira_key: str, pipeline: Any) -> None:
        """Register an active pipeline so feedback can be injected into it."""
        self._pipelines[jira_key] = pipeline
        logger.info("SlackConversationHandler: registered pipeline for %s", jira_key)

    def unregister_pipeline(self, jira_key: str) -> None:
        self._pipelines.pop(jira_key, None)

    async def handle_mention(
        self,
        user: str,
        text: str,
        channel: str,
        thread_ts: str = "",
        ts: str = "",
    ) -> str:
        """Process a Slack @mention and return the reply text.

        Detects intent, dispatches accordingly, and posts a threaded reply.

        Parameters
        ----------
        user:
            Slack user ID of the sender.
        text:
            Clean message text (already stripped of <@BOTID>).
        channel:
            Channel ID where the mention occurred.
        thread_ts:
            Parent thread ts if already in a thread.
        ts:
            Message ts (used as thread_ts for replies if not already in thread).
        """
        intent = detect_intent(text)

        logger.info(
            "SlackConversationHandler: @mention from %s — intent=%s text=%r",
            user,
            intent.value,
            text[:80],
        )

        reply = await self._dispatch(intent, text, user, channel)

        # Reply in thread to keep conversations organised
        reply_thread = thread_ts if thread_ts else ts
        if reply_thread:
            await self._slack.send_threaded_reply(
                channel_id=channel,
                thread_id=reply_thread,
                message=reply,
            )
        else:
            await self._slack.send_message(
                channel_id=channel or get_settings().slack_notification_channel,
                message=reply,
            )

        return reply

    async def handle_dm(
        self,
        user: str,
        text: str,
        channel: str,
    ) -> str:
        """Process a direct message to the bot (non-mention DM).

        Uses the same intent dispatch as @mentions, replies in the same DM channel.
        """
        intent = detect_intent(text)

        logger.info(
            "SlackConversationHandler: DM from %s — intent=%s text=%r",
            user,
            intent.value,
            text[:80],
        )

        reply = await self._dispatch(intent, text, user, channel)
        await self._slack.send_message(channel_id=channel, message=reply)
        return reply

    async def _dispatch(
        self,
        intent: IntentType,
        text: str,
        user: str,
        channel: str,
    ) -> str:
        """Route intent to the appropriate handler. Returns reply string."""
        match intent:
            case IntentType.STATUS_QUERY:
                return self._handle_status()

            case IntentType.APPROVE:
                return self._handle_approve(user)

            case IntentType.REJECT:
                return self._handle_reject(user, text)

            case IntentType.RETRY:
                return self._handle_retry(text, user)

            case IntentType.STOP:
                return self._handle_stop(text, user)

            case IntentType.EXPLAIN:
                return self._handle_explain()

            case IntentType.DEBUG_HELP | IntentType.CLARIFY:
                return self._handle_feedback(text, user)

            case _:
                return (
                    "👋 Hi! I'm Mason. I didn't quite understand that.\n"
                    "You can say: *status*, *approve*, *reject*, *retry*, *stop*, "
                    "or give me feedback like 'use X approach instead'.\n"
                    "You can also mention a Jira key like `GIFT-1234` to target a specific task."
                )

    def _handle_status(self) -> str:
        if not self._pipelines:
            return "🤖 *Mason*: No active tasks right now."
        lines = ["🤖 *Mason Status Report*\n"]
        for jira_key, pipeline in self._pipelines.items():
            state = getattr(getattr(pipeline, "_context", None), "current_state", "unknown")
            pr_url = getattr(getattr(pipeline, "_context", None), "pr_url", "")
            line = f"• *{jira_key}* — `{state}`"
            if pr_url:
                line += f" — <{pr_url}|View PR>"
            lines.append(line)
        return "\n".join(lines)

    def _handle_approve(self, user: str) -> str:
        pending_count = self._approval_flow.pending_count
        if pending_count == 0:
            return "✅ No pending approval requests. Nothing to approve."

        for request_id in list(self._approval_flow._pending.keys()):  # noqa: SLF001
            self._approval_flow.resolve(request_id, approved=True, responder=user)
            break

        return f"✅ Approved by <@{user}>. Agent is resuming."

    def _handle_reject(self, user: str, text: str) -> str:
        pending_count = self._approval_flow.pending_count
        if pending_count == 0:
            return "❌ No pending approval requests. Nothing to reject."

        for request_id in list(self._approval_flow._pending.keys()):  # noqa: SLF001
            self._approval_flow.resolve(request_id, approved=False, responder=user)
            break

        reason = re.sub(r"\breject\b", "", text, flags=re.IGNORECASE).strip(" .,")
        return (
            f"❌ Rejected by <@{user}>. "
            + (f"Reason: _{reason}_ " if reason else "")
            + "Agent will re-plan."
        )

    def _handle_retry(self, text: str, user: str) -> str:
        jira_key = extract_jira_key(text)
        pipeline = (
            self._pipelines.get(jira_key)
            if jira_key
            else next(iter(self._pipelines.values()), None)
        )
        if pipeline is None:
            return "🔄 No active pipeline to retry."
        if hasattr(pipeline, "inject_feedback"):
            pipeline.inject_feedback(f"RETRY requested by {user}: {text}")
        return f"🔄 Retry queued for *{jira_key or 'current task'}*."

    def _handle_stop(self, text: str, user: str) -> str:
        jira_key = extract_jira_key(text)
        pipeline = (
            self._pipelines.get(jira_key)
            if jira_key
            else next(iter(self._pipelines.values()), None)
        )
        if pipeline and hasattr(pipeline, "inject_feedback"):
            pipeline.inject_feedback(f"STOP requested by {user}. Pause current work.")
        return f"⏸️ Stop signal sent to *{jira_key or 'current task'}*."

    def _handle_explain(self) -> str:
        if not self._pipelines:
            return "🤖 No active task. Nothing to explain."
        jira_key = next(iter(self._pipelines.keys()))
        return (
            f"🤖 I'm working on *{jira_key}*. "
            "For detailed reasoning, check the Jira ticket comments — "
            "I post my decision rationale there as I work."
        )

    def _handle_feedback(self, text: str, user: str) -> str:
        """Inject developer feedback into the active pipeline."""
        jira_key = extract_jira_key(text)
        pipeline = (
            self._pipelines.get(jira_key)
            if jira_key
            else next(iter(self._pipelines.values()), None)
        )

        if pipeline is None:
            return "🤖 No active task. Start a pipeline first with a Jira ticket."

        if hasattr(pipeline, "inject_feedback"):
            pipeline.inject_feedback(f"Developer feedback from {user}: {text}")
            active_key = jira_key or next(iter(self._pipelines.keys()))
            return (
                f"🤖 Got it, <@{user}>! Feedback injected into *{active_key}*.\n"
                f"> _{text}_\n\n"
                "I'll take this into account for my next action."
            )

        return "🤖 Feedback received but no active pipeline to inject into."
