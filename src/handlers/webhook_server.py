"""FastAPI webhook server for receiving Teams card actions and @mentions.

Endpoints
---------
POST /webhooks/teams/approval   Teams Adaptive Card Approve/Reject button click
POST /webhooks/teams/message    Teams @mention / incoming message
GET  /approvals/{id}            Query approval request status
GET  /health                    Health check
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncGenerator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from src.handlers.webhook_models import (
    ApprovalStatusResponse,
    TeamsCardActionPayload,
    TeamsMentionPayload,
    WebhookHealthResponse,
)

if TYPE_CHECKING:
    from src.integrations.teams.approval_flow import ApprovalFlow
    from src.integrations.teams.conversation_handler import AgentConversationHandler

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_webhook_app(
    *,
    approval_flow: "ApprovalFlow",
    conversation_handler: "AgentConversationHandler",
) -> FastAPI:
    """Create and configure the FastAPI webhook application.

    Parameters
    ----------
    approval_flow:
        Shared `ApprovalFlow` instance — the same one used by the pipeline.
    conversation_handler:
        `AgentConversationHandler` instance wired to active pipelines.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger.info("Webhook server starting — approval_flow ready")
        yield
        logger.info("Webhook server shutting down")

    app = FastAPI(
        title="Dev-AI Teams Webhook",
        description="Receives Teams card actions and @mentions for human-in-the-loop.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # POST /webhooks/teams/approval
    # ------------------------------------------------------------------

    @app.post("/webhooks/teams/approval", status_code=status.HTTP_200_OK)
    async def teams_approval(payload: TeamsCardActionPayload) -> dict[str, Any]:
        """Receive an Approve/Reject card action from Teams.

        Called by Teams when a user clicks an Approve or Reject button
        on an Adaptive Card sent by the agent.
        """
        logger.info(
            "Webhook: approval action request_id=%s approved=%s responder=%s",
            payload.request_id,
            payload.approved,
            payload.responder,
        )

        request = approval_flow.get_request(payload.request_id)
        if request is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Approval request '{payload.request_id}' not found or already resolved.",
            )

        approval_flow.resolve(
            payload.request_id,
            approved=payload.approved,
            responder=payload.responder,
        )

        action = "approved" if payload.approved else "rejected"
        return {
            "status": "ok",
            "request_id": payload.request_id,
            "action": action,
            "responder": payload.responder,
        }

    # ------------------------------------------------------------------
    # POST /webhooks/teams/message
    # ------------------------------------------------------------------

    @app.post("/webhooks/teams/message", status_code=status.HTTP_200_OK)
    async def teams_message(payload: TeamsMentionPayload) -> dict[str, Any]:
        """Receive an @mention or message from Teams.

        Dispatches to `AgentConversationHandler` which detects intent
        and routes to the active pipeline.
        """
        logger.info(
            "Webhook: @mention from %s channel=%s text=%r",
            payload.sender,
            payload.channel_id,
            payload.text[:80],
        )

        reply = await conversation_handler.handle_mention(payload)
        return {"status": "ok", "reply": reply}

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
