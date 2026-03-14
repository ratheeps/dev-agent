"""Main workflow pipeline — drives the Jira-to-PR state machine."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

from src.agents.orchestrator import Orchestrator
from src.integrations.mcp_manager import MCPManager
from src.integrations.scm.github_adapter import GitHubSCMAdapter
from src.integrations.notifications.approval_flow import ApprovalFlow, ApprovalTrigger
from src.memory.client import MemoryClient
from src.schemas.task import Task, TaskStatus
from src.settings import get_settings
from src.workflows.code_implementation import CodeImplementationHandler
from src.workflows.jira_ingestion import JiraIngestionHandler
from src.workflows.pr_creation import PRCreationHandler
from src.workflows.review_loop import ReviewLoopHandler
from src.workflows.states import (
    TERMINAL_STATES,
    WorkflowContext,
    WorkflowState,
)

logger = logging.getLogger(__name__)


class WorkflowPipeline:
    """Orchestrates the full Jira ticket → PR lifecycle.

    The pipeline is a state machine that transitions through defined states,
    persisting context to memory after each transition so it can be resumed
    after a crash.
    """

    def __init__(
        self,
        *,
        jira_key: str,
        orchestrator: Orchestrator,
        mcp_manager: MCPManager,
        memory_client: MemoryClient,
        approval_flow: ApprovalFlow | None = None,
    ) -> None:
        self._jira_key = jira_key
        self._orchestrator = orchestrator
        self._mcp = mcp_manager
        self._memory = memory_client
        self._approval_flow = approval_flow

        self._context = WorkflowContext(
            workflow_id=uuid.uuid4().hex[:12],
            jira_key=jira_key,
        )

        self._ingestion = JiraIngestionHandler(mcp_manager=mcp_manager)
        self._implementation = CodeImplementationHandler(mcp_manager=mcp_manager)
        self._pr_creation = PRCreationHandler(mcp_manager=mcp_manager)
        self._review_loop = ReviewLoopHandler(mcp_manager=mcp_manager)

    @property
    def context(self) -> WorkflowContext:
        return self._context

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def run(self) -> WorkflowContext:
        """Drive the pipeline from current state to completion or failure."""
        logger.info(
            "Pipeline %s: starting for %s (state=%s)",
            self._context.workflow_id,
            self._jira_key,
            self._context.current_state.value,
        )

        while not self._context.is_terminal:
            handler = self._state_handlers.get(self._context.current_state)
            if handler is None:
                logger.error(
                    "Pipeline %s: no handler for state %s",
                    self._context.workflow_id,
                    self._context.current_state.value,
                )
                self._context.transition_to(
                    WorkflowState.FAILED,
                    condition=f"No handler for state {self._context.current_state.value}",
                )
                break

            try:
                await handler(self)
            except Exception as exc:
                logger.exception(
                    "Pipeline %s: handler for %s raised %s",
                    self._context.workflow_id,
                    self._context.current_state.value,
                    exc,
                )
                self._context.error_info = str(exc)
                if self._context.can_retry:
                    self._context.transition_to(
                        WorkflowState.FAILED,
                        condition=str(exc),
                    )
                    self._context.transition_to(
                        WorkflowState.RETRYING,
                        condition=f"Retry {self._context.retry_count + 1}",
                    )
                    self._context.retry_count += 1
                else:
                    self._context.transition_to(
                        WorkflowState.FAILED,
                        condition=f"Max retries exceeded: {exc}",
                    )

            await self._persist_state()

        logger.info(
            "Pipeline %s: finished in state %s",
            self._context.workflow_id,
            self._context.current_state.value,
        )
        return self._context

    async def resume(self, context: WorkflowContext) -> WorkflowContext:
        """Resume a pipeline from a previously saved context."""
        self._context = context
        self._jira_key = context.jira_key
        logger.info(
            "Pipeline %s: resuming from state %s",
            context.workflow_id,
            context.current_state.value,
        )
        return await self.run()

    def inject_feedback(self, feedback: str) -> None:
        """Inject developer feedback (from Slack @mention) into the pipeline context.

        The feedback is queued in `context.feedback_queue` and consumed by the
        orchestrator/worker on their next iteration.
        """
        self._context.feedback_queue.append(feedback)
        logger.info(
            "Pipeline %s: feedback injected — %r",
            self._context.workflow_id,
            feedback[:80],
        )

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------

    async def _handle_ticket_received(self) -> None:
        logger.info("Pipeline: ticket received — %s", self._jira_key)
        self._context.transition_to(
            WorkflowState.CONTEXT_LOADING,
            condition="Ticket acknowledged",
        )

    async def _handle_context_loading(self) -> None:
        logger.info("Pipeline: loading context for %s", self._jira_key)
        task = await self._ingestion.ingest(self._jira_key)
        self._context.task = task
        self._context.transition_to(
            WorkflowState.PLANNING,
            condition="Context loaded successfully",
        )

    async def _handle_planning(self) -> None:
        if self._context.task is None:
            raise RuntimeError("No task available for planning")

        logger.info("Pipeline: creating plan for %s", self._jira_key)
        plan = await self._orchestrator.create_plan(self._context.task)
        self._context.plan = plan
        self._context.transition_to(
            WorkflowState.DELEGATING,
            condition=f"Plan created with {len(plan.subtasks)} subtasks",
        )

    async def _handle_delegating(self) -> None:
        if self._context.task is None or self._context.plan is None:
            raise RuntimeError("Missing task or plan for delegation")

        logger.info("Pipeline: delegating subtasks for %s", self._jira_key)
        branch_name = f"agent/{self._jira_key.lower().replace('-', '_')}"
        self._context.branch_name = branch_name

        # Create feature branch
        await self._mcp.github.create_branch(
            owner=get_settings().org,
            repo=self._context.task.context.get("repository", ""),
            branch=branch_name,
            from_ref="main",
        )

        self._context.transition_to(
            WorkflowState.IMPLEMENTING,
            condition=f"Branch {branch_name} created, delegating to workers",
        )

    async def _handle_implementing(self) -> None:
        if self._context.task is None or self._context.plan is None:
            raise RuntimeError("Missing task or plan for implementation")

        logger.info("Pipeline: implementing subtasks for %s", self._jira_key)
        results = await self._orchestrator.delegate(
            self._context.plan, self._context.task
        )

        errors = [r for r in results.values() if "error" in r]
        if errors:
            raise RuntimeError(f"{len(errors)} subtask(s) failed: {errors}")

        self._context.transition_to(
            WorkflowState.TESTING,
            condition="All subtasks implemented",
        )

    async def _handle_testing(self) -> None:
        if self._context.task is None:
            raise RuntimeError("No task available for testing")

        logger.info("Pipeline: running tests for %s", self._jira_key)
        file_paths = []
        for st in self._context.task.subtasks:
            file_paths.extend(st.file_paths)

        test_result = await self._implementation.run_tests(file_paths)
        if not test_result.get("passed", False):
            raise RuntimeError(f"Tests failed: {test_result.get('summary', 'unknown')}")

        # Route through approval gate before creating the PR
        if self._approval_flow is not None:
            self._context.transition_to(
                WorkflowState.AWAITING_APPROVAL,
                condition="Tests passed — awaiting human approval before PR",
            )
        else:
            self._context.transition_to(
                WorkflowState.PR_CREATED,
                condition="All tests passed",
            )

    async def _handle_approval_gate(self) -> None:
        """Request human approval before creating the PR.

        Pauses the pipeline until a Slack button action (or @mention) resolves
        the approval. On rejection, re-routes back to IMPLEMENTING so the
        agent can re-plan based on the rejection feedback.
        """
        if self._approval_flow is None:
            # No approval flow configured — skip straight to PR
            self._context.transition_to(
                WorkflowState.PR_CREATED,
                condition="Approval gate skipped (no ApprovalFlow configured)",
            )
            return

        task_title = self._context.task.title if self._context.task else self._jira_key
        repo = self._context.task.context.get("repository", "") if self._context.task else ""

        approval = await self._approval_flow.request_approval(
            trigger=ApprovalTrigger.PRE_MERGE,
            title=f"PR ready for {self._jira_key}: {task_title}",
            description=(
                f"Mason has finished implementing and all tests pass.\n\n"
                f"**Repo**: {repo}\n"
                f"**Branch**: {self._context.branch_name}\n\n"
                "Please review and approve to create the PR, or reject to request changes."
            ),
        )

        from src.integrations.notifications.approval_flow import ApprovalStatus

        if approval.status == ApprovalStatus.APPROVED:
            logger.info("Pipeline: approval granted by %s", approval.response_by)
            self._context.transition_to(
                WorkflowState.PR_CREATED,
                condition=f"Approved by {approval.response_by}",
            )
        elif approval.status == ApprovalStatus.REJECTED:
            logger.info("Pipeline: approval rejected by %s", approval.response_by)
            self._context.feedback_queue.append(
                f"PR rejected by {approval.response_by}. Re-implement with requested changes."
            )
            self._context.transition_to(
                WorkflowState.IMPLEMENTING,
                condition=f"Rejected by {approval.response_by} — re-implementing",
            )
        else:
            # Timed out — proceed anyway to avoid blocking indefinitely
            logger.warning("Pipeline: approval timed out — proceeding with PR creation")
            self._context.transition_to(
                WorkflowState.PR_CREATED,
                condition="Approval timed out — auto-proceeding",
            )

    async def _handle_pr_creation(self) -> None:
        if self._context.task is None or self._context.plan is None:
            raise RuntimeError("Missing task or plan for PR creation")

        logger.info("Pipeline: creating PR for %s", self._jira_key)
        pr_result = await self._pr_creation.create_pr(
            task=self._context.task,
            plan=self._context.plan,
            branch=self._context.branch_name,
            scm_client=GitHubSCMAdapter(client=self._mcp.github, org=get_settings().org),
            jira_client=self._mcp.jira,
            slack_client=self._mcp.slack,
        )
        self._context.pr_url = pr_result.get("pr_url", "")
        self._context.pr_number = pr_result.get("pr_number", 0)

        self._context.transition_to(
            WorkflowState.REVIEWING,
            condition=f"PR created: {self._context.pr_url}",
        )

    async def _handle_reviewing(self) -> None:
        logger.info("Pipeline: monitoring review for PR %s", self._context.pr_url)
        review_result = await self._review_loop.monitor_review(
            pr_number=self._context.pr_number,
            owner=get_settings().org,
            repo=self._context.task.context.get("repository", "") if self._context.task else "",
            github_client=self._mcp.github,
            slack_client=self._mcp.slack,
        )

        if review_result.get("approved"):
            self._context.transition_to(
                WorkflowState.APPROVED,
                condition="PR approved",
            )
        elif review_result.get("changes_requested"):
            self._context.transition_to(
                WorkflowState.CHANGES_REQUESTED,
                condition="Changes requested in review",
            )

    async def _handle_changes_requested(self) -> None:
        logger.info("Pipeline: handling review changes for %s", self._jira_key)
        self._context.transition_to(
            WorkflowState.IMPLEMENTING,
            condition="Re-implementing based on review feedback",
        )

    async def _handle_retrying(self) -> None:
        last_state = self._context.last_non_failure_state
        if last_state is None:
            last_state = WorkflowState.CONTEXT_LOADING

        logger.info(
            "Pipeline: retrying from %s (attempt %d/%d)",
            last_state.value,
            self._context.retry_count,
            self._context.max_retries,
        )
        self._context.transition_to(
            last_state,
            condition=f"Retry attempt {self._context.retry_count}",
        )

    # ------------------------------------------------------------------
    # State handler dispatch table
    # ------------------------------------------------------------------

    _state_handlers: dict[WorkflowState, Any] = {
        WorkflowState.TICKET_RECEIVED: _handle_ticket_received,
        WorkflowState.CONTEXT_LOADING: _handle_context_loading,
        WorkflowState.PLANNING: _handle_planning,
        WorkflowState.DELEGATING: _handle_delegating,
        WorkflowState.IMPLEMENTING: _handle_implementing,
        WorkflowState.TESTING: _handle_testing,
        WorkflowState.AWAITING_APPROVAL: _handle_approval_gate,
        WorkflowState.PR_CREATED: _handle_pr_creation,
        WorkflowState.REVIEWING: _handle_reviewing,
        WorkflowState.CHANGES_REQUESTED: _handle_changes_requested,
        WorkflowState.RETRYING: _handle_retrying,
    }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_state(self) -> None:
        """Save current workflow context to memory for crash recovery."""
        try:
            await self._memory.store_session(
                session_id=self._context.workflow_id,
                data=self._context.model_dump(mode="json"),
            )
        except Exception:
            logger.exception(
                "Pipeline %s: failed to persist state",
                self._context.workflow_id,
            )
