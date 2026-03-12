"""Handles incoming Teams @mentions and dispatches intents to the agent pipeline."""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.integrations.teams.approval_flow import ApprovalFlow, ApprovalStatus
from src.integrations.teams.notification_client import TeamsNotificationClient

if TYPE_CHECKING:
    from src.handlers.webhook_models import TeamsMentionPayload

logger = logging.getLogger(__name__)


class IntentType(str, Enum):
    """Intents the agent can recognise from developer @mentions."""

    STATUS_QUERY = "status_query"
    DEBUG_HELP = "debug_help"
    RETRY = "retry"
    CLARIFY = "clarify"
    APPROVE = "approve"
    REJECT = "reject"
    EXPLAIN = "explain"
    STOP = "stop"
    UNKNOWN = "unknown"


# Pattern-based intent detection — keyword matching without LLM call overhead
_INTENT_PATTERNS: list[tuple[IntentType, list[str]]] = [
    (IntentType.STATUS_QUERY, ["status", "what are you", "what's happening", "progress", "where are you"]),
    (IntentType.APPROVE, ["approve", "approved", "go ahead", "lgtm", "ship it", "looks good"]),
    (IntentType.REJECT, ["reject", "rejected", "stop this", "don't proceed", "wrong approach", "change this"]),
    (IntentType.RETRY, ["retry", "try again", "re-run", "rerun", "run again"]),
    (IntentType.STOP, ["stop", "pause", "halt", "wait", "hold on"]),
    (IntentType.EXPLAIN, ["why", "explain", "how did you", "reason", "rationale"]),
    (IntentType.DEBUG_HELP, ["failing", "broken", "error", "fix", "debug", "not working", "issue"]),
    (IntentType.CLARIFY, ["use ", "instead", "should be", "prefer", "change to", "update approach"]),
]


def detect_intent(text: str) -> IntentType:
    """Classify developer @mention text into an IntentType.

    Uses keyword pattern matching. Returns CLARIFY for any instruction-like
    message that doesn't match specific patterns (most developer guidance).
    """
    clean = text.lower().strip()

    for intent, keywords in _INTENT_PATTERNS:
        if any(kw in clean for kw in keywords):
            return intent

    # If the message is phrased as an imperative or instruction, treat as CLARIFY
    if len(clean.split()) >= 3:
        return IntentType.CLARIFY

    return IntentType.UNKNOWN


