"""Long-term semantic memory for permanent project knowledge.

Stores coding conventions, architectural rules, and project preferences in
namespaced key-value entries backed by DynamoDB.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field

from src.memory.config import MemoryConfig

logger = logging.getLogger(__name__)


class SemanticEntry(BaseModel):
    """A single piece of long-term knowledge."""

    namespace: str
    key: str
    value: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: float = Field(default_factory=time.time)


class SemanticMemory:
    """Manages namespaced semantic knowledge in DynamoDB.

    Parameters
    ----------
    config:
        Memory configuration.
    """

    def __init__(self, config: MemoryConfig | None = None) -> None:
        self._config = config or MemoryConfig()
        self._lock = asyncio.Lock()
        self._table_name = self._config.semantic_table
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            kwargs: dict[str, Any] = {"region_name": self._config.aws_region}
            if self._config.dynamodb_endpoint_url:
                kwargs["endpoint_url"] = self._config.dynamodb_endpoint_url
            self._client = boto3.client("dynamodb", **kwargs)
        return self._client

    async def store(self, namespace: str, key: str, value: str, metadata: dict[str, Any] | None = None) -> SemanticEntry:
        """Store or overwrite a semantic entry."""
        entry = SemanticEntry(
            namespace=namespace,
            key=key,
            value=value,
            metadata=metadata or {},
        )

        async with self._lock:
            try:
                client = self._get_client()
                item: dict[str, Any] = {
                    "namespace": {"S": namespace},
                    "key": {"S": key},
                    "value": {"S": value},
                    "metadata": {"S": json.dumps(entry.metadata)},
                    "updated_at": {"N": str(entry.updated_at)},
                }
                await asyncio.to_thread(
                    client.put_item,
                    TableName=self._table_name,
                    Item=item,
                )
            except ClientError:
                logger.warning("DynamoDB unavailable — semantic entry not persisted", exc_info=True)
            except Exception:
                logger.warning("Unexpected error storing semantic entry", exc_info=True)

        return entry

    async def get(self, namespace: str, key: str) -> SemanticEntry | None:
        """Retrieve a specific semantic entry."""
        try:
            client = self._get_client()
            response = await asyncio.to_thread(
                client.get_item,
                TableName=self._table_name,
                Key={
                    "namespace": {"S": namespace},
                    "key": {"S": key},
                },
            )
        except ClientError:
            logger.warning("DynamoDB unavailable — cannot retrieve semantic entry", exc_info=True)
            return None
        except Exception:
            logger.warning("Unexpected error retrieving semantic entry", exc_info=True)
            return None

        item = response.get("Item")
        if not item:
            return None
        return self._item_to_entry(item)

    async def search(self, namespace: str, query: str = "", limit: int | None = None) -> list[SemanticEntry]:
        """Search semantic entries within a namespace.

        If *query* is non-empty, results are filtered to entries whose key or
        value contains the query string (case-insensitive).
        """
        effective_limit = limit or self._config.semantic_search_limit

        try:
            client = self._get_client()
            response = await asyncio.to_thread(
                client.query,
                TableName=self._table_name,
                KeyConditionExpression="#ns = :ns",
                ExpressionAttributeNames={"#ns": "namespace"},
                ExpressionAttributeValues={":ns": {"S": namespace}},
            )
        except ClientError:
            logger.warning("DynamoDB unavailable — returning empty semantic list", exc_info=True)
            return []
        except Exception:
            logger.warning("Unexpected error searching semantic memory", exc_info=True)
            return []

        entries = [self._item_to_entry(item) for item in response.get("Items", [])]

        if query:
            query_lower = query.lower()
            entries = [
                e
                for e in entries
                if query_lower in e.key.lower() or query_lower in e.value.lower()
            ]

        entries.sort(key=lambda e: e.updated_at, reverse=True)
        return entries[:effective_limit]

    async def delete(self, namespace: str, key: str) -> bool:
        """Delete a semantic entry. Returns True if the delete call succeeded."""
        try:
            client = self._get_client()
            await asyncio.to_thread(
                client.delete_item,
                TableName=self._table_name,
                Key={
                    "namespace": {"S": namespace},
                    "key": {"S": key},
                },
            )
            return True
        except ClientError:
            logger.warning("DynamoDB unavailable — cannot delete semantic entry", exc_info=True)
            return False
        except Exception:
            logger.warning("Unexpected error deleting semantic entry", exc_info=True)
            return False

    async def seed_from_claude_md(self, path: str | Path) -> int:
        """Parse a ``CLAUDE.md`` file and seed semantic memory with extracted rules.

        The parser recognises Markdown headings as keys and the content under
        each heading as the value.  Top-level headings (``#``) are treated as
        namespace hints when they match a known namespace; otherwise the
        ``conventions`` namespace is used as default.

        Returns the number of entries stored.
        """
        file_path = Path(path)
        if not file_path.exists():
            logger.warning("CLAUDE.md not found at %s — skipping seed", file_path)
            return 0

        text = file_path.read_text(encoding="utf-8")
        stored = 0

        # Split into sections by heading level 2+ (## or ###)
        section_pattern = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
        matches = list(section_pattern.finditer(text))

        namespace_map: dict[str, str] = {
            "project overview": "architecture",
            "tech stack": "architecture",
            "structure": "architecture",
            "development": "conventions",
            "conventions": "conventions",
        }

        for i, match in enumerate(matches):
            heading_level = len(match.group(1))
            heading_text = match.group(2).strip()

            # Extract body text until the next heading
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()

            if not body:
                continue

            # Determine namespace from top-level heading context
            heading_lower = heading_text.lower()
            namespace = namespace_map.get(heading_lower, "conventions")

            # For level-1 headings, skip storing the heading itself as an entry
            # (it serves only as a namespace selector)
            if heading_level == 1 and heading_lower in namespace_map:
                continue

            safe_key = re.sub(r"[^a-z0-9_-]", "_", heading_lower).strip("_")
            if not safe_key:
                safe_key = f"section_{i}"

            await self.store(
                namespace=namespace,
                key=safe_key,
                value=body,
                metadata={"source": str(file_path), "heading": heading_text},
            )
            stored += 1

        logger.info("Seeded %d semantic entries from %s", stored, file_path)
        return stored

    @staticmethod
    def _item_to_entry(item: dict[str, Any]) -> SemanticEntry:
        return SemanticEntry(
            namespace=item["namespace"]["S"],
            key=item["key"]["S"],
            value=item.get("value", {}).get("S", ""),
            metadata=json.loads(item.get("metadata", {}).get("S", "{}")),
            updated_at=float(item.get("updated_at", {}).get("N", "0")),
        )
