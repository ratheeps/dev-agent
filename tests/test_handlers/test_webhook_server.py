"""Tests for the FastAPI webhook server."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.handlers.webhook_server import create_webhook_app
from src.integrations.teams.approval_flow import ApprovalFlow, ApprovalStatus


def _make_app() -> tuple[TestClient, ApprovalFlow, MagicMock]:
    """Build a TestClient with mock dependencies."""
    teams_mock = AsyncMock()
    teams_mock.send_approval_request = AsyncMock(
        return_value=MagicMock(message_id="msg1", callback_id="cb1", status="pending")
    )
    teams_mock.send_message = AsyncMock()
    teams_mock.send_threaded_reply = AsyncMock()

    approval_flow = ApprovalFlow(teams_client=teams_mock)

    conv_handler = MagicMock()
    conv_handler.handle_mention = AsyncMock(return_value="Test reply")

    app = create_webhook_app(
        approval_flow=approval_flow,
        conversation_handler=conv_handler,
    )
    client = TestClient(app, raise_server_exceptions=True)
    return client, approval_flow, conv_handler


class TestHealthEndpoint:
    def test_health_returns_ok(self) -> None:
        client, _, _ = _make_app()
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["pending_approvals"] == 0

    def test_health_shows_pending_count(self) -> None:
        client, approval_flow, _ = _make_app()
        # Manually inject a fake pending entry
        from src.integrations.teams.approval_flow import ApprovalRequest, _PendingApproval

        req = ApprovalRequest(title="test", description="test")
        approval_flow._pending[req.id] = _PendingApproval(req)  # noqa: SLF001

        resp = client.get("/health")
        assert resp.json()["pending_approvals"] == 1


class TestApprovalEndpoint:
    def test_approve_resolves_pending(self) -> None:
        client, approval_flow, _ = _make_app()
        from src.integrations.teams.approval_flow import ApprovalRequest, _PendingApproval

        req = ApprovalRequest(title="merge PR", description="GIFT-1234 ready")
        approval_flow._pending[req.id] = _PendingApproval(req)  # noqa: SLF001

        resp = client.post(
            "/webhooks/teams/approval",
            json={"requestId": req.id, "approved": True, "responder": "alice"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "approved"
        assert data["responder"] == "alice"
        assert req.status == ApprovalStatus.APPROVED

    def test_reject_resolves_pending(self) -> None:
        client, approval_flow, _ = _make_app()
        from src.integrations.teams.approval_flow import ApprovalRequest, _PendingApproval

        req = ApprovalRequest(title="merge PR", description="GIFT-1234 ready")
        approval_flow._pending[req.id] = _PendingApproval(req)  # noqa: SLF001

        resp = client.post(
            "/webhooks/teams/approval",
            json={"requestId": req.id, "approved": False, "responder": "bob"},
        )
        assert resp.status_code == 200
        assert resp.json()["action"] == "rejected"
        assert req.status == ApprovalStatus.REJECTED

    def test_unknown_request_id_returns_404(self) -> None:
        client, _, _ = _make_app()
        resp = client.post(
            "/webhooks/teams/approval",
            json={"requestId": "nonexistent", "approved": True, "responder": "alice"},
        )
        assert resp.status_code == 404

    def test_missing_required_field_returns_422(self) -> None:
        client, _, _ = _make_app()
        resp = client.post(
            "/webhooks/teams/approval",
            json={"requestId": "abc123"},  # missing 'approved'
        )
        assert resp.status_code == 422


class TestApprovalStatusEndpoint:
    def test_get_approval_status(self) -> None:
        client, approval_flow, _ = _make_app()
        from src.integrations.teams.approval_flow import ApprovalRequest, _PendingApproval

        req = ApprovalRequest(title="merge PR", description="test")
        approval_flow._pending[req.id] = _PendingApproval(req)  # noqa: SLF001

        resp = client.get(f"/approvals/{req.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["request_id"] == req.id
        assert data["status"] == "pending"
        assert data["title"] == "merge PR"

    def test_unknown_id_returns_404(self) -> None:
        client, _, _ = _make_app()
        resp = client.get("/approvals/doesnotexist")
        assert resp.status_code == 404


class TestMessageEndpoint:
    def test_mention_dispatches_to_handler(self) -> None:
        client, _, conv_handler = _make_app()
        resp = client.post(
            "/webhooks/teams/message",
            json={
                "text": "@Mason what is the status?",
                "sender": "alice",
                "channelId": "mason-channel",
                "messageId": "msg123",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["reply"] == "Test reply"
        conv_handler.handle_mention.assert_called_once()

    def test_mention_missing_text_returns_422(self) -> None:
        client, _, _ = _make_app()
        resp = client.post(
            "/webhooks/teams/message",
            json={"sender": "alice"},  # missing 'text'
        )
        assert resp.status_code == 422
