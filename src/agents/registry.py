"""Agent registry — tracks active agents and manages their lifecycle."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.agents.base import load_limits_config
from src.agents.bedrock_client import BedrockClient
from src.agents.claude_sdk_client import ClaudeSDKClient
from src.agents.communication import MessageBus
from src.agents.worker import Worker
from src.schemas.skill import SkillSet
from src.schemas.task import SubTask

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Central registry that tracks orchestrator and worker agents.

    It enforces the ``max_concurrent`` worker limit from
    ``config/limits.yaml`` and provides helpers for spawning workers
    and performing graceful shutdown.
    """

    def __init__(
        self,
        message_bus: MessageBus,
        bedrock_client: BedrockClient | None = None,
        claude_sdk_client: ClaudeSDKClient | None = None,
        mcp_call: Any | None = None,
    ) -> None:
        self._message_bus = message_bus
        self._bedrock_client = bedrock_client
        self._claude_sdk_client = claude_sdk_client
        self._mcp_call = mcp_call
        self._workers: dict[str, Worker] = {}
        self._orchestrator_id: str | None = None
        self._lock = asyncio.Lock()

        limits = load_limits_config()
        self._max_concurrent: int = int(
            limits.get("workers", {}).get("max_concurrent", 5)
        )

    # -- orchestrator -----------------------------------------------

    def register_orchestrator(self, agent_id: str) -> None:
        """Record the orchestrator so the registry knows who is in charge."""
        self._orchestrator_id = agent_id
        logger.info("Registry: orchestrator registered as %s", agent_id)

    @property
    def orchestrator_id(self) -> str | None:
        return self._orchestrator_id

    # -- workers ----------------------------------------------------

    async def spawn_worker(self, subtask: SubTask, skill_set: SkillSet | None = None) -> Worker:
        """Create a :class:`Worker`, subscribe it to the bus, and track it.

        Raises :class:`RuntimeError` if the concurrent-worker cap is reached.
        """
        async with self._lock:
            if len(self._workers) >= self._max_concurrent:
                raise RuntimeError(
                    f"Cannot spawn worker — limit of {self._max_concurrent} "
                    f"concurrent workers reached"
                )

            worker = Worker(
                subtask_id=subtask.id,
                bedrock_client=self._bedrock_client,
                claude_sdk_client=self._claude_sdk_client,
                mcp_call=self._mcp_call,
                skill_set=skill_set,
            )
            worker._message_handler = self._message_bus
            await self._message_bus.subscribe(worker.agent_id)
            self._workers[worker.agent_id] = worker
            logger.info(
                "Registry: spawned worker %s for subtask %s (%d/%d)",
                worker.agent_id,
                subtask.id,
                len(self._workers),
                self._max_concurrent,
            )
            return worker

    def get_worker(self, agent_id: str) -> Worker | None:
        return self._workers.get(agent_id)

    def get_active_workers(self) -> list[Worker]:
        """Return all workers that are currently registered."""
        return list(self._workers.values())

    async def remove_worker(self, agent_id: str) -> None:
        """Unregister a worker and remove its message subscription."""
        async with self._lock:
            worker = self._workers.pop(agent_id, None)
        if worker is not None:
            await self._message_bus.unsubscribe(agent_id)
            logger.info("Registry: removed worker %s", agent_id)

    # -- bulk operations --------------------------------------------

    async def shutdown_all(self) -> None:
        """Gracefully shut down every tracked worker.

        Calls each worker's ``__aexit__`` to flip its running flag, then
        clears the internal registry.
        """
        async with self._lock:
            worker_ids = list(self._workers.keys())

        for wid in worker_ids:
            worker = self._workers.get(wid)
            if worker is not None:
                await worker.__aexit__(None, None, None)
                await self._message_bus.unsubscribe(wid)

        async with self._lock:
            self._workers.clear()

        logger.info("Registry: all workers shut down")

    # -- introspection ----------------------------------------------

    @property
    def active_worker_count(self) -> int:
        return len(self._workers)

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent
