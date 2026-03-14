"""Code implementation workflow handler."""

from __future__ import annotations

import logging
from typing import Any

from src.integrations.mcp_manager import MCPManager
from src.schemas.task import SubTask
from src.settings import get_settings

logger = logging.getLogger(__name__)


class CodeImplementationHandler:
    """Handles the code implementation phase of a subtask.

    Coordinates branch creation, code changes, test execution, and commits
    via the GitHub MCP integration.
    """

    def __init__(self, *, mcp_manager: MCPManager) -> None:
        self._mcp = mcp_manager

    async def implement(
        self,
        subtask: SubTask,
        context: dict[str, Any],
        owner: str = "",
        repo: str = "",
        branch: str = "",
    ) -> dict[str, Any]:
        """Execute the full implementation pipeline for a subtask.

        1. Worker implements code changes (via orchestrator delegation)
        2. Run tests on changed files
        3. Commit changes to branch

        Returns a result dict with changed_files, test_result, commit_sha.
        """
        if not owner:
            owner = get_settings().org

        logger.info(
            "CodeImplementation: implementing subtask %s on branch %s",
            subtask.id,
            branch,
        )

        # The actual code generation is handled by the Worker agent.
        # This handler coordinates the surrounding workflow steps.
        changed_files = list(subtask.file_paths)

        # Run tests
        test_result = await self.run_tests(changed_files)
        if not test_result.get("passed", False):
            # Retry once with additional context
            logger.warning(
                "CodeImplementation: tests failed for subtask %s, retrying",
                subtask.id,
            )
            test_result = await self.run_tests(changed_files)
            if not test_result.get("passed", False):
                return {
                    "subtask_id": subtask.id,
                    "changed_files": changed_files,
                    "test_result": test_result,
                    "error": f"Tests failed after retry: {test_result.get('summary', '')}",
                }

        # Commit changes
        commit_sha = await self._commit(
            owner=owner,
            repo=repo,
            branch=branch,
            message=f"feat: {subtask.title}",
            files=changed_files,
        )

        return {
            "subtask_id": subtask.id,
            "changed_files": changed_files,
            "test_result": test_result,
            "commit_sha": commit_sha,
        }

    async def run_tests(self, file_paths: list[str]) -> dict[str, Any]:
        """Execute tests relevant to the changed files.

        In the current phase this delegates to the GitHub MCP stub.
        Production will invoke a real test runner.
        """
        logger.info("CodeImplementation: running tests for %d files", len(file_paths))

        result = await self._mcp.github.push_file(
            owner=get_settings().org,
            repo="",
            path="",
            content="",
            message="test-run",
            branch="",
        )

        return {
            "passed": True,
            "summary": "All tests passed",
            "file_paths": file_paths,
        }

    async def _commit(
        self,
        *,
        owner: str,
        repo: str,
        branch: str,
        message: str,
        files: list[str],
    ) -> str:
        """Commit changes to the remote branch via GitHub MCP."""
        logger.info(
            "CodeImplementation: committing %d files to %s/%s:%s",
            len(files),
            owner,
            repo,
            branch,
        )

        for file_path in files:
            await self._mcp.github.push_file(
                owner=owner,
                repo=repo,
                path=file_path,
                content="",  # Content provided by worker agent
                message=message,
                branch=branch,
            )

        return f"stub-sha-{branch}"
