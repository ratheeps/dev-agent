"""Tests for the FastAPI webhook server (Slack-based)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from src.handlers.webhook_server import create_webhook_app
from src.integrations.notifications.approval_flow import ApprovalFlow, ApprovalRequest


def _make_app() -> tuple[TestClient, ApprovalFlow]:
    """Build a TestClient with mock Slack Bolt handler and ApprovalFlow."""
    slack_mock = AsyncMock()
    slack_mock.send_approval_request = AsyncMock(
        return_value=MagicMock(ts="ts1", callback_id="cb1", status="pending")
    )

    approval_flow = ApprovalFlow(notification_client=slack_mock)

    # Mock Bolt handler — just returns 200 OK for any Slack event
    bolt_handler = AsyncMock()
    bolt_handler.handle = AsyncMock(return_value=MagicMock(status_code=200, body=""))

    app = create_webhook_app(
        approval_flow=approval_flow,
        bolt_handler=bolt_handler,
    )
    client = TestClient(app, raise_server_exceptions=True)
    return client, approval_flow


class TestHealthEndpoint:
    def test_health_returns_ok(self) -> None:
        client, _ = _make_app()
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["pending_approvals"] == 0

    def test_health_shows_pending_count(self) -> None:
        client, approval_flow = _make_app()
        from src.integrations.notifications.approval_flow import _PendingApproval

        req = ApprovalRequest(title="test", description="test")
        approval_flow._pending[req.id] = _PendingApproval(req)  # noqa: SLF001

        resp = client.get("/health")
        assert resp.json()["pending_approvals"] == 1


class TestApprovalStatusEndpoint:
    def test_get_approval_status_pending(self) -> None:
        client, approval_flow = _make_app()
        from src.integrations.notifications.approval_flow import _PendingApproval

        req = ApprovalRequest(title="merge PR", description="test")
        approval_flow._pending[req.id] = _PendingApproval(req)  # noqa: SLF001

        resp = client.get(f"/approvals/{req.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["request_id"] == req.id
        assert data["status"] == "pending"
        assert data["title"] == "merge PR"

    def test_unknown_id_returns_404(self) -> None:
        client, _ = _make_app()
        resp = client.get("/approvals/doesnotexist")
        assert resp.status_code == 404

