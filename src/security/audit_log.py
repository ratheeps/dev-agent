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
