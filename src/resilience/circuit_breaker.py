"""Circuit breaker for MCP tool calls and external service interactions.

Prevents cascading failures by temporarily disabling calls to services
that are consistently failing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Callable, Coroutine, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"  # Normal operation — calls pass through
    OPEN = "open"  # Failing — calls are rejected immediately
    HALF_OPEN = "half_open"  # Testing — allow one call to probe health


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is open."""

    def __init__(self, service: str, retry_after: float) -> None:
        self.service = service
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker open for {service} — retry after {retry_after:.0f}s"
        )


class CircuitBreaker:
    """Per-service circuit breaker.

    Parameters
    ----------
    service:
        Name of the service (e.g., "atlassian", "github").
    failure_threshold:
        Number of consecutive failures before opening the circuit.
    recovery_timeout:
        Seconds to wait before transitioning from OPEN to HALF_OPEN.
    """

    def __init__(
        self,
        service: str,
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> None:
        self.service = service
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                return CircuitState.HALF_OPEN
        return self._state

    async def call(
        self,
        func: Callable[..., Coroutine[Any, Any, T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute *func* through the circuit breaker.

        Raises CircuitOpenError if the circuit is open.
        """
        current_state = self.state

        if current_state == CircuitState.OPEN:
            retry_after = self.recovery_timeout - (
                time.monotonic() - self._last_failure_time
            )
            raise CircuitOpenError(self.service, max(0.0, retry_after))

        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            await self._record_failure()
            raise
        else:
            await self._record_success()
            return result

    async def _record_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit OPEN for %s after %d failures",
                    self.service,
                    self._failure_count,
                )

    async def _record_success(self) -> None:
        async with self._lock:
            if self._state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
                logger.info("Circuit CLOSED for %s — recovered", self.service)
            self._state = CircuitState.CLOSED
            self._failure_count = 0

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
