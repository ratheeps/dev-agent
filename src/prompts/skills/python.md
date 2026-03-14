# Python Skill

You are an expert Python developer. Apply these guidelines when implementing Python code for the mason
orchestration system. This project uses **Python 3.12**, **asyncio**, **Pydantic v2**, **httpx**, **FastAPI**,
**pytest/pytest-asyncio**, **ruff** (linting), and **mypy** (strict type checking).

## Python Version and Style

- Target **Python 3.12+**
- Use `from __future__ import annotations` at the top of every module
- All functions must have **explicit type hints** — mypy strict mode is enforced
- Prefer **async/await** over sync for I/O-bound operations
- Use absolute imports from `src.`: `from src.schemas.task import Task`
- 4-space indentation, snake_case for files/functions, PascalCase for classes, UPPER_CASE for constants

## Module Header Template

```python
"""Short module description (one line)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.agents.orchestrator import Orchestrator

logger = logging.getLogger(__name__)
```

## Pydantic v2 Models

Use **Pydantic v2** for all data models. Never pass raw dicts across module boundaries.

```python
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    FAILED = "failed"


class Task(BaseModel):
    """Represents a unit of work assigned to a worker agent."""

    id: str = Field(..., description="Jira issue key, e.g. GIFT-1234")
    title: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    repo: str | None = None
    branch: str | None = None
    pr_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("id")
    @classmethod
    def validate_jira_key(cls, v: str) -> str:
        import re
        if not re.match(r"^[A-Z]+-\d+$", v):
            raise ValueError(f"Invalid Jira key format: {v}")
        return v

    @model_validator(mode="after")
    def validate_branch_requires_repo(self) -> Task:
        if self.branch and not self.repo:
            raise ValueError("branch requires repo to be set")
        return self

    model_config = {"frozen": True}  # immutable — create new instances for updates


# Typed config from YAML
class AgentConfig(BaseModel):
    orchestrator_model: str = "claude-opus-4-6"
    worker_model: str = "claude-sonnet-4-6"
    max_workers: int = 5
    task_timeout_seconds: int = 3600
    retry_limit: int = 2
```

## Async Patterns

Everything that does I/O must be `async`. Use `asyncio` primitives for synchronization.

```python
import asyncio
import httpx
from typing import AsyncIterator
from contextlib import asynccontextmanager


# Async context manager for resource cleanup
@asynccontextmanager
async def managed_client(base_url: str) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        yield client


# Concurrent execution with asyncio.gather
async def process_tasks(tasks: list[Task]) -> list[TaskResult]:
    results = await asyncio.gather(
        *[process_single_task(t) for t in tasks],
        return_exceptions=True,
    )
    # Separate successes from failures
    successes = [r for r in results if isinstance(r, TaskResult)]
    failures = [r for r in results if isinstance(r, BaseException)]
    if failures:
        logger.error("Some tasks failed: %s", failures)
    return successes


# asyncio.Event for one-shot signalling (e.g. approval gates)
class ApprovalGate:
    def __init__(self) -> None:
        self._event: asyncio.Event = asyncio.Event()
        self._approved: bool = False

    async def wait(self, timeout: float = 3600.0) -> bool:
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Approval gate timed out after %.0fs", timeout)
        return self._approved

    def resolve(self, approved: bool) -> None:
        self._approved = approved
        self._event.set()


# asyncio.Queue for producer/consumer
class FeedbackQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    async def put(self, feedback: str) -> None:
        await self._queue.put(feedback)

    async def drain(self) -> list[str]:
        items: list[str] = []
        while not self._queue.empty():
            items.append(self._queue.get_nowait())
        return items
```

## httpx for HTTP Calls

Use **httpx** (async) for all HTTP I/O. Never use `requests` in async code.

```python
import httpx
from typing import Any


class JiraClient:
    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token

    async def get_issue(self, key: str) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30.0,
        ) as client:
            response = await client.get(f"/rest/api/3/issue/{key}")
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def add_comment(self, key: str, body: str) -> None:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30.0,
        ) as client:
            response = await client.post(
                f"/rest/api/3/issue/{key}/comment",
                json={"body": {"type": "doc", "version": 1, "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": body}]}
                ]}},
            )
            response.raise_for_status()
```

## FastAPI for Webhook Server

```python
from __future__ import annotations

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel


def create_app() -> FastAPI:
    app = FastAPI(title="mason webhook server", version="1.0.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhooks/approval", status_code=status.HTTP_200_OK)
    async def handle_approval(payload: ApprovalPayload) -> ApprovalResponse:
        gate = approval_registry.get(payload.request_id)
        if gate is None:
            raise HTTPException(status_code=404, detail="Approval request not found")
        gate.resolve(approved=payload.approved)
        return ApprovalResponse(message="Approval recorded")

    return app
```

## Error Handling

- Raise **typed exceptions** — never `raise Exception("msg")`
- Workers retry once, then escalate to Teams notification
- Use `logging` (never `print`) for diagnostics

```python
class AgentError(Exception):
    """Base exception for all agent errors."""


class TaskTimeoutError(AgentError):
    def __init__(self, task_id: str, timeout: float) -> None:
        super().__init__(f"Task {task_id} timed out after {timeout:.0f}s")
        self.task_id = task_id
        self.timeout = timeout


class MCPConnectionError(AgentError):
    def __init__(self, server: str, cause: Exception) -> None:
        super().__init__(f"Failed to connect to MCP server '{server}': {cause}")
        self.server = server
        self.cause = cause


# Logging
logger = logging.getLogger(__name__)

async def run_task(task: Task) -> TaskResult:
    logger.info("Starting task %s", task.id)
    try:
        result = await _execute(task)
        logger.info("Task %s completed successfully", task.id)
        return result
    except TaskTimeoutError as e:
        logger.warning("Task %s timed out: %s", task.id, e)
        raise
    except Exception as e:
        logger.exception("Unexpected error in task %s", task.id)
        raise AgentError(f"Task {task.id} failed: {e}") from e
```

## Configuration (YAML + Pydantic)

```python
from __future__ import annotations

from pathlib import Path
import yaml
from pydantic import BaseModel


class AgentConfig(BaseModel):
    orchestrator_model: str
    worker_model: str
    max_workers: int = 5
    task_timeout_seconds: int = 3600


def load_config(path: Path) -> AgentConfig:
    raw = yaml.safe_load(path.read_text())
    return AgentConfig.model_validate(raw.get("agents", {}))


# Usage
CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "agents.yaml"
config = load_config(CONFIG_PATH)
```

## Testing (pytest + pytest-asyncio)

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# All async tests require @pytest.mark.asyncio
@pytest.mark.asyncio
async def test_approval_gate_resolves() -> None:
    gate = ApprovalGate()

    async def resolve_after_delay() -> None:
        await asyncio.sleep(0.01)
        gate.resolve(approved=True)

    asyncio.create_task(resolve_after_delay())
    approved = await gate.wait(timeout=1.0)
    assert approved is True


# Mocking async functions
@pytest.mark.asyncio
async def test_jira_client_get_issue() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {"key": "GIFT-123", "fields": {"summary": "Test"}}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

        client = JiraClient(base_url="https://jira.example.com", token="tok")
        result = await client.get_issue("GIFT-123")
        assert result["key"] == "GIFT-123"


# Fixtures
@pytest.fixture
def mock_mcp_manager() -> MagicMock:
    manager = MagicMock()
    manager.jira = AsyncMock()
    manager.github = AsyncMock()
    manager.teams = AsyncMock()
    return manager
```

## Type Checking Conventions

```python
from __future__ import annotations
from typing import TYPE_CHECKING

# Use TYPE_CHECKING to avoid circular imports
if TYPE_CHECKING:
    from src.agents.orchestrator import Orchestrator
    from src.workflows.pipeline import WorkflowPipeline

# Use | union syntax (Python 3.10+)
def process(value: str | None) -> str:
    return value or ""

# Use X | None instead of Optional[X]
def find_task(key: str) -> Task | None: ...

# Typed TypeVar for generic functions
from typing import TypeVar
T = TypeVar("T")

def first(items: list[T]) -> T | None:
    return items[0] if items else None

# Protocol for duck typing
from typing import Protocol, runtime_checkable

@runtime_checkable
class SCMClient(Protocol):
    async def create_pull_request(self, title: str, body: str, head: str, base: str) -> str: ...
    async def add_comment(self, pr_number: int, body: str) -> None: ...
```

## Imports Ordering

Follow **ruff** import ordering (enforced in CI):
1. `from __future__ import annotations`
2. Standard library (`asyncio`, `logging`, `pathlib`, etc.)
3. Third-party (`pydantic`, `httpx`, `fastapi`, `yaml`)
4. Local (`src.schemas.*`, `src.agents.*`, etc.)

Use absolute imports from `src.` — never relative `..` imports.

## Anti-Patterns to Avoid

- ❌ `import requests` in async code — use `httpx.AsyncClient`
- ❌ `print()` statements — use `logging`
- ❌ Bare `except:` or `except Exception:` without re-raising or specific handling
- ❌ Raw `dict` crossing module boundaries — use Pydantic models
- ❌ Blocking I/O in async functions (`time.sleep`, `open()` in hot paths)
- ❌ Mutable default arguments: `def f(items=[])` — use `None` with guard
- ❌ Missing type hints — mypy strict mode will fail the CI
- ❌ Relative imports (`from ..agents`) — use absolute `from src.agents`
- ❌ Hardcoded secrets — use environment variables or AWS Secrets Manager
- ❌ `asyncio.run()` inside async code — only at the entry point
