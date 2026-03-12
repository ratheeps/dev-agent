"""Pydantic models for implementation plans produced by the orchestrator."""

from __future__ import annotations

import enum
import uuid

from pydantic import BaseModel, Field


class AgentType(str, enum.Enum):
    """Which class of agent should execute a plan step."""

    ORCHESTRATOR = "orchestrator"
    WORKER = "worker"


class PlanStep(BaseModel):
    """A single step inside an implementation plan."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    description: str
    file_paths: list[str] = Field(
        default_factory=list,
        description="Files this step will create or modify",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="IDs of PlanSteps that must finish first",
    )
    agent_type: AgentType = AgentType.WORKER
    repository: str | None = Field(
        default=None,
        description="Target repository name for this step (e.g. 'wallet-service')",
    )


class Plan(BaseModel):
    """An ordered implementation plan for a Task, produced by the orchestrator."""

    task_id: str = Field(..., description="ID of the Task this plan addresses")
    subtasks: list[PlanStep] = Field(
        default_factory=list,
        description="Ordered list of steps to execute",
    )
    dependency_graph: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Mapping of step ID -> list of step IDs it depends on",
    )
    estimated_complexity: str = Field(
        default="medium",
        description="low / medium / high / critical",
    )
    context_summary: str = Field(
        default="",
        description="Natural-language summary of relevant context for workers",
    )

    def build_dependency_graph(self) -> dict[str, list[str]]:
        """Rebuild *dependency_graph* from the subtask list and return it."""
        graph: dict[str, list[str]] = {}
        for step in self.subtasks:
            graph[step.id] = list(step.dependencies)
        self.dependency_graph = graph
        return graph

    def execution_order(self) -> list[list[str]]:
        """Return step IDs grouped into waves that can run in parallel.

        Each wave contains steps whose dependencies are satisfied by all
        previous waves.  Raises ``ValueError`` on dependency cycles.
        """
        graph = dict(self.dependency_graph) if self.dependency_graph else self.build_dependency_graph()
        remaining = {step.id for step in self.subtasks}
        resolved: set[str] = set()
        waves: list[list[str]] = []

        while remaining:
            wave = [
                sid
                for sid in remaining
                if all(dep in resolved for dep in graph.get(sid, []))
            ]
            if not wave:
                raise ValueError(
                    f"Dependency cycle detected among steps: {remaining}"
                )
            waves.append(wave)
            resolved.update(wave)
            remaining -= set(wave)

        return waves
