"""Tests for Worker Playwright UI methods: screenshot_page, verify_ui, debug_ui, run_e2e_tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.worker import Worker
from src.schemas.playwright import (
    BrowserSnapshot,
    ConsoleError,
    DOMSnapshot,
    UIAssertion,
    UIVerificationResult,
)
from src.schemas.skill import Skill, SkillSet, TechStack

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_worker(mcp_call: Any | None = None, skill_set: SkillSet | None = None) -> Worker:
    return Worker(
        subtask_id="sub-1",
        mcp_call=mcp_call,
        skill_set=skill_set,
    )


def _react_skill_set() -> SkillSet:
    skill = Skill(
        name="react",
        tech_stack=TechStack.REACT,
        description="React",
        prompt_file="skills/react.md",
    )
    return SkillSet(skills=[skill])


def _playwright_skill_set() -> SkillSet:
    skill = Skill(
        name="playwright",
        tech_stack=TechStack.PLAYWRIGHT,
        description="Playwright",
        prompt_file="skills/playwright.md",
    )
    return SkillSet(skills=[skill])


# ---------------------------------------------------------------------------
# _mcp_manager lazy init
# ---------------------------------------------------------------------------


class TestMCPManagerProperty:
    def test_returns_none_when_no_mcp_call(self) -> None:
        worker = _make_worker(mcp_call=None)
        assert worker._mcp_manager is None

    def test_returns_manager_when_mcp_call_provided(self) -> None:
        mock_call = AsyncMock()
        worker = _make_worker(mcp_call=mock_call)
        mgr = worker._mcp_manager
        assert mgr is not None

    def test_returns_same_instance_on_second_access(self) -> None:
        mock_call = AsyncMock()
        worker = _make_worker(mcp_call=mock_call)
        mgr1 = worker._mcp_manager
        mgr2 = worker._mcp_manager
        assert mgr1 is mgr2


# ---------------------------------------------------------------------------
# screenshot_page
# ---------------------------------------------------------------------------


class TestScreenshotPage:
    @pytest.mark.asyncio
    async def test_returns_empty_snapshot_without_mcp(self) -> None:
        worker = _make_worker(mcp_call=None)
        result = await worker.screenshot_page("http://localhost:3000")
        assert isinstance(result, BrowserSnapshot)
        assert result.url == "http://localhost:3000"

    @pytest.mark.asyncio
    async def test_delegates_to_playwright_client(self) -> None:
        mock_call = AsyncMock()
        worker = _make_worker(mcp_call=mock_call)

        expected_snapshot = BrowserSnapshot(url="http://localhost:3000", title="App")
        mock_playwright = AsyncMock()
        mock_playwright.screenshot_url = AsyncMock(return_value=expected_snapshot)

        with patch.object(type(worker), "_mcp_manager", new_callable=lambda: property(
            lambda self: MagicMock(playwright=mock_playwright)
        )):
            result = await worker.screenshot_page("http://localhost:3000")

        mock_playwright.screenshot_url.assert_called_once_with("http://localhost:3000")
        assert result == expected_snapshot


# ---------------------------------------------------------------------------
# verify_ui
# ---------------------------------------------------------------------------


class TestVerifyUI:
    @pytest.mark.asyncio
    async def test_returns_passed_true_without_mcp(self) -> None:
        worker = _make_worker(mcp_call=None)
        result = await worker.verify_ui("http://localhost:3000")
        assert isinstance(result, UIVerificationResult)
        assert result.passed is True
        assert result.url == "http://localhost:3000"

    @pytest.mark.asyncio
    async def test_delegates_to_playwright_with_assertions(self) -> None:
        mock_call = AsyncMock()
        worker = _make_worker(mcp_call=mock_call)

        assertions = [UIAssertion(selector="h1", expected_text="Welcome")]
        expected_result = UIVerificationResult(
            url="http://localhost:3000",
            passed=True,
            failures=[],
        )
        mock_playwright = AsyncMock()
        mock_playwright.verify_assertions = AsyncMock(return_value=expected_result)

        with patch.object(type(worker), "_mcp_manager", new_callable=lambda: property(
            lambda self: MagicMock(playwright=mock_playwright)
        )):
            result = await worker.verify_ui("http://localhost:3000", assertions)

        mock_playwright.verify_assertions.assert_called_once_with(
            url="http://localhost:3000",
            assertions=assertions,
        )
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_passes_empty_assertions_when_none_given(self) -> None:
        mock_call = AsyncMock()
        worker = _make_worker(mcp_call=mock_call)

        expected_result = UIVerificationResult(url="http://localhost:3000", passed=True)
        mock_playwright = AsyncMock()
        mock_playwright.verify_assertions = AsyncMock(return_value=expected_result)

        with patch.object(type(worker), "_mcp_manager", new_callable=lambda: property(
            lambda self: MagicMock(playwright=mock_playwright)
        )):
            await worker.verify_ui("http://localhost:3000")

        call_kwargs = mock_playwright.verify_assertions.call_args
        assert call_kwargs[1]["assertions"] == []


# ---------------------------------------------------------------------------
# debug_ui
# ---------------------------------------------------------------------------


class TestDebugUI:
    @pytest.mark.asyncio
    async def test_returns_empty_dom_snapshot_without_mcp(self) -> None:
        worker = _make_worker(mcp_call=None)
        dom, errors = await worker.debug_ui("http://localhost:3000")
        assert isinstance(dom, DOMSnapshot)
        assert dom.url == "http://localhost:3000"
        assert errors == []

    @pytest.mark.asyncio
    async def test_returns_dom_and_console_errors(self) -> None:
        mock_call = AsyncMock()
        worker = _make_worker(mcp_call=mock_call)

        expected_dom = DOMSnapshot(url="http://localhost:3000", html="<html>...</html>")
        expected_errors = [ConsoleError(level="error", message="Uncaught ReferenceError")]

        mock_playwright = AsyncMock()
        mock_playwright.navigate = AsyncMock(return_value={})
        mock_playwright.get_dom_snapshot = AsyncMock(return_value=expected_dom)
        mock_playwright.get_console_errors = AsyncMock(return_value=expected_errors)

        with patch.object(type(worker), "_mcp_manager", new_callable=lambda: property(
            lambda self: MagicMock(playwright=mock_playwright)
        )):
            dom, errors = await worker.debug_ui("http://localhost:3000")

        assert dom == expected_dom
        assert errors == expected_errors
        mock_playwright.navigate.assert_called_once_with("http://localhost:3000")


# ---------------------------------------------------------------------------
# run_e2e_tests
# ---------------------------------------------------------------------------


class TestRunE2ETests:
    @pytest.mark.asyncio
    async def test_returns_structured_result(self) -> None:
        mock_call = AsyncMock()
        worker = _make_worker(mcp_call=mock_call)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = {"output": "5 passed"}

        with patch.object(worker, "call_mcp_tool", new_callable=AsyncMock) as mock_tool:
            mock_tool.return_value = mock_result
            result = await worker.run_e2e_tests("e2e")

        assert result["passed"] is True
        assert result["test_dir"] == "e2e"
        assert "E2E tests passed" in result["summary"]

    @pytest.mark.asyncio
    async def test_uses_default_e2e_dir(self) -> None:
        worker = _make_worker()

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.data = {"output": "2 failed"}

        with patch.object(worker, "call_mcp_tool", new_callable=AsyncMock) as mock_tool:
            mock_tool.return_value = mock_result
            result = await worker.run_e2e_tests()

        assert result["test_dir"] == "e2e"
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# _is_frontend_task
# ---------------------------------------------------------------------------


class TestIsFrontendTask:
    def test_false_without_skill_set(self) -> None:
        worker = _make_worker()
        assert worker._is_frontend_task() is False

    def test_true_with_react_skill(self) -> None:
        worker = _make_worker(skill_set=_react_skill_set())
        assert worker._is_frontend_task() is True

    def test_true_with_playwright_skill(self) -> None:
        worker = _make_worker(skill_set=_playwright_skill_set())
        assert worker._is_frontend_task() is True

    def test_false_with_non_frontend_skill(self) -> None:
        skill = Skill(
            name="php",
            tech_stack=TechStack.PHP,
            description="PHP",
            prompt_file="skills/php.md",
        )
        worker = _make_worker(skill_set=SkillSet(skills=[skill]))
        assert worker._is_frontend_task() is False
