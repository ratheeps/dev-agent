"""Pydantic models for Playwright MCP browser automation."""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, Field


class BrowserActionType(str, enum.Enum):
    """Types of browser interactions."""

    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    SCREENSHOT = "screenshot"
    EVALUATE = "evaluate"
    CLOSE = "close"


class BrowserAction(BaseModel):
    """A single browser automation action."""

    action_type: BrowserActionType
    selector: str | None = None
    value: str | None = None
    url: str | None = None
    js_expression: str | None = None


class BrowserSnapshot(BaseModel):
    """A captured screenshot with page metadata."""

    url: str
    title: str = ""
    screenshot_b64: str = Field(
        default="",
        description="Base64-encoded PNG screenshot",
    )
    timestamp: str = ""


class ConsoleError(BaseModel):
    """A browser console message captured during page execution."""

    level: str = Field(
        description="Log level: 'error', 'warning', 'info', 'log'",
    )
    message: str
    source: str = ""
    line: int | None = None


class DOMSnapshot(BaseModel):
    """A snapshot of the current page DOM state."""

    url: str
    title: str = ""
    html: str = Field(default="", description="Full page outer HTML")
    visible_text: str = Field(
        default="",
        description="Concatenated visible text content of the page",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class UIAssertion(BaseModel):
    """A single UI assertion to verify against a live page."""

    selector: str = Field(description="CSS selector or ARIA role selector")
    expected_text: str | None = Field(
        default=None,
        description="Assert this text is present within the matched element",
    )
    expected_visible: bool | None = Field(
        default=None,
        description="Assert element is (True) or is not (False) visible",
    )
    description: str = ""


class AssertionFailure(BaseModel):
    """Details of a failed UIAssertion."""

    assertion: UIAssertion
    actual_text: str | None = None
    error_message: str = ""


class UIVerificationResult(BaseModel):
    """The outcome of running a set of UIAssertions against a live page."""

    url: str
    passed: bool
    failures: list[AssertionFailure] = Field(default_factory=list)
    snapshot: BrowserSnapshot | None = None
    console_errors: list[ConsoleError] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
