"""Token bucket rate limiter for MCP tool calls.

Enforces per-service rate limits to avoid hitting external API quotas.
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    """Raised when a call is rejected due to rate limiting."""

    def __init__(self, service: str, retry_after: float) -> None:
        self.service = service
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded for {service} — retry after {retry_after:.1f}s"
        )


class TokenBucketRateLimiter:
    """Token bucket rate limiter.

    Parameters
    ----------
    service:
        Name of the service being rate-limited.
    max_tokens:
        Maximum number of tokens (burst capacity).
    refill_rate:
        Tokens added per second.
    """

    def __init__(
        self,
        service: str,
        *,
        max_tokens: float = 10.0,
        refill_rate: float = 1.0,
    ) -> None:
        self.service = service
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate

        self._tokens = max_tokens
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        """Acquire *tokens* from the bucket. Blocks until available.

        If blocking is not desired, use :meth:`try_acquire` instead.
        """
        while True:
            acquired = await self.try_acquire(tokens)
            if acquired:
                return
            # Wait for enough tokens to refill
            wait_time = (tokens - self._tokens) / self.refill_rate
            await asyncio.sleep(min(wait_time, 1.0))

    async def try_acquire(self, tokens: float = 1.0) -> bool:
        """Try to acquire *tokens* without blocking.

        Returns True if successful, False if insufficient tokens.
        """
        async with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self.max_tokens,
            self._tokens + elapsed * self.refill_rate,
        )
        self._last_refill = now

    @property
    def available_tokens(self) -> float:
        """Current number of available tokens (approximate)."""
        self._refill()
        return self._tokens
