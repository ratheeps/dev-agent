"""Pydantic models for Microsoft Teams data structures."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TeamsMessageResponse(BaseModel):
    """Response after sending a Teams message."""

    id: str = ""
    created_date_time: datetime | None = Field(None, alias="createdDateTime")
    web_url: str = Field("", alias="webUrl")

    model_config = {"populate_by_name": True}


class TeamsApprovalRequest(BaseModel):
    """Payload for an approval request sent via Teams."""

    channel_id: str
    title: str
    description: str
    callback_id: str


class TeamsApprovalResponse(BaseModel):
    """Response after sending an approval card to Teams."""

    message_id: str = ""
    callback_id: str = ""
    status: str = "pending"
