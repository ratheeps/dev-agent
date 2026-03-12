"""Async webhook handler for Jira webhook events.

Designed to be mounted on an API Gateway or any async HTTP framework.
Validates the webhook payload, extracts the ticket key, and spawns
the workflow pipeline.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from src.agents.communication import MessageBus
from src.agents.orchestrator import Orchestrator
from src.agents.registry import AgentRegistry
from src.integrations.mcp_manager import MCPManager
from src.memory.client import MemoryClient
from src.workflows.pipeline import WorkflowPipeline

logger = logging.getLogger(__name__)


class WebhookEvent(BaseModel):
    """Parsed Jira webhook event."""

    event_type: str = Field(..., description="e.g. jira:issue_created, jira:issue_updated")
    issue_key: str = Field(..., description="e.g. GIFT-1234")
    issue_id: str = ""
    project_key: str = ""
    summary: str = ""
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class WebhookResponse(BaseModel):
    """Response returned to the webhook caller."""

    status: int = 202
    message: str = "Accepted"
    workflow_id: str = ""


# Supported Jira event types that trigger the pipeline
TRIGGER_EVENTS = frozenset({
    "jira:issue_created",
    "jira:issue_updated",
})


def parse_jira_webhook(payload: dict[str, Any]) -> WebhookEvent:
    """Extract a WebhookEvent from a raw Jira webhook payload."""
    event_type = payload.get("webhookEvent", payload.get("event_type", ""))
    issue = payload.get("issue", {})
    fields = issue.get("fields", {})

    return WebhookEvent(
        event_type=event_type,
        issue_key=issue.get("key", ""),
        issue_id=str(issue.get("id", "")),
        project_key=fields.get("project", {}).get("key", ""),
        summary=fields.get("summary", ""),
        raw_payload=payload,
    )


def validate_webhook_signature(
    body: bytes,
    signature: str,
    secret: str,
) -> bool:
    """Validate a Jira webhook signature using HMAC-SHA256."""
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        "sha256",
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


async def handle_webhook(
    body: bytes,
    headers: dict[str, str],
    *,
    webhook_secret: str = "",
    mcp_call: Any = None,
) -> WebhookResponse:
    """Process a Jira webhook request.

    Parameters
    ----------
    body:
        Raw request body bytes.
    headers:
        HTTP headers (case-insensitive keys expected).
    webhook_secret:
        Shared secret for signature validation. Empty = skip validation.
    mcp_call:
        MCP tool invocation callable for the pipeline.

    Returns
    -------
    WebhookResponse with status 202 if accepted, 400/401 on error.
    """
    # Validate signature if secret is configured
    if webhook_secret:
        signature = headers.get("x-hub-signature-256", headers.get("X-Hub-Signature-256", ""))
        if not validate_webhook_signature(body, signature, webhook_secret):
            logger.warning("Webhook signature validation failed")
            return WebhookResponse(status=401, message="Invalid signature")

    # Parse payload
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Invalid webhook payload: %s", exc)
        return WebhookResponse(status=400, message=f"Invalid JSON: {exc}")

    event = parse_jira_webhook(payload)

    if not event.issue_key:
        return WebhookResponse(status=400, message="Missing issue key in payload")

    if event.event_type not in TRIGGER_EVENTS:
        logger.info("Ignoring non-trigger event: %s", event.event_type)
        return WebhookResponse(status=200, message=f"Ignored event: {event.event_type}")

    logger.info(
        "Webhook received: %s — %s (%s)",
        event.event_type,
        event.issue_key,
        event.summary,
    )

    # Spawn pipeline in background
    async def _run_pipeline() -> None:
        try:
            async def _noop_mcp(tool: str, args: dict[str, Any]) -> Any:
                return {"_stub": True}

            mgr = MCPManager.create(mcp_call=mcp_call or _noop_mcp)
            memory = MemoryClient()
            bus = MessageBus()
            registry = AgentRegistry(message_bus=bus)
            orchestrator = Orchestrator(registry=registry, message_bus=bus)

            pipeline = WorkflowPipeline(
                jira_key=event.issue_key,
                orchestrator=orchestrator,
                mcp_manager=mgr,
                memory_client=memory,
            )
            await pipeline.run()
        except Exception:
            logger.exception("Pipeline failed for %s", event.issue_key)
        finally:
            MCPManager.reset()

    task = asyncio.create_task(_run_pipeline())

    return WebhookResponse(
        status=202,
        message=f"Pipeline started for {event.issue_key}",
        workflow_id=event.issue_key,
    )
