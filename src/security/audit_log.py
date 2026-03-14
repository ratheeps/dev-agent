"""Audit logging for agent actions and MCP tool invocations.

Records all significant actions to a structured log for compliance
and debugging purposes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("devai.audit")


class AuditEntry(BaseModel):
    """A single audit log entry."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str
    agent_id: str = ""
    action: str = ""
    target: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    error: str = ""


def log_action(
    *,
    event_type: str,
    agent_id: str = "",
    action: str = "",
    target: str = "",
    details: dict[str, Any] | None = None,
    success: bool = True,
    error: str = "",
) -> AuditEntry:
    """Record an audit event and return the entry."""
    entry = AuditEntry(
        event_type=event_type,
        agent_id=agent_id,
        action=action,
        target=target,
        details=details or {},
        success=success,
        error=error,
    )

    log_line = entry.model_dump_json()
    if success:
        logger.info(log_line)
    else:
        logger.warning(log_line)

    return entry


def log_mcp_call(
    *,
    agent_id: str,
    server: str,
    tool: str,
    args: dict[str, Any] | None = None,
    success: bool = True,
    error: str = "",
) -> AuditEntry:
    """Convenience wrapper for MCP tool call audit entries."""
    return log_action(
        event_type="mcp_tool_call",
        agent_id=agent_id,
        action=tool,
        target=server,
        details={"args": args or {}},
        success=success,
        error=error,
    )


def log_state_transition(
    *,
    workflow_id: str,
    from_state: str,
    to_state: str,
    condition: str = "",
) -> AuditEntry:
    """Convenience wrapper for workflow state transition audit entries."""
    return log_action(
        event_type="state_transition",
        action=f"{from_state} -> {to_state}",
        target=workflow_id,
        details={"condition": condition},
    )


def log_slack_event(
    *,
    event_type: str,
    user_id: str = "",
    channel_id: str = "",
    text_preview: str = "",
    success: bool = True,
    error: str = "",
) -> AuditEntry:
    """Audit an incoming Slack event (mention, DM, or approval callback).

    Parameters
    ----------
    event_type:
        One of: ``app_mention``, ``dm``, ``approval_approved``,
        ``approval_rejected``, ``signature_invalid``.
    user_id:
        Slack user ID of the sender / approver.
    channel_id:
        Slack channel or DM channel ID.
    text_preview:
        First 100 chars of the message text (for debugging, not PII logging).
    success:
        False when e.g. signature verification fails.
    error:
        Error description when success=False.
    """
    return log_action(
        event_type=f"slack.{event_type}",
        agent_id="webhook",
        action=event_type,
        target=channel_id,
        details={
            "user_id": user_id,
            "text_preview": text_preview[:100],
        },
        success=success,
        error=error,
    )
