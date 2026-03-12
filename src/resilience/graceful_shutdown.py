"""Graceful shutdown coordinator for the agent system.

Ensures all active workers complete or are cancelled cleanly before
the process exits.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class ShutdownCoordinator:
    """Manages graceful shutdown of async tasks.

    Usage::

        coordinator = ShutdownCoordinator()
        coordinator.install_signal_handlers()

        async with coordinator:
            # Register cleanup callbacks
            coordinator.on_shutdown(cleanup_mcp)
            coordinator.on_shutdown(cleanup_memory)

            # Wait for shutdown signal
            await coordinator.wait()
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout
        self._shutdown_event = asyncio.Event()
        self._callbacks: list[Callable[[], Coroutine[Any, Any, None]]] = []
        self._active_tasks: set[asyncio.Task[Any]] = set()

    def install_signal_handlers(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Install SIGINT/SIGTERM handlers on the event loop."""
        loop = loop or asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._signal_handler, sig)

    def _signal_handler(self, sig: signal.Signals) -> None:
        logger.info("Received %s — initiating graceful shutdown", sig.name)
        self._shutdown_event.set()

    def on_shutdown(self, callback: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """Register an async cleanup callback."""
        self._callbacks.append(callback)

    def track_task(self, task: asyncio.Task[Any]) -> None:
        """Track an active task for cancellation on shutdown."""
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)

    async def wait(self) -> None:
        """Block until a shutdown signal is received."""
        await self._shutdown_event.wait()

    @property
    def is_shutting_down(self) -> bool:
        return self._shutdown_event.is_set()

    async def __aenter__(self) -> ShutdownCoordinator:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self._execute_shutdown()

    async def _execute_shutdown(self) -> None:
        """Cancel tasks and run cleanup callbacks."""
        logger.info("Executing graceful shutdown (timeout=%ss)", self._timeout)

        # Cancel active tasks
        for task in list(self._active_tasks):
            task.cancel()

        if self._active_tasks:
            await asyncio.wait(
                self._active_tasks,
                timeout=self._timeout,
            )

        # Run cleanup callbacks
        for callback in self._callbacks:
            try:
                await asyncio.wait_for(callback(), timeout=self._timeout)
            except asyncio.TimeoutError:
                logger.warning("Shutdown callback timed out: %s", callback)
            except Exception:
                logger.exception("Shutdown callback failed: %s", callback)

        logger.info("Graceful shutdown complete")
