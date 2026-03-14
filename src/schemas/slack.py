"""Pydantic models for Slack data structures."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class SlackMessageResponse(BaseModel):
    """Response after sending a Slack message."""

    ok: bool = True
    ts: str = ""
    channel: str = ""
    message_text: str = ""


class SlackApprovalRequest(BaseModel):
    """Payload for an approval request sent via Slack."""

    channel_id: str
    title: str
    description: str
    callback_id: str


class SlackApprovalResponse(BaseModel):
    """Response after sending an approval Block Kit message to Slack."""

    ok: bool = True
    ts: str = ""
    channel: str = ""
    callback_id: str = ""
    status: str = "pending"


class SlackMentionEvent(BaseModel):
    """Slack app_mention event payload (from Bolt event handler)."""

    user: str = Field(default="", description="Slack user ID who mentioned the bot")
    text: str = Field(..., description="Full message text including @mention")
    channel: str = Field(default="", description="Channel ID")
    ts: str = Field(default="", description="Message timestamp (also used as thread reply target)")
    thread_ts: str = Field(default="", description="Thread timestamp if message is in a thread")
    event_ts: str = Field(default="", description="Event timestamp")

    @property
    def clean_text(self) -> str:
        """Remove <@BOTID> mention prefix from the message text."""
        import re
        return re.sub(r"<@[A-Z0-9]+>", "", self.text).strip()

    @property
    def thread_id(self) -> str:
        """Return thread_ts if in a thread, else ts (starts new thread)."""
        return self.thread_ts if self.thread_ts else self.ts


class SlackInteractionPayload(BaseModel):
    """Slack block_actions interaction payload (button click)."""

    type: str = "block_actions"
    trigger_id: str = ""
    user_id: str = ""
    user_name: str = ""
    channel_id: str = ""
    message_ts: str = ""
    action_id: str = ""
    action_value: str = ""
    callback_id: str = ""

    model_config = {"populate_by_name": True}


class SlackDMPayload(BaseModel):
    """Slack direct message event payload."""

    user: str = Field(default="", description="Slack user ID")
    text: str = Field(..., description="DM message text")
    channel: str = Field(default="", description="DM channel ID")
    ts: str = Field(default="")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
