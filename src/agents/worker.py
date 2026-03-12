"""Sonnet worker agent — executes subtasks assigned by the orchestrator."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.agents.base import BaseAgent, load_prompt
from src.agents.bedrock_client import BedrockClient
from src.agents.claude_sdk_client import ClaudeSDKClient
from src.integrations.mcp_manager import MCPManager
from src.schemas.message import MessageType
from src.schemas.playwright import (
    BrowserSnapshot,
    ConsoleError,
    DOMSnapshot,
    UIAssertion,
    UIVerificationResult,
)
from src.schemas.skill import SkillSet, TechStack
from src.schemas.task import SubTask, Task, TaskStatus
from src.skills.composer import SkillComposer
from src.skills.registry import get_default_registry

logger = logging.getLogger(__name__)

_WORKER_PROMPT_FILE = "worker_system.md"

# Tech stacks that should trigger browser-based UI verification
_FRONTEND_STACKS = frozenset(
    {TechStack.REACT, TechStack.NEXTJS, TechStack.TYPESCRIPT, TechStack.PLAYWRIGHT}
)


class Worker(BaseAgent):
    """Implementation agent backed by Claude Sonnet 4.6.

    Responsible for:
    1. Executing a single subtask (code changes).
    2. Running relevant tests.
    3. Verifying UI for frontend tasks using Playwright MCP.
    4. Committing changes via the GitHub MCP server.
    5. Reporting status back to the orchestrator.
    """

    def __init__(
        self,
        *,
        subtask_id: str | None = None,
        agent_id: str | None = None,
        bedrock_client: BedrockClient | None = None,
        claude_sdk_client: ClaudeSDKClient | None = None,
        mcp_call: Any | None = None,
        skill_set: SkillSet | None = None,
    ) -> None:
        base_prompt = load_prompt(_WORKER_PROMPT_FILE)
        composer = SkillComposer(get_default_registry())
        system_prompt = (
            composer.compose_worker_prompt(base_prompt, skill_set)
            if skill_set and not skill_set.is_empty
            else base_prompt
        )
        super().__init__(
            agent_id=agent_id,
            model="claude-sonnet-4-6",
            role="worker",
            system_prompt=system_prompt,
            bedrock_client=bedrock_client,
            claude_sdk_client=claude_sdk_client,
            mcp_call=mcp_call,
        )
        self._subtask_id = subtask_id
        self._skill_set = skill_set
        self._timeout_seconds: float = (
            float(self._agents_config.get("worker", {}).get("timeout_minutes", 30))
            * 60.0
        )
        self.__mcp_manager: MCPManager | None = None

    @property
    def _mcp_manager(self) -> MCPManager | None:
        """Lazily initialise an MCPManager from the raw mcp_call, if available."""
        if self.__mcp_manager is None and self._mcp_call is not None:
            self.__mcp_manager = MCPManager(mcp_call=self._mcp_call)
        return self.__mcp_manager

    async def run(self, task: Task | SubTask) -> dict[str, Any]:
        """Execute a subtask end-to-end within the configured timeout."""
        if not isinstance(task, SubTask):
            raise TypeError("Worker.run() expects a SubTask, not a Task")

        subtask: SubTask = task
        subtask.mark_status(TaskStatus.IN_PROGRESS)

        logger.info(
            "Worker %s: starting subtask %s — %s",
            self.agent_id,
            subtask.id,
            subtask.title,
        )

        try:
            result = await asyncio.wait_for(
                self._execute_pipeline(subtask),
                timeout=self._timeout_seconds,
            )
        except asyncio.TimeoutError:
            subtask.mark_status(TaskStatus.FAILED)
            error_payload = {
                "subtask_id": subtask.id,
                "error": f"Worker timed out after {self._timeout_seconds}s",
            }
            await self._report_error(error_payload)
            raise
        except Exception as exc:
            subtask.mark_status(TaskStatus.FAILED)
            error_payload = {
                "subtask_id": subtask.id,
                "error": str(exc),
            }
            await self._report_error(error_payload)
            raise

        subtask.mark_status(TaskStatus.COMPLETED)
        subtask.result = result
        await self._report_result(result)

        logger.info("Worker %s: subtask %s completed", self.agent_id, subtask.id)
        return result

    # ------------------------------------------------------------------
    # Pipeline steps
    # ------------------------------------------------------------------

    async def _execute_pipeline(self, subtask: SubTask) -> dict[str, Any]:
        """Run the implementation -> test -> UI verify -> commit pipeline."""
        changed_files = await self.execute_subtask(subtask, subtask.result or {})

        subtask.mark_status(TaskStatus.TESTING)
        test_result = await self.run_tests(changed_files)

        if not test_result.get("passed", False):
            raise RuntimeError(
                f"Tests failed for subtask {subtask.id}: "
                f"{test_result.get('summary', 'unknown failure')}"
            )

        # Run Playwright UI verification for frontend tasks
        ui_result: UIVerificationResult | None = None
        if self._is_frontend_task():
            task_context: dict[str, Any] = subtask.result or {}
            dev_url = str(task_context.get("dev_url", "http://localhost:3000"))
            assertions = _build_assertions_from_context(task_context)
            try:
                ui_result = await self.verify_ui(dev_url, assertions)
                if not ui_result.passed:
                    logger.warning(
                        "Worker %s: UI verification failed (%d failures) — "
                        "attaching debug context but not blocking commit",
                        self.agent_id,
                        len(ui_result.failures),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Worker %s: UI verification skipped (Playwright unavailable): %s",
                    self.agent_id,
                    exc,
                )

        commit_sha = await self.commit_changes(
            branch=f"agent/{subtask.parent_task_id}/{subtask.id}",
            message=f"feat: {subtask.title}",
        )

        result: dict[str, Any] = {
            "subtask_id": subtask.id,
            "changed_files": changed_files,
            "test_result": test_result,
            "commit_sha": commit_sha,
        }
        if ui_result is not None:
            result["ui_verification"] = ui_result.model_dump()

        return result

    async def execute_subtask(
        self,
        subtask: SubTask,
        context: dict[str, Any],
    ) -> list[str]:
        """Implement the code changes described by *subtask*.

        In Phase 3, this invokes the GitHub MCP stub to signal which files
        would be modified.  The actual LLM-driven code generation is wired
        in Phase 6 via Bedrock AgentCore Runtime.

        Returns a list of changed file paths.
        """
        logger.info(
            "Worker %s: executing subtask %s with %d target files",
            self.agent_id,
            subtask.id,
            len(subtask.file_paths),
        )

        for file_path in subtask.file_paths:
            await self.call_mcp_tool(
                server="github",
                tool="edit_file",
                args={
                    "path": file_path,
                    "description": subtask.description,
                },
            )

        return list(subtask.file_paths)

    async def run_tests(self, file_paths: list[str]) -> dict[str, Any]:
        """Run tests relevant to the changed *file_paths*.

        In Phase 3 this is a stub that returns a synthetic pass result.
        Phase 6 will invoke the actual test runner.
        """
        logger.info(
            "Worker %s: running tests for %d files",
            self.agent_id,
            len(file_paths),
        )

        result = await self.call_mcp_tool(
            server="github",
            tool="run_tests",
            args={"file_paths": file_paths},
        )

        return {
            "passed": result.success,
            "summary": "All tests passed" if result.success else "Tests failed",
            "file_paths": file_paths,
        }

    async def commit_changes(self, branch: str, message: str) -> str:
        """Commit staged changes to *branch* via the GitHub MCP server.

        Returns the commit SHA (stub value in Phase 3).
        """
        logger.info(
            "Worker %s: committing to branch %s — %s",
            self.agent_id,
            branch,
            message,
        )

        result = await self.call_mcp_tool(
            server="github",
            tool="create_commit",
            args={"branch": branch, "message": message},
        )

        return str(result.data.get("sha", "stub-sha-placeholder"))

    # ------------------------------------------------------------------
    # Playwright UI methods
    # ------------------------------------------------------------------

    async def screenshot_page(self, url: str) -> BrowserSnapshot:
        """Navigate to *url* and capture a screenshot via Playwright MCP."""
        logger.info("Worker %s: capturing screenshot of %s", self.agent_id, url)
        if self._mcp_manager is None:
            return BrowserSnapshot(url=url)
        return await self._mcp_manager.playwright.screenshot_url(url)

    async def verify_ui(
        self,
        url: str,
        assertions: list[UIAssertion] | None = None,
    ) -> UIVerificationResult:
        """Navigate to *url*, run *assertions*, and return a full verification result.

        Always captures a screenshot and console errors for debug context.
        If *assertions* is empty, returns a result with just the screenshot
        and console errors (useful as a sanity check).
        """
        logger.info(
            "Worker %s: verifying UI at %s (%d assertions)",
            self.agent_id,
            url,
            len(assertions or []),
        )
        if self._mcp_manager is None:
            return UIVerificationResult(url=url, passed=True)
        return await self._mcp_manager.playwright.verify_assertions(
            url=url,
            assertions=assertions or [],
        )

    async def debug_ui(self, url: str) -> tuple[DOMSnapshot, list[ConsoleError]]:
        """Navigate to *url* and capture the full DOM + console errors for debugging."""
        logger.info("Worker %s: capturing debug snapshot of %s", self.agent_id, url)
        if self._mcp_manager is None:
            return DOMSnapshot(url=url), []
        client = self._mcp_manager.playwright
        await client.navigate(url)
        dom = await client.get_dom_snapshot()
        errors = await client.get_console_errors()
        return dom, errors

    async def run_e2e_tests(self, test_dir: str = "e2e") -> dict[str, Any]:
        """Run the Playwright E2E test suite via ``npx playwright test``.

        Uses the Bash MCP tool so the agent SDK's file-system context is used.
        Returns a structured result with pass/fail status and output summary.
        """
        logger.info("Worker %s: running E2E tests in %s", self.agent_id, test_dir)
        result = await self.call_mcp_tool(
            server="github",
            tool="run_tests",
            args={
                "command": f"npx playwright test {test_dir} --reporter=list",
                "file_paths": [],
            },
        )
        return {
            "passed": result.success,
            "summary": "E2E tests passed" if result.success else "E2E tests failed",
            "test_dir": test_dir,
            "output": result.data.get("output", "") if hasattr(result, "data") else "",
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_frontend_task(self) -> bool:
        """Return True if this worker has at least one frontend skill."""
        if self._skill_set is None:
            return False
        detected = {s.tech_stack for s in self._skill_set.skills}
        return bool(detected & _FRONTEND_STACKS)

    # ------------------------------------------------------------------
    # Messaging helpers
    # ------------------------------------------------------------------

    async def _report_result(self, result: dict[str, Any]) -> None:
        """Send a RESULT message back to the orchestrator (broadcast)."""
        msg = self.build_message(
            to_agent="*",
            message_type=MessageType.RESULT,
            payload=result,
        )
        await self.send_message(msg)

    async def _report_error(self, error_payload: dict[str, Any]) -> None:
        """Send an ERROR message back to the orchestrator (broadcast)."""
        msg = self.build_message(
            to_agent="*",
            message_type=MessageType.ERROR,
            payload=error_payload,
        )
        await self.send_message(msg)

    async def report_blocker(self, description: str) -> None:
        """Escalate a blocker that requires human intervention."""
        msg = self.build_message(
            to_agent="*",
            message_type=MessageType.ESCALATION,
            payload={
                "subtask_id": self._subtask_id,
                "blocker": description,
            },
        )
        await self.send_message(msg)
        logger.warning(
            "Worker %s: BLOCKER escalated — %s",
            self.agent_id,
            description,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_assertions_from_context(context: dict[str, Any]) -> list[UIAssertion]:
    """Build UIAssertions from subtask context if provided."""
    raw = context.get("ui_assertions", [])
    assertions: list[UIAssertion] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                assertions.append(UIAssertion(**item))
            except Exception:  # noqa: BLE001
                pass
    return assertions

