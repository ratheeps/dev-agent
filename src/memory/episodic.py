"""Episodic memory — stores past task outcomes and PR feedback.

Used for questions like *"how was this type of bug fixed before?"* by recording
every completed task as an ``Episode`` and providing tag-based retrieval.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field

from src.memory.config import MemoryConfig

logger = logging.getLogger(__name__)


class Episode(BaseModel):
    """A single recorded task outcome."""

    agent_id: str
    episode_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    jira_key: str = ""
    action_taken: str = ""
    outcome: str = ""
    feedback: str = ""
    timestamp: float = Field(default_factory=time.time)
    tags: list[str] = Field(default_factory=list)


class EpisodicMemory:
    """Manages episodic memory in DynamoDB.

    Parameters
    ----------
    config:
        Memory configuration.
    """

    def __init__(self, config: MemoryConfig | None = None) -> None:
        self._config = config or MemoryConfig()
        self._lock = asyncio.Lock()
        self._table_name = self._config.episodic_table
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            kwargs: dict[str, Any] = {"region_name": self._config.aws_region}
            if self._config.dynamodb_endpoint_url:
                kwargs["endpoint_url"] = self._config.dynamodb_endpoint_url
            self._client = boto3.client("dynamodb", **kwargs)
        return self._client

    async def store(self, episode: Episode) -> Episode:
        """Persist an episode."""
        async with self._lock:
            try:
                client = self._get_client()
                item: dict[str, Any] = {
                    "agent_id": {"S": episode.agent_id},
                    "episode_id": {"S": episode.episode_id},
                    "task_id": {"S": episode.task_id},
                    "jira_key": {"S": episode.jira_key},
                    "action_taken": {"S": episode.action_taken},
                    "outcome": {"S": episode.outcome},
                    "feedback": {"S": episode.feedback},
                    "timestamp": {"N": str(episode.timestamp)},
                    "tags": {"S": json.dumps(episode.tags)},
                }
                await asyncio.to_thread(
                    client.put_item,
                    TableName=self._table_name,
                    Item=item,
                )
            except ClientError:
                logger.warning("DynamoDB unavailable — episode not persisted", exc_info=True)
            except Exception:
                logger.warning("Unexpected error storing episode", exc_info=True)
        return episode

    async def get(self, agent_id: str, episode_id: str) -> Episode | None:
        """Retrieve a specific episode by composite key."""
        try:
            client = self._get_client()
            response = await asyncio.to_thread(
                client.get_item,
                TableName=self._table_name,
                Key={
                    "agent_id": {"S": agent_id},
                    "episode_id": {"S": episode_id},
                },
            )
        except ClientError:
            logger.warning("DynamoDB unavailable — cannot retrieve episode", exc_info=True)
            return None
        except Exception:
            logger.warning("Unexpected error retrieving episode", exc_info=True)
            return None

        item = response.get("Item")
        if not item:
            return None
        return self._item_to_episode(item)

    async def search(
        self,
        agent_id: str,
        query: str = "",
        tags: list[str] | None = None,
        limit: int | None = None,
    ) -> list[Episode]:
        """Search episodes for *agent_id*.

        Filtering strategy:
        * If *tags* are provided, results are filtered to episodes that share
          at least one tag.
        * If *query* is provided, results are filtered to episodes whose
          ``action_taken``, ``outcome``, or ``feedback`` contain the query
          string (case-insensitive).

        Results are ordered newest-first and capped at *limit*.
        """
        effective_limit = limit or self._config.episodic_search_limit

        try:
            client = self._get_client()
            response = await asyncio.to_thread(
                client.query,
                TableName=self._table_name,
                KeyConditionExpression="agent_id = :aid",
                ExpressionAttributeValues={":aid": {"S": agent_id}},
            )
        except ClientError:
            logger.warning("DynamoDB unavailable — returning empty episode list", exc_info=True)
            return []
        except Exception:
            logger.warning("Unexpected error searching episodes", exc_info=True)
            return []

        episodes = [self._item_to_episode(item) for item in response.get("Items", [])]

        # Tag filter
        if tags:
            tag_set = set(tags)
            episodes = [ep for ep in episodes if tag_set.intersection(ep.tags)]

        # Text query filter (simple substring match)
        if query:
            query_lower = query.lower()
            episodes = [
                ep
                for ep in episodes
                if query_lower in ep.action_taken.lower()
                or query_lower in ep.outcome.lower()
                or query_lower in ep.feedback.lower()
            ]

        # Sort newest first, cap at limit
        episodes.sort(key=lambda ep: ep.timestamp, reverse=True)
        return episodes[:effective_limit]

    @staticmethod
    def _item_to_episode(item: dict[str, Any]) -> Episode:
        return Episode(
            agent_id=item["agent_id"]["S"],
            episode_id=item["episode_id"]["S"],
            task_id=item.get("task_id", {}).get("S", ""),
            jira_key=item.get("jira_key", {}).get("S", ""),
            action_taken=item.get("action_taken", {}).get("S", ""),
            outcome=item.get("outcome", {}).get("S", ""),
            feedback=item.get("feedback", {}).get("S", ""),
            timestamp=float(item.get("timestamp", {}).get("N", "0")),
            tags=json.loads(item.get("tags", {}).get("S", "[]")),
        )
