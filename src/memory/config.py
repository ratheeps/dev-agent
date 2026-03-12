"""Memory subsystem configuration backed by Pydantic settings."""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class DynamoTableDefinition(BaseModel):
    """Schema description for a single DynamoDB table."""

    table_name: str
    partition_key: str
    partition_key_type: str = "S"
    sort_key: str
    sort_key_type: str = "S"
    ttl_attribute: str | None = None
    ttl_enabled: bool = False


SESSION_TABLE = DynamoTableDefinition(
    table_name="devai-session-memory",
    partition_key="session_id",
    partition_key_type="S",
    sort_key="timestamp",
    sort_key_type="N",
    ttl_attribute="ttl",
    ttl_enabled=True,
)

EPISODIC_TABLE = DynamoTableDefinition(
    table_name="devai-episodic-memory",
    partition_key="agent_id",
    partition_key_type="S",
    sort_key="episode_id",
    sort_key_type="S",
)

SEMANTIC_TABLE = DynamoTableDefinition(
    table_name="devai-semantic-memory",
    partition_key="namespace",
    partition_key_type="S",
    sort_key="key",
    sort_key_type="S",
)

ALL_TABLES: list[DynamoTableDefinition] = [SESSION_TABLE, EPISODIC_TABLE, SEMANTIC_TABLE]


class MemoryConfig(BaseSettings):
    """Configuration for the memory subsystem.

    Values are loaded from environment variables prefixed with ``DEVAI_MEMORY_``
    (case-insensitive).  Fallback defaults are suitable for local development
    against DynamoDB Local.
    """

    model_config = {"env_prefix": "DEVAI_MEMORY_", "case_sensitive": False}

    # AWS / connection
    aws_region: str = Field(default="us-east-1", description="AWS region for DynamoDB")
    dynamodb_endpoint_url: str | None = Field(
        default=None,
        description="Override endpoint for DynamoDB Local (e.g. http://localhost:8000)",
    )

    # Table names (allow overriding via env for multi-tenant / staging)
    session_table: str = Field(default=SESSION_TABLE.table_name)
    episodic_table: str = Field(default=EPISODIC_TABLE.table_name)
    semantic_table: str = Field(default=SEMANTIC_TABLE.table_name)

    # TTLs (seconds)
    session_ttl_seconds: int = Field(
        default=86400, description="TTL for session memory items (default 24 h)"
    )

    # Extraction / search
    episodic_search_limit: int = Field(default=10, description="Default max episodes returned")
    semantic_search_limit: int = Field(
        default=20, description="Default max semantic entries returned"
    )

    # Semantic namespaces recognised by the system
    semantic_namespaces: list[str] = Field(
        default=["conventions", "architecture", "preferences", "golden_rules"],
    )
