"""Tests for the WorkflowPipeline and state machine."""

from __future__ import annotations

import pytest

from src.workflows.states import (
    InvalidTransitionError,
    WorkflowContext,
    WorkflowState,
)


def test_valid_transition() -> None:
    ctx = WorkflowContext(workflow_id="w1", jira_key="GIFT-1")
    assert ctx.current_state == WorkflowState.TICKET_RECEIVED

    ctx.transition_to(WorkflowState.CONTEXT_LOADING, condition="start")
    assert ctx.current_state == WorkflowState.CONTEXT_LOADING
    assert len(ctx.transitions) == 1
    assert ctx.transitions[0].from_state == WorkflowState.TICKET_RECEIVED
    assert ctx.transitions[0].to_state == WorkflowState.CONTEXT_LOADING


def test_invalid_transition() -> None:
    ctx = WorkflowContext(workflow_id="w1", jira_key="GIFT-1")
    with pytest.raises(InvalidTransitionError, match="Cannot transition"):
        ctx.transition_to(WorkflowState.MERGED)


def test_terminal_state() -> None:
    ctx = WorkflowContext(workflow_id="w1", jira_key="GIFT-1")
    ctx.transition_to(WorkflowState.FAILED, condition="error")
    assert ctx.is_terminal is True


def test_done_is_terminal() -> None:
    ctx = WorkflowContext(
        workflow_id="w1",
        jira_key="GIFT-1",
        current_state=WorkflowState.MERGED,
    )
    ctx.transition_to(WorkflowState.DONE)
    assert ctx.is_terminal is True


def test_can_retry() -> None:
    ctx = WorkflowContext(workflow_id="w1", jira_key="GIFT-1", max_retries=2)
    assert ctx.can_retry is True

    ctx.retry_count = 2
    assert ctx.can_retry is False


def test_full_happy_path_transitions() -> None:
    ctx = WorkflowContext(workflow_id="w1", jira_key="GIFT-1")

    path = [
        WorkflowState.CONTEXT_LOADING,
        WorkflowState.PLANNING,
        WorkflowState.DELEGATING,
        WorkflowState.IMPLEMENTING,
        WorkflowState.TESTING,
        WorkflowState.PR_CREATED,
        WorkflowState.REVIEWING,
        WorkflowState.APPROVED,
        WorkflowState.MERGED,
        WorkflowState.DONE,
    ]

    for state in path:
        ctx.transition_to(state)

    assert ctx.current_state == WorkflowState.DONE
    assert ctx.is_terminal is True
    assert len(ctx.transitions) == len(path)


def test_retry_path() -> None:
    ctx = WorkflowContext(workflow_id="w1", jira_key="GIFT-1")
    ctx.transition_to(WorkflowState.CONTEXT_LOADING)
    ctx.transition_to(WorkflowState.PLANNING)
    ctx.transition_to(WorkflowState.FAILED, condition="planning error")
    ctx.transition_to(WorkflowState.RETRYING)
    ctx.transition_to(WorkflowState.PLANNING)

    assert ctx.current_state == WorkflowState.PLANNING
    assert len(ctx.transitions) == 5


def test_changes_requested_loop() -> None:
    ctx = WorkflowContext(
        workflow_id="w1",
        jira_key="GIFT-1",
        current_state=WorkflowState.REVIEWING,
    )
    ctx.transition_to(WorkflowState.CHANGES_REQUESTED)
    ctx.transition_to(WorkflowState.IMPLEMENTING)
    ctx.transition_to(WorkflowState.TESTING)
    ctx.transition_to(WorkflowState.PR_CREATED)
    ctx.transition_to(WorkflowState.REVIEWING)
    ctx.transition_to(WorkflowState.APPROVED)

    assert ctx.current_state == WorkflowState.APPROVED


def test_last_non_failure_state() -> None:
    ctx = WorkflowContext(workflow_id="w1", jira_key="GIFT-1")
    ctx.transition_to(WorkflowState.CONTEXT_LOADING)
    ctx.transition_to(WorkflowState.PLANNING)
    ctx.transition_to(WorkflowState.FAILED)

    assert ctx.last_non_failure_state == WorkflowState.PLANNING
