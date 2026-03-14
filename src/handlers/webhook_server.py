"""FastAPI webhook server — Slack events, approvals, and health.

Endpoints
---------
POST /slack/events          All Slack events (mentions, DMs, button actions)
                            handled by Slack Bolt via AsyncSlackRequestHandler.
GET  /approvals/{id}        Query approval request status
GET  /health                Health check
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncGenerator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from src.handlers.webhook_models import (
    ApprovalStatusResponse,
    WebhookHealthResponse,
)

if TYPE_CHECKING:
    from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler

    from src.integrations.notifications.approval_flow import ApprovalFlow

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_webhook_app(
    *,
    approval_flow: "ApprovalFlow",
    bolt_handler: "AsyncSlackRequestHandler",
) -> FastAPI:
    """Create and configure the FastAPI webhook application.

    Parameters
    ----------
    approval_flow:
        Shared ``ApprovalFlow`` instance — the same one used by the pipeline.
    bolt_handler:
        ``AsyncSlackRequestHandler`` wrapping the configured Slack Bolt app.
        All Slack events (mentions, DMs, button clicks) are routed through this.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger.info("Webhook server starting — Slack Bolt handler ready")
        yield
        logger.info("Webhook server shutting down")

    app = FastAPI(
        title="Mason Slack Webhook",
        description="Receives Slack events and @mentions for human-in-the-loop.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # POST /slack/events  — Slack Bolt handles everything:
    #   • app_mention  → SlackConversationHandler
    #   • message (im) → SlackConversationHandler
    #   • block_actions (approve_button/reject_button) → SlackApprovalAdapter
    # ------------------------------------------------------------------

    @app.post("/slack/events")
    async def slack_events(req: Request) -> Any:
        """Receive all Slack events via the Bolt request handler.

        Slack sends all event types (mentions, DMs, button interactions)
        to this single endpoint. Bolt dispatches internally.
        """
        return await bolt_handler.handle(req)

    # ------------------------------------------------------------------
    # GET /approvals/{request_id}
    # ------------------------------------------------------------------

    @app.get("/approvals/{request_id}", response_model=ApprovalStatusResponse)
    async def get_approval_status(request_id: str) -> ApprovalStatusResponse:
        """Query the status of a pending or resolved approval request."""
        request = approval_flow.get_request(request_id)
        if request is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Approval request '{request_id}' not found.",
            )
        return ApprovalStatusResponse(
            request_id=request.id,
            status=request.status.value,
            title=request.title,
            response_by=request.response_by,
            created_at=request.created_at,
            resolved_at=request.resolved_at,
        )

    # ------------------------------------------------------------------
    # GET /health
    # ------------------------------------------------------------------

    @app.get("/health", response_model=WebhookHealthResponse)
    async def health() -> WebhookHealthResponse:
        return WebhookHealthResponse(pending_approvals=approval_flow.pending_count)

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Webhook unhandled error: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    return app
