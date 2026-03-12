"""Tests for the Orchestrator agent."""

from __future__ import annotations

import pytest

from src.agents.communication import MessageBus
from src.agents.orchestrator import Orchestrator
from src.agents.registry import AgentRegistry
from src.schemas.plan import PlanStep
from src.schemas.task import SubTask, Task, TaskStatus


@pytest.fixture
def message_bus() -> MessageBus:
    return MessageBus()


@pytest.fixture
def registry(message_bus: MessageBus) -> AgentRegistry:
    return AgentRegistry(message_bus=message_bus)


@pytest.fixture
def orchestrator(registry: AgentRegistry, message_bus: MessageBus) -> Orchestrator:
    return Orchestrator(registry=registry, message_bus=message_bus)


def test_orchestrator_creation(orchestrator: Orchestrator) -> None:
    assert orchestrator.model == "claude-opus-4-6"
    assert orchestrator.role == "orchestrator"
    assert orchestrator.agent_id.startswith("orchestrator-")


def test_orchestrator_rejects_subtask(orchestrator: Orchestrator) -> None:
    subtask = SubTask(parent_task_id="t1", title="test")
    with pytest.raises(TypeError, match="expects a Task"):
        import asyncio
        asyncio.get_event_loop().run_until_complete(orchestrator.run(subtask))


@pytest.mark.asyncio
async def test_create_plan(orchestrator: Orchestrator) -> None:
    task = Task(
        jira_key="GIFT-100",
        title="Test task",
        subtasks=[
            SubTask(
                id="st1",
                parent_task_id="t1",
                title="Implement feature",
                file_paths=["src/foo.py"],
            ),
            SubTask(
                id="st2",
                parent_task_id="t1",
                title="Write tests",
                file_paths=["tests/test_foo.py"],
                dependencies=["st1"],
            ),
        ],
    )

    plan = await orchestrator.create_plan(task)

    assert plan.task_id == task.id
    assert len(plan.subtasks) == 2
    assert plan.estimated_complexity == "medium"


@pytest.mark.asyncio
async def test_ingest_ticket(orchestrator: Orchestrator) -> None:
    context = await orchestrator.ingest_ticket("GIFT-100")

    assert "jira_issue" in context
    assert "confluence_pages" in context
    assert "figma_designs" in context


@pytest.mark.asyncio
async def test_aggregate_results(orchestrator: Orchestrator) -> None:
    task = Task(jira_key="GIFT-100", title="Test")
    task.subtasks = [
        SubTask(
            parent_task_id=task.id,
            title="sub1",
            status=TaskStatus.COMPLETED,
        ),
    ]

    results = {
        "worker-1": {
            "changed_files": ["src/a.py"],
            "commit_sha": "abc123",
        },
    }

    aggregated = await orchestrator.aggregate_results(results, task)

    assert aggregated["jira_key"] == "GIFT-100"
    assert "src/a.py" in aggregated["changed_files"]
    assert "abc123" in aggregated["commits"]
    assert aggregated["errors"] == []
