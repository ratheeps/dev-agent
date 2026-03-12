"""Tests for PlaywrightUIClient MCP wrapper."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.integrations.playwright.ui_client import PlaywrightUIClient
from src.schemas.playwright import (
    AssertionFailure,
    BrowserSnapshot,
    ConsoleError,
    DOMSnapshot,
    UIAssertion,
    UIVerificationResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mcp_call() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def client(mock_mcp_call: AsyncMock) -> PlaywrightUIClient:
    return PlaywrightUIClient(mcp_call=mock_mcp_call)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestPlaywrightUIClientInit:
    def test_default_tool_prefix(self, mock_mcp_call: AsyncMock) -> None:
        c = PlaywrightUIClient(mcp_call=mock_mcp_call)
        assert c._prefix == "mcp__playwright__"

    def test_custom_tool_prefix(self, mock_mcp_call: AsyncMock) -> None:
        c = PlaywrightUIClient(mcp_call=mock_mcp_call, tool_prefix="custom__pw__")
        assert c._prefix == "custom__pw__"

    def test_tool_name_construction(self, mock_mcp_call: AsyncMock) -> None:
        c = PlaywrightUIClient(mcp_call=mock_mcp_call)
        assert c._tool("navigate") == "mcp__playwright__navigate"
        assert c._tool("screenshot") == "mcp__playwright__screenshot"


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


class TestNavigate:
    @pytest.mark.asyncio
    async def test_navigate_calls_correct_tool(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = {"url": "http://localhost:3000"}
        await client.navigate("http://localhost:3000")
        mock_mcp_call.assert_called_once_with(
            "mcp__playwright__navigate",
            {"url": "http://localhost:3000"},
        )


# ---------------------------------------------------------------------------
# Screenshots
# ---------------------------------------------------------------------------


class TestScreenshot:
    @pytest.mark.asyncio
    async def test_screenshot_returns_browser_snapshot(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = {
            "url": "http://localhost:3000",
            "title": "Home",
            "screenshot": "base64data",
            "timestamp": "2026-01-01T00:00:00Z",
        }
        result = await client.screenshot()
        assert isinstance(result, BrowserSnapshot)
        assert result.url == "http://localhost:3000"
        assert result.title == "Home"
        assert result.screenshot_b64 == "base64data"
        mock_mcp_call.assert_called_once_with("mcp__playwright__screenshot", {})

    @pytest.mark.asyncio
    async def test_screenshot_url_navigates_first(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = {"url": "http://localhost:3000"}
        await client.screenshot_url("http://localhost:3000")
        # First call: navigate, second call: screenshot
        assert mock_mcp_call.call_count == 2
        first_call = mock_mcp_call.call_args_list[0]
        assert first_call[0][0] == "mcp__playwright__navigate"

    @pytest.mark.asyncio
    async def test_screenshot_empty_response_returns_default(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = {}
        result = await client.screenshot()
        assert isinstance(result, BrowserSnapshot)
        assert result.url == ""


# ---------------------------------------------------------------------------
# Interactions
# ---------------------------------------------------------------------------


class TestInteractions:
    @pytest.mark.asyncio
    async def test_click_calls_correct_tool(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = {}
        await client.click("button[type='submit']")
        mock_mcp_call.assert_called_once_with(
            "mcp__playwright__click",
            {"selector": "button[type='submit']"},
        )

    @pytest.mark.asyncio
    async def test_fill_passes_selector_and_value(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = {}
        await client.fill("#email", "user@example.com")
        mock_mcp_call.assert_called_once_with(
            "mcp__playwright__fill",
            {"selector": "#email", "value": "user@example.com"},
        )

    @pytest.mark.asyncio
    async def test_select_option_passes_selector_and_value(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = {}
        await client.select_option("#country", "AU")
        mock_mcp_call.assert_called_once_with(
            "mcp__playwright__select_option",
            {"selector": "#country", "value": "AU"},
        )

    @pytest.mark.asyncio
    async def test_type_text_calls_type_tool(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = {}
        await client.type_text("#search", "hello world")
        mock_mcp_call.assert_called_once_with(
            "mcp__playwright__type",
            {"selector": "#search", "text": "hello world"},
        )


# ---------------------------------------------------------------------------
# Assertions / inspection
# ---------------------------------------------------------------------------


class TestAssertions:
    @pytest.mark.asyncio
    async def test_get_text_returns_string(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = {"text": "Welcome to the app"}
        result = await client.get_text("h1")
        assert result == "Welcome to the app"
        mock_mcp_call.assert_called_once_with(
            "mcp__playwright__get_text", {"selector": "h1"}
        )

    @pytest.mark.asyncio
    async def test_assert_visible_true_on_success(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = {"visible": True}
        assert await client.assert_visible("h1") is True

    @pytest.mark.asyncio
    async def test_assert_visible_false_on_exception(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.side_effect = RuntimeError("Element not found")
        assert await client.assert_visible(".missing") is False

    @pytest.mark.asyncio
    async def test_assert_text_true_when_text_present(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = {"text": "Hello, world!"}
        result = await client.assert_text("p", "Hello")
        assert result is True

    @pytest.mark.asyncio
    async def test_assert_text_false_when_text_missing(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = {"text": "Goodbye"}
        result = await client.assert_text("p", "Hello")
        assert result is False


# ---------------------------------------------------------------------------
# Debug helpers
# ---------------------------------------------------------------------------


class TestDebugHelpers:
    @pytest.mark.asyncio
    async def test_get_console_errors_parses_errors(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = {
            "errors": [
                {"level": "error", "message": "Uncaught TypeError", "source": "app.js", "line": 42}
            ]
        }
        errors = await client.get_console_errors()
        assert len(errors) == 1
        assert isinstance(errors[0], ConsoleError)
        assert errors[0].level == "error"
        assert errors[0].message == "Uncaught TypeError"
        assert errors[0].line == 42

    @pytest.mark.asyncio
    async def test_get_console_errors_empty_on_no_errors(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = {"errors": []}
        errors = await client.get_console_errors()
        assert errors == []

    @pytest.mark.asyncio
    async def test_get_dom_snapshot_returns_dom_snapshot(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = {
            "url": "http://localhost:3000",
            "title": "App",
            "html": "<html>...</html>",
            "visible_text": "Welcome App",
        }
        result = await client.get_dom_snapshot()
        assert isinstance(result, DOMSnapshot)
        assert result.url == "http://localhost:3000"
        assert result.html == "<html>...</html>"

    @pytest.mark.asyncio
    async def test_evaluate_returns_result(
        self, client: PlaywrightUIClient, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.return_value = {"result": 42}
        result = await client.evaluate("1 + 41")
        assert result == 42
        mock_mcp_call.assert_called_once_with(
            "mcp__playwright__evaluate",
            {"expression": "1 + 41"},
        )


# ---------------------------------------------------------------------------
# verify_assertions high-level helper
# ---------------------------------------------------------------------------


class TestVerifyAssertions:
    def _make_mock_call(self) -> AsyncMock:
        """Return a mock that handles navigate, screenshot, get_console_errors,
        assert_visible, and get_text calls in order."""
        mock = AsyncMock()

        async def side_effect(tool: str, args: dict[str, Any]) -> Any:
            if tool.endswith("navigate"):
                return {"url": args.get("url", "")}
            if tool.endswith("screenshot"):
                return {"url": "http://localhost:3000", "title": "App"}
            if tool.endswith("get_console_errors"):
                return {"errors": []}
            if tool.endswith("assert_visible"):
                return {"visible": True}
            if tool.endswith("get_text"):
                return {"text": "Welcome"}
            return {}

        mock.side_effect = side_effect
        return mock

    @pytest.mark.asyncio
    async def test_returns_passed_true_when_all_pass(
        self, mock_mcp_call: AsyncMock
    ) -> None:
        mock_mcp_call.side_effect = self._make_mock_call().side_effect
        client = PlaywrightUIClient(mcp_call=mock_mcp_call)
        result = await client.verify_assertions(
            url="http://localhost:3000",
            assertions=[
                UIAssertion(selector="h1", expected_text="Welcome"),
            ],
        )
        assert isinstance(result, UIVerificationResult)
        assert result.passed is True
        assert result.failures == []

    @pytest.mark.asyncio
    async def test_returns_failures_when_assertion_fails(
        self, mock_mcp_call: AsyncMock
    ) -> None:
        async def side_effect(tool: str, args: dict[str, Any]) -> Any:
            if tool.endswith("navigate"):
                return {}
            if tool.endswith("screenshot"):
                return {}
            if tool.endswith("get_console_errors"):
                return {"errors": []}
            if tool.endswith("get_text"):
                return {"text": "Not matching"}
            return {}

        mock_mcp_call.side_effect = side_effect
        client = PlaywrightUIClient(mcp_call=mock_mcp_call)
        result = await client.verify_assertions(
            url="http://localhost:3000",
            assertions=[UIAssertion(selector="h1", expected_text="Expected text")],
        )
        assert result.passed is False
        assert len(result.failures) == 1
        assert isinstance(result.failures[0], AssertionFailure)
