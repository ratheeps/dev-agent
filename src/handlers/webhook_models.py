"""Pydantic models for Teams webhook payloads."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class TeamsCardActionPayload(BaseModel):
    """Payload Teams sends when a user clicks an Adaptive Card action button."""

    request_id: str = Field(..., alias="requestId", description="ApprovalRequest.id")
    approved: bool
    responder: str = Field(default="", description="Teams user who clicked the button")
    channel_id: str = Field(default="", alias="channelId")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"populate_by_name": True}


class TeamsMentionPayload(BaseModel):
    """Payload Teams sends when a message mentions the bot."""

    message_id: str = Field(default="", alias="messageId")
    text: str = Field(..., description="Full message text (including @mention prefix)")
    sender: str = Field(default="", description="Teams user display name or email")
    sender_id: str = Field(default="", alias="senderId")
    channel_id: str = Field(default="", alias="channelId")
    thread_id: str = Field(default="", alias="threadId", description="Conversation thread for replies")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def clean_text(self) -> str:
        """Remove @DevAI prefix from the message text."""
        import re
        return re.sub(r"@\w[\w\s]*?\b", "", self.text).strip()

    model_config = {"populate_by_name": True}


class ApprovalStatusResponse(BaseModel):
    """Response body for GET /approvals/{id}."""

    request_id: str
    status: str
    title: str = ""
    response_by: str = ""
    created_at: datetime | None = None
    resolved_at: datetime | None = None


class WebhookHealthResponse(BaseModel):
    """Response for GET /health."""

    status: str = "ok"
    pending_approvals: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
