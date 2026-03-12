"""Sonnet worker agent — executes subtasks assigned by the orchestrator."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.agents.base import BaseAgent, load_prompt
from src.agents.bedrock_client import BedrockClient
from src.agents.claude_sdk_client import ClaudeSDKClient
from src.schemas.message import MessageType
from src.schemas.skill import SkillSet
from src.schemas.task import SubTask, Task, TaskStatus
from src.skills.composer import SkillComposer
from src.skills.registry import get_default_registry

logger = logging.getLogger(__name__)

_WORKER_PROMPT_FILE = "worker_system.md"


class Worker(BaseAgent):
    """Implementation agent backed by Claude Sonnet 4.6.

    Responsible for:
    1. Executing a single subtask (code changes).
    2. Running relevant tests.
    3. Committing changes via the GitHub MCP server.
    4. Reporting status back to the orchestrator.
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

    # ------------------------------------------------------------------
    # Primary workflow
    # ------------------------------------------------------------------

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
        """Run the implementation -> test -> commit pipeline."""
        changed_files = await self.execute_subtask(subtask, subtask.result or {})

        subtask.mark_status(TaskStatus.TESTING)
        test_result = await self.run_tests(changed_files)

        if not test_result.get("passed", False):
            raise RuntimeError(
                f"Tests failed for subtask {subtask.id}: "
                f"{test_result.get('summary', 'unknown failure')}"
            )

        commit_sha = await self.commit_changes(
            branch=f"agent/{subtask.parent_task_id}/{subtask.id}",
            message=f"feat: {subtask.title}",
        )

        return {
            "subtask_id": subtask.id,
            "changed_files": changed_files,
            "test_result": test_result,
            "commit_sha": commit_sha,
        }

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
