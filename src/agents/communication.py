"""In-memory async message bus for inter-agent communication."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from src.schemas.message import AgentMessage

logger = logging.getLogger(__name__)


class MessageBus:
    """Lightweight async message bus backed by :class:`asyncio.Queue`.

    Each agent that calls :meth:`subscribe` gets a dedicated queue.
    :meth:`publish` routes messages to the correct queue (or broadcasts
    to every subscriber when ``to_agent == '*'``).
    """

    def __init__(self, maxsize: int = 1000) -> None:
        self._queues: dict[str, asyncio.Queue[AgentMessage]] = {}
        self._maxsize = maxsize
        self._history: list[AgentMessage] = []
        self._lock = asyncio.Lock()

    # -- subscription -----------------------------------------------

    async def subscribe(self, agent_id: str) -> None:
        """Create a mailbox for *agent_id*.

        Calling this twice for the same ID is a no-op.
        """
        async with self._lock:
            if agent_id not in self._queues:
                self._queues[agent_id] = asyncio.Queue(maxsize=self._maxsize)
                logger.debug("MessageBus: subscribed %s", agent_id)

    async def unsubscribe(self, agent_id: str) -> None:
        """Remove the mailbox for *agent_id*."""
        async with self._lock:
            self._queues.pop(agent_id, None)
            logger.debug("MessageBus: unsubscribed %s", agent_id)

    # -- publish / consume ------------------------------------------

    async def publish(self, message: AgentMessage) -> None:
        """Deliver *message* to its recipient(s)."""
        self._history.append(message)

        if message.is_broadcast:
            async with self._lock:
                targets = [
                    (aid, q)
                    for aid, q in self._queues.items()
                    if aid != message.from_agent
                ]
            for agent_id, queue in targets:
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    logger.warning(
                        "MessageBus: queue full for %s — dropping message %s",
                        agent_id,
                        message.id,
                    )
        else:
            async with self._lock:
                queue = self._queues.get(message.to_agent)
            if queue is not None:
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    logger.warning(
                        "MessageBus: queue full for %s — dropping message %s",
                        message.to_agent,
                        message.id,
                    )
            else:
                logger.warning(
                    "MessageBus: no subscriber for %s — message %s undelivered",
                    message.to_agent,
                    message.id,
                )

    async def get_messages(
        self,
        agent_id: str,
        *,
        timeout: float | None = None,
    ) -> list[AgentMessage]:
        """Drain all pending messages for *agent_id*.

        If the queue is empty and *timeout* is given, waits up to *timeout*
        seconds for at least one message.  Returns an empty list on timeout.
        """
        async with self._lock:
            queue = self._queues.get(agent_id)
        if queue is None:
            return []

        messages: list[AgentMessage] = []

        # Fast drain of everything available right now.
        while not queue.empty():
            try:
                messages.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        # If nothing was available, optionally wait for one message.
        if not messages and timeout is not None:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=timeout)
                messages.append(msg)
            except asyncio.TimeoutError:
                pass

        return messages

    # -- introspection ----------------------------------------------

    @property
    def subscriber_ids(self) -> list[str]:
        return list(self._queues.keys())

    @property
    def history(self) -> list[AgentMessage]:
        """Full ordered history of published messages."""
        return list(self._history)

    def history_for(self, agent_id: str) -> list[AgentMessage]:
        """Return messages sent *to* or *from* a specific agent."""
        return [
            m
            for m in self._history
            if m.from_agent == agent_id
            or m.to_agent == agent_id
            or m.is_broadcast
        ]
