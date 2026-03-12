"""Pydantic models for tasks and subtasks managed by the agent system."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, enum.Enum):
    """Lifecycle states for a task or subtask."""

    PENDING = "pending"
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    TESTING = "testing"
    REVIEW = "review"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class SubTask(BaseModel):
    """An atomic unit of work assigned to a single worker agent."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    parent_task_id: str = Field(..., description="ID of the owning Task")
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    file_paths: list[str] = Field(
        default_factory=list,
        description="Source files this subtask will create or modify",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="IDs of subtasks that must complete before this one starts",
    )
    result: dict[str, Any] | None = Field(
        default=None,
        description="Worker output once the subtask completes or fails",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def mark_status(self, new_status: TaskStatus) -> None:
        """Transition to *new_status* and bump the updated timestamp."""
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc)

    @property
    def is_terminal(self) -> bool:
        """Return True when the subtask has reached a final state."""
        return self.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}


class Task(BaseModel):
    """Top-level task — usually maps 1:1 with a Jira ticket."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    jira_key: str = Field(..., description="e.g. PROJ-1234")
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: str = "Medium"
    assignee: str | None = None
    subtasks: list[SubTask] = Field(default_factory=list)
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary context gathered from Jira / Confluence / Figma",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def mark_status(self, new_status: TaskStatus) -> None:
        """Transition to *new_status* and bump the updated timestamp."""
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc)

    @property
    def completed_subtask_count(self) -> int:
        return sum(1 for s in self.subtasks if s.status == TaskStatus.COMPLETED)

    @property
    def progress_pct(self) -> float:
        """Percentage of subtasks that have completed (0.0 – 100.0)."""
        if not self.subtasks:
            return 0.0
        return (self.completed_subtask_count / len(self.subtasks)) * 100.0
