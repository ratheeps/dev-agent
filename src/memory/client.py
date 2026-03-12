"""Unified memory client that wraps all three memory tiers.

Provides a single entry point for agents to interact with session (short-term),
episodic, and semantic (long-term) memory.
"""

from __future__ import annotations

import logging
from typing import Any

from src.memory.config import MemoryConfig
from src.memory.episodic import Episode, EpisodicMemory
from src.memory.semantic import SemanticEntry, SemanticMemory
from src.memory.short_term import SessionEntry, SessionMemory

logger = logging.getLogger(__name__)


class MemoryClient:
    """Facade over session, episodic, and semantic memory stores.

    Parameters
    ----------
    config:
        Shared memory configuration.  When ``None`` a default
        ``MemoryConfig`` is constructed (reads from env vars).
    """

    def __init__(self, config: MemoryConfig | None = None) -> None:
        self._config = config or MemoryConfig()
        self._session = SessionMemory(self._config)
        self._episodic = EpisodicMemory(self._config)
        self._semantic = SemanticMemory(self._config)

    @property
    def config(self) -> MemoryConfig:
        return self._config

    # ------------------------------------------------------------------
    # Session (short-term) memory
    # ------------------------------------------------------------------

    async def store_session(self, session_id: str, data: dict[str, Any]) -> SessionEntry:
        """Store active task state for a session."""
        return await self._session.store(session_id, data)

    async def get_session(self, session_id: str, limit: int = 50) -> list[SessionEntry]:
        """Retrieve session entries ordered newest-first."""
        return await self._session.get(session_id, limit=limit)

    async def clear_session(self, session_id: str) -> int:
        """Clear all entries for a completed session. Returns items deleted."""
        return await self._session.clear(session_id)

    # ------------------------------------------------------------------
    # Episodic memory
    # ------------------------------------------------------------------

    async def store_episode(self, agent_id: str, episode: Episode) -> Episode:
        """Record a task outcome.

        The *agent_id* parameter is a convenience override; it will be set on
        the episode before storage.
        """
        episode.agent_id = agent_id
        return await self._episodic.store(episode)

    async def search_episodes(
        self,
        agent_id: str,
        query: str = "",
        tags: list[str] | None = None,
        limit: int | None = None,
    ) -> list[Episode]:
        """Find similar past episodes by query text and/or tags."""
        return await self._episodic.search(agent_id, query=query, tags=tags, limit=limit)

    async def get_episode(self, agent_id: str, episode_id: str) -> Episode | None:
        """Retrieve a specific episode by its composite key."""
        return await self._episodic.get(agent_id, episode_id)

    # ------------------------------------------------------------------
    # Semantic (long-term) memory
    # ------------------------------------------------------------------

    async def store_semantic(
        self,
        namespace: str,
        key: str,
        value: str,
        metadata: dict[str, Any] | None = None,
    ) -> SemanticEntry:
        """Store permanent knowledge under a namespace."""
        return await self._semantic.store(namespace, key, value, metadata=metadata)

    async def get_semantic(self, namespace: str, key: str) -> SemanticEntry | None:
        """Retrieve a specific semantic entry."""
        return await self._semantic.get(namespace, key)

    async def search_semantic(
        self,
        namespace: str,
        query: str = "",
        limit: int | None = None,
    ) -> list[SemanticEntry]:
        """Search semantic entries within a namespace."""
        return await self._semantic.search(namespace, query=query, limit=limit)

    async def seed_from_claude_md(self, path: str) -> int:
        """Parse CLAUDE.md and seed semantic memory with extracted rules."""
        return await self._semantic.seed_from_claude_md(path)
