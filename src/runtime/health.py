"""Health check module for AgentCore Runtime."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def health_check() -> dict[str, Any]:
    """Return a basic health status response.

    AgentCore Runtime calls this periodically to verify the agent is alive.
    """
    return {
        "status": "healthy",
        "service": "dev-ai",
        "version": "0.1.0",
    }
