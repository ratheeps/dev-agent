"""Short-term / session memory for active task state.

Stores current task context, intermediate results, and conversation state in
DynamoDB with automatic TTL expiry.  All public methods are async and
thread-safe via an ``asyncio.Lock``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field

from src.memory.config import MemoryConfig

logger = logging.getLogger(__name__)


class SessionEntry(BaseModel):
    """A single timestamped entry within a session."""

    session_id: str
    timestamp: float = Field(default_factory=time.time)
    data: dict[str, Any] = Field(default_factory=dict)
    ttl: int = 0


class SessionMemory:
    """Manages short-term session state in DynamoDB.

    Parameters
    ----------
    config:
        Memory configuration (table names, TTLs, region, etc.).
    """

    def __init__(self, config: MemoryConfig | None = None) -> None:
        self._config = config or MemoryConfig()
        self._lock = asyncio.Lock()
        self._table_name = self._config.session_table
        self._ttl_seconds = self._config.session_ttl_seconds
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazily create the boto3 DynamoDB client."""
        if self._client is None:
            kwargs: dict[str, Any] = {"region_name": self._config.aws_region}
            if self._config.dynamodb_endpoint_url:
                kwargs["endpoint_url"] = self._config.dynamodb_endpoint_url
            self._client = boto3.client("dynamodb", **kwargs)
        return self._client

    async def store(self, session_id: str, data: dict[str, Any]) -> SessionEntry:
        """Store active task state for *session_id*.

        A TTL is automatically applied based on the configured
        ``session_ttl_seconds``.
        """
        now = time.time()
        ttl_epoch = int(now) + self._ttl_seconds
        entry = SessionEntry(session_id=session_id, timestamp=now, data=data, ttl=ttl_epoch)

        async with self._lock:
            try:
                client = self._get_client()
                await asyncio.to_thread(
                    client.put_item,
                    TableName=self._table_name,
                    Item={
                        "session_id": {"S": session_id},
                        "timestamp": {"N": str(entry.timestamp)},
                        "data": {"S": json.dumps(data)},
                        "ttl": {"N": str(ttl_epoch)},
                    },
                )
            except ClientError:
                logger.warning("DynamoDB unavailable — session entry not persisted", exc_info=True)
            except Exception:
                logger.warning(
                    "Unexpected error storing session entry", exc_info=True
                )

        return entry

    async def get(self, session_id: str, limit: int = 50) -> list[SessionEntry]:
        """Retrieve all entries for *session_id* ordered by timestamp descending."""
        async with self._lock:
            try:
                client = self._get_client()
                response = await asyncio.to_thread(
                    client.query,
                    TableName=self._table_name,
                    KeyConditionExpression="session_id = :sid",
                    ExpressionAttributeValues={":sid": {"S": session_id}},
                    ScanIndexForward=False,
                    Limit=limit,
                )
            except ClientError:
                logger.warning(
                    "DynamoDB unavailable — returning empty session", exc_info=True
                )
                return []
            except Exception:
                logger.warning("Unexpected error querying session", exc_info=True)
                return []

        entries: list[SessionEntry] = []
        for item in response.get("Items", []):
            entries.append(
                SessionEntry(
                    session_id=item["session_id"]["S"],
                    timestamp=float(item["timestamp"]["N"]),
                    data=json.loads(item["data"]["S"]),
                    ttl=int(item.get("ttl", {}).get("N", "0")),
                )
            )
        return entries

    async def clear(self, session_id: str) -> int:
        """Delete all entries for *session_id*. Returns the number of items deleted."""
        entries = await self.get(session_id, limit=1000)
        deleted = 0

        async with self._lock:
            client = self._get_client()
            for entry in entries:
                try:
                    await asyncio.to_thread(
                        client.delete_item,
                        TableName=self._table_name,
                        Key={
                            "session_id": {"S": session_id},
                            "timestamp": {"N": str(entry.timestamp)},
                        },
                    )
                    deleted += 1
                except ClientError:
                    logger.warning(
                        "DynamoDB unavailable — could not delete session entry", exc_info=True
                    )
                except Exception:
                    logger.warning("Unexpected error deleting session entry", exc_info=True)

        logger.info("Cleared %d session entries for %s", deleted, session_id)
        return deleted
