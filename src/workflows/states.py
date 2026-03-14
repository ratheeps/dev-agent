"""Workflow state definitions for the Jira-to-PR pipeline.

Defines the state machine states, valid transitions, and the context
object that travels through the entire pipeline lifecycle.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from src.schemas.plan import Plan
from src.schemas.task import Task


class WorkflowState(str, enum.Enum):
    """All possible states in the Jira-to-PR pipeline."""

    TICKET_RECEIVED = "ticket_received"
    CONTEXT_LOADING = "context_loading"
    PLANNING = "planning"
    DELEGATING = "delegating"
    IMPLEMENTING = "implementing"
    TESTING = "testing"
    AWAITING_APPROVAL = "awaiting_approval"
    PR_CREATED = "pr_created"
    REVIEWING = "reviewing"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    MERGED = "merged"
    DONE = "done"
    FAILED = "failed"
    RETRYING = "retrying"


# ---------------------------------------------------------------------------
# Valid state transitions
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.TICKET_RECEIVED: frozenset({
        WorkflowState.CONTEXT_LOADING,
        WorkflowState.FAILED,
    }),
    WorkflowState.CONTEXT_LOADING: frozenset({
        WorkflowState.PLANNING,
        WorkflowState.FAILED,
        WorkflowState.RETRYING,
    }),
    WorkflowState.PLANNING: frozenset({
        WorkflowState.DELEGATING,
        WorkflowState.FAILED,
        WorkflowState.RETRYING,
    }),
    WorkflowState.DELEGATING: frozenset({
        WorkflowState.IMPLEMENTING,
        WorkflowState.FAILED,
        WorkflowState.RETRYING,
    }),
    WorkflowState.IMPLEMENTING: frozenset({
        WorkflowState.TESTING,
        WorkflowState.FAILED,
        WorkflowState.RETRYING,
    }),
    WorkflowState.TESTING: frozenset({
        WorkflowState.AWAITING_APPROVAL,
        WorkflowState.PR_CREATED,
        WorkflowState.IMPLEMENTING,
        WorkflowState.FAILED,
        WorkflowState.RETRYING,
    }),
    WorkflowState.AWAITING_APPROVAL: frozenset({
        WorkflowState.PR_CREATED,
        WorkflowState.IMPLEMENTING,  # rejected → re-plan
        WorkflowState.FAILED,
    }),
    WorkflowState.PR_CREATED: frozenset({
        WorkflowState.REVIEWING,
        WorkflowState.FAILED,
    }),
    WorkflowState.REVIEWING: frozenset({
        WorkflowState.CHANGES_REQUESTED,
        WorkflowState.APPROVED,
        WorkflowState.FAILED,
    }),
    WorkflowState.CHANGES_REQUESTED: frozenset({
        WorkflowState.IMPLEMENTING,
        WorkflowState.FAILED,
        WorkflowState.RETRYING,
    }),
    WorkflowState.APPROVED: frozenset({
        WorkflowState.MERGED,
        WorkflowState.FAILED,
    }),
    WorkflowState.MERGED: frozenset({
        WorkflowState.DONE,
        WorkflowState.FAILED,
    }),
    WorkflowState.RETRYING: frozenset({
        WorkflowState.CONTEXT_LOADING,
        WorkflowState.PLANNING,
        WorkflowState.DELEGATING,
        WorkflowState.IMPLEMENTING,
        WorkflowState.FAILED,
    }),
    WorkflowState.DONE: frozenset(),
    WorkflowState.FAILED: frozenset({
        WorkflowState.RETRYING,
    }),
}

# Terminal states that end the pipeline loop
TERMINAL_STATES: frozenset[WorkflowState] = frozenset({
    WorkflowState.DONE,
    WorkflowState.FAILED,
})

# Default per-state timeout in seconds
STATE_TIMEOUTS: dict[WorkflowState, int] = {
    WorkflowState.TICKET_RECEIVED: 30,
    WorkflowState.CONTEXT_LOADING: 120,
    WorkflowState.PLANNING: 300,
    WorkflowState.DELEGATING: 60,
    WorkflowState.IMPLEMENTING: 1800,
    WorkflowState.TESTING: 600,
    WorkflowState.AWAITING_APPROVAL: 3600,  # 1 hour for human response
    WorkflowState.PR_CREATED: 60,
    WorkflowState.REVIEWING: 7200,
    WorkflowState.CHANGES_REQUESTED: 1800,
    WorkflowState.APPROVED: 60,
    WorkflowState.MERGED: 60,
    WorkflowState.RETRYING: 60,
}


class WorkflowTransition(BaseModel):
    """Record of a single state transition in the pipeline."""

    from_state: WorkflowState
    to_state: WorkflowState
    condition: str = Field(
        default="",
        description="Human-readable reason for the transition",
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkflowContext(BaseModel):
    """Mutable context that accompanies the workflow through every state.

    Serialised to memory after each transition so the pipeline can be
    resumed from the last successful state after a crash.
    """

    workflow_id: str
    jira_key: str
    task: Task | None = None
    plan: Plan | None = None
    current_state: WorkflowState = WorkflowState.TICKET_RECEIVED
    transitions: list[WorkflowTransition] = Field(default_factory=list)
    pr_url: str = ""
    pr_number: int = 0
    branch_name: str = ""
    error_info: str = ""
    retry_count: int = 0
    max_retries: int = 3
    feedback_queue: list[str] = Field(
        default_factory=list,
        description="Developer feedback injected via Slack @mentions",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def transition_to(self, new_state: WorkflowState, condition: str = "") -> None:
        """Validate and execute a state transition.

        Raises
        ------
        InvalidTransitionError
            If the transition is not allowed by ``VALID_TRANSITIONS``.
        """
        allowed = VALID_TRANSITIONS.get(self.current_state, frozenset())
        if new_state not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition from {self.current_state.value} to "
                f"{new_state.value}. Allowed: "
                f"{', '.join(s.value for s in allowed)}"
            )

        transition = WorkflowTransition(
            from_state=self.current_state,
            to_state=new_state,
            condition=condition,
        )
        self.transitions.append(transition)
        self.current_state = new_state
        self.updated_at = datetime.now(timezone.utc)

    @property
    def is_terminal(self) -> bool:
        """Return ``True`` when the workflow has reached a final state."""
        return self.current_state in TERMINAL_STATES

    @property
    def can_retry(self) -> bool:
        """Return ``True`` when the workflow is eligible for a retry."""
        return self.retry_count < self.max_retries

    @property
    def last_non_failure_state(self) -> WorkflowState | None:
        """Return the most recent state before the current FAILED state.

        Useful for deciding where to resume after a retry.
        """
        for transition in reversed(self.transitions):
            if transition.from_state not in (
                WorkflowState.FAILED,
                WorkflowState.RETRYING,
            ):
                return transition.from_state
        return None


class InvalidTransitionError(Exception):
    """Raised when a state transition violates the state machine rules."""
