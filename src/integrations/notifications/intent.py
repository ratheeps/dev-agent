"""Shared intent detection for @mention handling.

Platform-independent — used by the Slack conversation handler.
"""

from __future__ import annotations

import re
from enum import Enum


class IntentType(str, Enum):
    """Intents the agent can recognise from developer @mentions."""

    STATUS_QUERY = "status_query"
    DEBUG_HELP = "debug_help"
    RETRY = "retry"
    CLARIFY = "clarify"
    APPROVE = "approve"
    REJECT = "reject"
    EXPLAIN = "explain"
    STOP = "stop"
    UNKNOWN = "unknown"


# Pattern-based intent detection — keyword matching without LLM call overhead
_INTENT_PATTERNS: list[tuple[IntentType, list[str]]] = [
    (IntentType.STATUS_QUERY, ["status", "what are you", "what's happening", "progress", "where are you"]),  # noqa: E501
    (IntentType.APPROVE, ["approve", "approved", "go ahead", "lgtm", "ship it", "looks good"]),
    (IntentType.REJECT, ["reject", "rejected", "stop this", "don't proceed", "wrong approach", "change this"]),  # noqa: E501
    (IntentType.RETRY, ["retry", "try again", "re-run", "rerun", "run again"]),
    (IntentType.STOP, ["stop", "pause", "halt", "wait", "hold on"]),
    (IntentType.EXPLAIN, ["why", "explain", "how did you", "reason", "rationale"]),
    (IntentType.DEBUG_HELP, ["failing", "broken", "error", "fix", "debug", "not working", "issue"]),
    (IntentType.CLARIFY, ["use ", "instead", "should be", "prefer", "change to", "update approach"]),  # noqa: E501
]


def detect_intent(text: str) -> IntentType:
    """Classify developer @mention text into an IntentType.

    Uses keyword pattern matching. Returns CLARIFY for any instruction-like
    message that doesn't match specific patterns (most developer guidance).
    """
    clean = text.lower().strip()

    for intent, keywords in _INTENT_PATTERNS:
        if any(kw in clean for kw in keywords):
            return intent

    # If the message is phrased as an imperative or instruction, treat as CLARIFY
    if len(clean.split()) >= 3:
        return IntentType.CLARIFY

    return IntentType.UNKNOWN


def extract_jira_key(text: str) -> str | None:
    """Extract a Jira key (e.g. GIFT-1234) from text, or None."""
    match = re.search(r"\b([A-Z]{2,10}-\d+)\b", text)
    return match.group(1) if match else None
