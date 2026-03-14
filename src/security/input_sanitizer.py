"""Input sanitization for agent inputs and MCP tool arguments.

Prevents injection attacks by validating and sanitizing all external
inputs before they reach agent prompts or MCP tool calls.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Maximum lengths for common fields
MAX_JIRA_KEY_LENGTH = 20
MAX_SUMMARY_LENGTH = 500
MAX_DESCRIPTION_LENGTH = 50_000
MAX_FILE_PATH_LENGTH = 500

# Patterns that should never appear in agent inputs
DANGEROUS_PATTERNS = [
    re.compile(r"<script\b", re.IGNORECASE),
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"\beval\s*\(", re.IGNORECASE),
    re.compile(r"\bexec\s*\(", re.IGNORECASE),
    re.compile(r";\s*rm\s+-rf\b"),
    re.compile(r"\|\s*bash\b"),
    re.compile(r"\$\(\s*curl\b"),
]

# Valid Jira key pattern
JIRA_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")

# Valid file path pattern (no directory traversal)
SAFE_PATH_PATTERN = re.compile(r"^[\w./\-]+$")


class SanitizationError(Exception):
    """Raised when input fails sanitization."""


def sanitize_jira_key(key: str) -> str:
    """Validate and return a Jira issue key."""
    key = key.strip().upper()
    if len(key) > MAX_JIRA_KEY_LENGTH:
        raise SanitizationError(f"Jira key too long: {len(key)} chars")
    if not JIRA_KEY_PATTERN.match(key):
        raise SanitizationError(f"Invalid Jira key format: {key}")
    return key


def sanitize_text(text: str, max_length: int = MAX_DESCRIPTION_LENGTH) -> str:
    """Sanitize free-text input by removing dangerous patterns."""
    if len(text) > max_length:
        logger.warning("Text truncated from %d to %d chars", len(text), max_length)
        text = text[:max_length]

    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(text):
            logger.warning("Dangerous pattern detected and removed: %s", pattern.pattern)
            text = pattern.sub("[REMOVED]", text)

    return text


def sanitize_file_path(path: str) -> str:
    """Validate a file path — rejects directory traversal and shell metacharacters."""
    path = path.strip()
    if len(path) > MAX_FILE_PATH_LENGTH:
        raise SanitizationError(f"File path too long: {len(path)} chars")

    # Block directory traversal
    if ".." in path:
        raise SanitizationError(f"Directory traversal detected in path: {path}")

    if not SAFE_PATH_PATTERN.match(path):
        raise SanitizationError(f"Unsafe characters in path: {path}")

    return path


def sanitize_mcp_args(args: dict[str, Any]) -> dict[str, Any]:
    """Sanitize all string values in an MCP tool arguments dict."""
    sanitized: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            sanitized[key] = sanitize_text(value, max_length=MAX_DESCRIPTION_LENGTH)
        elif isinstance(value, dict):
            sanitized[key] = sanitize_mcp_args(value)
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_text(v) if isinstance(v, str) else v for v in value
            ]
        else:
            sanitized[key] = value
    return sanitized


# Slack mrkdwn control characters that should be stripped from injected content
_SLACK_INJECTION_PATTERN = re.compile(r"[<>]")


def sanitize_slack_text(text: str, max_length: int = MAX_SUMMARY_LENGTH) -> str:
    """Sanitize Slack @mention text before intent parsing.

    Strips Slack mrkdwn angle brackets (used for links/mentions), truncates
    to ``max_length``, and removes any dangerous shell/script patterns.

    Parameters
    ----------
    text:
        Raw text from a Slack app_mention or DM event (already stripped of
        ``<@BOTID>`` by the Bolt handler or SlackMentionEvent.clean_text).
    max_length:
        Maximum character length (default: MAX_SUMMARY_LENGTH = 500).
    """
    text = _SLACK_INJECTION_PATTERN.sub("", text)
    return sanitize_text(text, max_length=max_length)