class AgentConversationHandler:
    """Handles incoming Teams @mentions and routes them to the running pipeline.

    Parameters
    ----------
    teams_client:
        For sending replies.
    approval_flow:
        For resolving pending approval requests via APPROVE/REJECT intents.
    pipeline_registry:
        Dict mapping jira_key → WorkflowPipeline. Used to inject feedback.
    """

    def __init__(
        self,
        *,
        teams_client: TeamsNotificationClient,
        approval_flow: ApprovalFlow,
        pipeline_registry: dict[str, Any] | None = None,
    ) -> None:
        self._teams = teams_client
        self._approval_flow = approval_flow
        self._pipelines: dict[str, Any] = pipeline_registry or {}

    def register_pipeline(self, jira_key: str, pipeline: Any) -> None:
        """Register an active pipeline so feedback can be injected into it."""
        self._pipelines[jira_key] = pipeline
        logger.info("ConversationHandler: registered pipeline for %s", jira_key)

    def unregister_pipeline(self, jira_key: str) -> None:
        self._pipelines.pop(jira_key, None)

    async def handle_mention(self, payload: "TeamsMentionPayload") -> str:
        """Process an @mention and return the reply text.

        Detects intent, dispatches accordingly, and sends a threaded reply.
        """
        text = payload.clean_text
        intent = detect_intent(text)

        logger.info(
            "ConversationHandler: @mention from %s — intent=%s text=%r",
            payload.sender,
            intent.value,
            text[:80],
        )

        reply = await self._dispatch(intent, text, payload)

        # Send reply in the same thread if thread_id is available
        if payload.thread_id:
            await self._teams.send_threaded_reply(
                channel_id=payload.channel_id,
                thread_id=payload.thread_id,
                message=reply,
            )
        else:
            await self._teams.send_message(
                channel_id=payload.channel_id or "dev-ai-notifications",
                message=reply,
            )

        return reply

    async def _dispatch(
        self, intent: IntentType, text: str, payload: "TeamsMentionPayload"
    ) -> str:
        """Route intent to the appropriate handler. Returns reply string."""
        match intent:
            case IntentType.STATUS_QUERY:
                return self._handle_status()

            case IntentType.APPROVE:
                return self._handle_approve(payload.sender)

            case IntentType.REJECT:
                return self._handle_reject(payload.sender, text)

            case IntentType.RETRY:
                return await self._handle_retry(text, payload)

            case IntentType.STOP:
                return self._handle_stop(text, payload)

            case IntentType.EXPLAIN:
                return self._handle_explain()

            case IntentType.DEBUG_HELP | IntentType.CLARIFY:
                return await self._handle_feedback(text, payload)

            case _:
                return (
                    "👋 Hi! I'm Dev-AI. I didn't quite understand that. "
                    "You can say: **status**, **approve**, **reject**, **retry**, "
                    "**stop**, or give me feedback like 'use X approach instead'."
                )

    def _handle_status(self) -> str:
        if not self._pipelines:
            return "🤖 **Dev-AI**: No active tasks right now."
        lines = ["🤖 **Dev-AI Status Report**\n"]
        for jira_key, pipeline in self._pipelines.items():
            state = getattr(getattr(pipeline, "_context", None), "current_state", "unknown")
            pr_url = getattr(getattr(pipeline, "_context", None), "pr_url", "")
            line = f"• **{jira_key}** — `{state}`"
            if pr_url:
                line += f" — [PR]({pr_url})"
            lines.append(line)
        return "\n".join(lines)

    def _handle_approve(self, responder: str) -> str:
        pending_count = self._approval_flow.pending_count
        if pending_count == 0:
            return "✅ No pending approval requests. Nothing to approve."

        # Resolve the first pending approval (most common case — one at a time)
        # In production, the responder would reference a specific request ID
        resolved = 0
        for request_id in list(self._approval_flow._pending.keys()):  # noqa: SLF001
            self._approval_flow.resolve(request_id, approved=True, responder=responder)
            resolved += 1
            break  # Resolve one at a time

        return f"✅ Approved by **{responder or 'you'}**. Agent is resuming."

    def _handle_reject(self, responder: str, text: str) -> str:
        pending_count = self._approval_flow.pending_count
        if pending_count == 0:
            return "❌ No pending approval requests. Nothing to reject."

        for request_id in list(self._approval_flow._pending.keys()):  # noqa: SLF001
            self._approval_flow.resolve(request_id, approved=False, responder=responder)
            break

        reason = re.sub(r"\breject\b", "", text, flags=re.IGNORECASE).strip(" .,")
        return f"❌ Rejected by **{responder or 'you'}**. {('Reason: ' + reason) if reason else 'Agent will re-plan.'}"

    async def _handle_retry(self, text: str, payload: "TeamsMentionPayload") -> str:
        jira_key = _extract_jira_key(text)
        pipeline = self._pipelines.get(jira_key) if jira_key else next(iter(self._pipelines.values()), None)
        if pipeline is None:
            return "🔄 No active pipeline to retry."
        if hasattr(pipeline, "inject_feedback"):
            pipeline.inject_feedback(f"RETRY requested by {payload.sender}: {text}")
        return f"🔄 Retry queued for **{jira_key or 'current task'}**."

    def _handle_stop(self, text: str, payload: "TeamsMentionPayload") -> str:
        jira_key = _extract_jira_key(text)
        pipeline = self._pipelines.get(jira_key) if jira_key else next(iter(self._pipelines.values()), None)
        if pipeline and hasattr(pipeline, "inject_feedback"):
            pipeline.inject_feedback(f"STOP requested by {payload.sender}. Pause current work.")
        return f"⏸️ Stop signal sent to **{jira_key or 'current task'}**."

    def _handle_explain(self) -> str:
        if not self._pipelines:
            return "🤖 No active task. Nothing to explain."
        pipeline = next(iter(self._pipelines.values()))
        jira_key = next(iter(self._pipelines.keys()))
        return (
            f"🤖 I'm working on **{jira_key}**. "
            "For detailed reasoning, check the Jira ticket comments — "
            "I post my decision rationale there as I work."
        )

    async def _handle_feedback(self, text: str, payload: "TeamsMentionPayload") -> str:
        """Inject developer feedback into the active pipeline."""
        jira_key = _extract_jira_key(text)
        pipeline = self._pipelines.get(jira_key) if jira_key else next(iter(self._pipelines.values()), None)

        if pipeline is None:
            return "🤖 No active task. Start a pipeline first with a Jira ticket."

        if hasattr(pipeline, "inject_feedback"):
            pipeline.inject_feedback(f"Developer feedback from {payload.sender}: {text}")
            active_key = jira_key or next(iter(self._pipelines.keys()))
            return (
                f"🤖 Got it, **{payload.sender}**! Feedback injected into **{active_key}**.\n"
                f"> _{text}_\n\n"
                "I'll take this into account for my next action."
            )

        return "🤖 Feedback received but no active pipeline to inject into."


def _extract_jira_key(text: str) -> str | None:
    """Extract a Jira key (e.g. GIFT-1234) from text, or None."""
    match = re.search(r"\b([A-Z]{2,10}-\d+)\b", text)
    return match.group(1) if match else None
