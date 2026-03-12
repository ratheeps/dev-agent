"""Inter-agent message protocol models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class MessageType(str, enum.Enum):
    """Types of messages exchanged between agents."""

    TASK_ASSIGNMENT = "task_assignment"
    STATUS_UPDATE = "status_update"
    RESULT = "result"
    ERROR = "error"
    ESCALATION = "escalation"
    CONTEXT_REQUEST = "context_request"
    CONTEXT_RESPONSE = "context_response"


class AgentMessage(BaseModel):
    """A single message sent between agents over the message bus."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    from_agent: str = Field(..., description="Sender agent ID")
    to_agent: str = Field(
        ...,
        description="Recipient agent ID, or '*' for broadcast",
    )
    message_type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_broadcast(self) -> bool:
        return self.to_agent == "*"

    @property
    def is_error(self) -> bool:
        return self.message_type in {MessageType.ERROR, MessageType.ESCALATION}
