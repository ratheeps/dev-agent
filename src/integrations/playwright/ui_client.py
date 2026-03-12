"""Typed async wrapper around the Playwright MCP server tools.

All methods delegate to the injected ``mcp_call`` callable which invokes
the corresponding Playwright MCP tool.  Tool names follow the pattern
``mcp__playwright__<operation>``.

Usage::

    client = PlaywrightUIClient(mcp_call=my_tool_invoker)
    await client.navigate("http://localhost:3000")
    snapshot = await client.screenshot()
    result = await client.verify_assertions(
        url="http://localhost:3000",
        assertions=[
            UIAssertion(selector="h1", expected_text="Welcome"),
        ],
    )
    await client.close()
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from src.schemas.playwright import (
    AssertionFailure,
    BrowserSnapshot,
    ConsoleError,
    DOMSnapshot,
    UIAssertion,
    UIVerificationResult,
)

logger = logging.getLogger(__name__)

McpCallFn = Callable[[str, dict[str, Any]], Coroutine[Any, Any, Any]]


class PlaywrightUIClient:
    """High-level async Playwright client backed by MCP tools.

    Parameters
    ----------
    mcp_call:
        Async callable ``(tool_name, arguments) -> Any`` provided by the
        agent runtime.
    tool_prefix:
        Prefix applied to Playwright MCP tool names.  Override if your MCP
        server uses a different naming convention.
    """

    def __init__(
        self,
        mcp_call: McpCallFn,
        tool_prefix: str = "mcp__playwright__",
    ) -> None:
        self._call = mcp_call
        self._prefix = tool_prefix

    def _tool(self, name: str) -> str:
        return f"{self._prefix}{name}"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def navigate(self, url: str) -> dict[str, Any]:
        """Navigate the browser to *url*."""
        logger.debug("Playwright: navigating to %s", url)
        raw: dict[str, Any] = await self._call(
            self._tool("navigate"),
            {"url": url},
        )
        return raw

    # ------------------------------------------------------------------
    # Screenshots
    # ------------------------------------------------------------------

    async def screenshot(self) -> BrowserSnapshot:
        """Capture a screenshot of the current page."""
        raw = await self._call(self._tool("screenshot"), {})
        return _parse_snapshot(raw)

    async def screenshot_url(self, url: str) -> BrowserSnapshot:
        """Navigate to *url* then capture a screenshot."""
        await self.navigate(url)
        return await self.screenshot()

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------

    async def click(self, selector: str) -> dict[str, Any]:
        """Click the element matching *selector*."""
        raw: dict[str, Any] = await self._call(
            self._tool("click"),
            {"selector": selector},
        )
        return raw

    async def fill(self, selector: str, value: str) -> dict[str, Any]:
        """Fill an input field matching *selector* with *value*."""
        raw: dict[str, Any] = await self._call(
            self._tool("fill"),
            {"selector": selector, "value": value},
        )
        return raw

    async def select_option(self, selector: str, value: str) -> dict[str, Any]:
        """Select *value* in a <select> element matching *selector*."""
        raw: dict[str, Any] = await self._call(
            self._tool("select_option"),
            {"selector": selector, "value": value},
        )
        return raw

    async def type_text(self, selector: str, text: str) -> dict[str, Any]:
        """Type *text* into the element matching *selector* keystroke-by-keystroke."""
        raw: dict[str, Any] = await self._call(
            self._tool("type"),
            {"selector": selector, "text": text},
        )
        return raw

    # ------------------------------------------------------------------
    # Assertions / inspection
    # ------------------------------------------------------------------

    async def get_text(self, selector: str) -> str:
        """Return the inner text of the element matching *selector*."""
        raw = await self._call(
            self._tool("get_text"),
            {"selector": selector},
        )
        if isinstance(raw, dict):
            return str(raw.get("text", ""))
        return str(raw)

    async def assert_visible(self, selector: str) -> bool:
        """Return ``True`` if the element matching *selector* is visible."""
        try:
            raw = await self._call(
                self._tool("assert_visible"),
                {"selector": selector},
            )
            if isinstance(raw, dict):
                return bool(raw.get("visible", True))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("Playwright assert_visible failed for %r: %s", selector, exc)
            return False

    async def assert_text(self, selector: str, expected: str) -> bool:
        """Return ``True`` if the element at *selector* contains *expected* text."""
        actual = await self.get_text(selector)
        return expected in actual

    # ------------------------------------------------------------------
    # Debug helpers
    # ------------------------------------------------------------------

    async def get_console_errors(self) -> list[ConsoleError]:
        """Return console messages captured since last navigation."""
        raw = await self._call(self._tool("get_console_errors"), {})
        errors: list[ConsoleError] = []
        if isinstance(raw, dict):
            for entry in raw.get("errors", []):
                errors.append(
                    ConsoleError(
                        level=entry.get("level", "error"),
                        message=entry.get("message", ""),
                        source=entry.get("source", ""),
                        line=entry.get("line"),
                    )
                )
        return errors

    async def get_dom_snapshot(self) -> DOMSnapshot:
        """Return a snapshot of the current page DOM and visible text."""
        raw = await self._call(self._tool("get_dom_snapshot"), {})
        if isinstance(raw, dict):
            return DOMSnapshot(
                url=raw.get("url", ""),
                title=raw.get("title", ""),
                html=raw.get("html", ""),
                visible_text=raw.get("visible_text", ""),
                metadata=raw.get("metadata", {}),
            )
        return DOMSnapshot(url="")

    async def evaluate(self, js_expression: str) -> Any:
        """Evaluate a JavaScript expression in the page context and return the result."""
        raw = await self._call(
            self._tool("evaluate"),
            {"expression": js_expression},
        )
        if isinstance(raw, dict):
            return raw.get("result")
        return raw

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the browser / page managed by this client."""
        await self._call(self._tool("close"), {})

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------

    async def verify_assertions(
        self,
        url: str,
        assertions: list[UIAssertion],
    ) -> UIVerificationResult:
        """Navigate to *url*, run all *assertions*, and return the result.

        Always captures a screenshot and console errors regardless of
        assertion outcomes so callers have rich debug context.
        """
        await self.navigate(url)
        snapshot = await self.screenshot()
        console_errors = await self.get_console_errors()

        failures: list[AssertionFailure] = []
        for assertion in assertions:
            failure = await self._check_assertion(assertion)
            if failure is not None:
                failures.append(failure)

        return UIVerificationResult(
            url=url,
            passed=len(failures) == 0,
            failures=failures,
            snapshot=snapshot,
            console_errors=console_errors,
        )

    async def _check_assertion(
        self, assertion: UIAssertion
    ) -> AssertionFailure | None:
        """Run a single assertion; return an :class:`AssertionFailure` or ``None``."""
        try:
            if assertion.expected_visible is not None:
                visible = await self.assert_visible(assertion.selector)
                if visible != assertion.expected_visible:
                    return AssertionFailure(
                        assertion=assertion,
                        error_message=(
                            f"Expected visible={assertion.expected_visible}, "
                            f"got visible={visible}"
                        ),
                    )

            if assertion.expected_text is not None:
                actual = await self.get_text(assertion.selector)
                if assertion.expected_text not in actual:
                    return AssertionFailure(
                        assertion=assertion,
                        actual_text=actual,
                        error_message=(
                            f"Expected text {assertion.expected_text!r} "
                            f"not found in {actual!r}"
                        ),
                    )
        except Exception as exc:  # noqa: BLE001
            return AssertionFailure(
                assertion=assertion,
                error_message=f"Assertion raised exception: {exc}",
            )

        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_snapshot(raw: Any) -> BrowserSnapshot:
    """Parse a raw MCP tool response into a :class:`BrowserSnapshot`."""
    if isinstance(raw, dict):
        screenshot_data = raw.get("screenshot", raw.get("data", ""))
        if isinstance(screenshot_data, bytes):
            screenshot_data = base64.b64encode(screenshot_data).decode()
        return BrowserSnapshot(
            url=raw.get("url", ""),
            title=raw.get("title", ""),
            screenshot_b64=str(screenshot_data),
            timestamp=raw.get("timestamp", ""),
        )
    return BrowserSnapshot(url="")
