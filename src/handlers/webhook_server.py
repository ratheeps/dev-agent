"""FastAPI webhook server — Slack events, approvals, and health.

Endpoints
---------
POST /slack/events          All Slack events (mentions, DMs, button actions)
                            handled by Slack Bolt via AsyncSlackRequestHandler.
GET  /approvals/{id}        Query approval request status
GET  /health                Health check

Production entrypoint
---------------------
``app_factory()`` is the zero-argument factory consumed by uvicorn's
``--factory`` flag. It wires all Slack dependencies and returns the ASGI app.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

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
# Production factory (zero-arg — consumed by uvicorn --factory)
# ---------------------------------------------------------------------------


def app_factory() -> FastAPI:
    """Create the fully-wired production FastAPI application.

    Called by uvicorn as a factory (no arguments). Reads configuration from
    environment variables via ``MasonSettings``.

    Raises ``RuntimeError`` if required Slack credentials are missing so the
    container fails fast at startup rather than crashing on the first request.
    """
    from src.integrations.notifications.approval_flow import ApprovalFlow
    from src.integrations.slack.approval_adapter import SlackApprovalAdapter
    from src.integrations.slack.bolt_app import create_bolt_app, create_bolt_handler
    from src.integrations.slack.conversation_handler import SlackConversationHandler
    from src.integrations.slack.notification_client import SlackNotificationClient
    from src.settings import get_settings

    settings = get_settings()

    if not settings.slack_bot_token:
        raise RuntimeError(
            "MASON_SLACK_BOT_TOKEN is not set. "
            "Set it in .env or as an environment variable before starting."
        )
    if not settings.slack_signing_secret:
        raise RuntimeError(
            "MASON_SLACK_SIGNING_SECRET is not set. "
            "Set it in .env or as an environment variable before starting."
        )

    slack_client = SlackNotificationClient(bot_token=settings.slack_bot_token)
    approval_flow = ApprovalFlow(notification_client=slack_client)
    conversation_handler = SlackConversationHandler(
        slack_client=slack_client,
        approval_flow=approval_flow,
    )
    approval_adapter = SlackApprovalAdapter(
        slack_client=slack_client,
        approval_flow=approval_flow,
    )
    bolt_app = create_bolt_app(
        slack_client=slack_client,
        conversation_handler=conversation_handler,
        approval_adapter=approval_adapter,
    )
    bolt_handler = create_bolt_handler(bolt_app)

    return create_webhook_app(
        approval_flow=approval_flow,
        bolt_handler=bolt_handler,
    )


# ---------------------------------------------------------------------------
# App factory (parameterized — used in tests and programmatic construction)
# ---------------------------------------------------------------------------


def create_webhook_app(
    *,
    approval_flow: ApprovalFlow,
    bolt_handler: AsyncSlackRequestHandler,
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

