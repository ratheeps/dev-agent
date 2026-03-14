"""Pydantic models for webhook payloads and responses."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


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
