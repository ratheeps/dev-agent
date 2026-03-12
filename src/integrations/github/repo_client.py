"""Typed async wrapper around GitHub MCP tools.

All methods delegate to the injected ``mcp_call`` callable which invokes the
corresponding GitHub MCP server tool.  Tool names follow the pattern
``mcp__github__<operation>``.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Callable, Coroutine

from src.schemas.github import (
    GitHubFileContent,
    GitHubPullRequest,
    GitHubPullRequestComment,
    GitHubRepo,
)

logger = logging.getLogger(__name__)

McpCallFn = Callable[[str, dict[str, Any]], Coroutine[Any, Any, Any]]


class GitHubRepoClient:
    """High-level async GitHub client backed by MCP tools.

    Parameters
    ----------
    mcp_call:
        Async callable ``(tool_name, arguments) -> Any`` provided by the
        agent runtime.
    tool_prefix:
        Prefix applied to GitHub MCP tool names.  Override if your MCP
        server uses a different naming convention.
    """

    def __init__(
        self,
        mcp_call: McpCallFn,
        tool_prefix: str = "mcp__github__",
    ) -> None:
        self._call = mcp_call
        self._prefix = tool_prefix

    def _tool(self, name: str) -> str:
        return f"{self._prefix}{name}"

    # ------------------------------------------------------------------
    # Repository
    # ------------------------------------------------------------------

    async def get_repo(self, owner: str, repo: str) -> GitHubRepo:
        """Get repository metadata."""
        raw = await self._call(
            self._tool("get_repo"),
            {"owner": owner, "repo": repo},
        )
        return _parse_model(raw, GitHubRepo)

    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------

    async def create_branch(
        self,
        owner: str,
        repo: str,
        branch: str,
        from_ref: str = "main",
    ) -> dict[str, Any]:
        """Create a new branch from *from_ref*.

        Returns the raw ref object from the GitHub API.
        """
        # Resolve the SHA of the source ref first.
        ref_data = await self._call(
            self._tool("get_ref"),
            {"owner": owner, "repo": repo, "ref": f"heads/{from_ref}"},
        )
        sha = _extract_sha(ref_data)

        result: Any = await self._call(
            self._tool("create_ref"),
            {
                "owner": owner,
                "repo": repo,
                "ref": f"refs/heads/{branch}",
                "sha": sha,
            },
        )
        logger.info("Created branch %s from %s (sha=%s)", branch, from_ref, sha)
        return result if isinstance(result, dict) else {"ref": branch, "sha": sha}

    async def delete_branch(self, owner: str, repo: str, branch: str) -> None:
        """Delete a remote branch."""
        await self._call(
            self._tool("delete_ref"),
            {"owner": owner, "repo": repo, "ref": f"heads/{branch}"},
        )
        logger.info("Deleted branch %s/%s:%s", owner, repo, branch)

    # ------------------------------------------------------------------
    # Pull Requests
    # ------------------------------------------------------------------

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> GitHubPullRequest:
        """Open a new pull request."""
        raw = await self._call(
            self._tool("create_pull_request"),
            {
                "owner": owner,
                "repo": repo,
                "title": title,
                "body": body,
                "head": head,
                "base": base,
            },
        )
        return _parse_model(raw, GitHubPullRequest)

    async def get_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> GitHubPullRequest:
        """Fetch a single pull request."""
        raw = await self._call(
            self._tool("get_pull_request"),
            {"owner": owner, "repo": repo, "pull_number": pr_number},
        )
        return _parse_model(raw, GitHubPullRequest)

    async def list_pull_request_comments(
        self,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> list[GitHubPullRequestComment]:
        """List review comments on a pull request."""
        raw = await self._call(
            self._tool("list_pull_request_comments"),
            {"owner": owner, "repo": repo, "pull_number": pr_number},
        )
        items: list[dict[str, Any]] = raw if isinstance(raw, list) else []
        return [_parse_model(item, GitHubPullRequestComment) for item in items]

    # ------------------------------------------------------------------
    # File Contents
    # ------------------------------------------------------------------

    async def push_file(
        self,
        owner: str,
        repo: str,
        path: str,
        content: str,
        message: str,
        branch: str = "main",
        *,
        sha: str | None = None,
    ) -> GitHubFileContent:
        """Create or update a file in a repository.

        Parameters
        ----------
        sha:
            The blob SHA of the file being replaced.  Required when
            updating an existing file; omit when creating a new one.
        """
        encoded = base64.b64encode(content.encode()).decode()

        args: dict[str, Any] = {
            "owner": owner,
            "repo": repo,
            "path": path,
            "message": message,
            "content": encoded,
            "branch": branch,
        }
        if sha is not None:
            args["sha"] = sha

        raw = await self._call(self._tool("create_or_update_file"), args)

        file_data: dict[str, Any] = {}
        if isinstance(raw, dict):
            file_data = raw.get("content", raw)

        return _parse_model(file_data, GitHubFileContent)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

from typing import TypeVar

from pydantic import BaseModel

_T = TypeVar("_T", bound=BaseModel)


def _parse_model(raw: Any, model: type[_T]) -> _T:
    if isinstance(raw, dict):
        return model.model_validate(raw)
    return model.model_validate_json(str(raw))


def _extract_sha(ref_data: Any) -> str:
    """Extract the commit SHA from a Git reference response."""
    if isinstance(ref_data, dict):
        obj = ref_data.get("object", {})
        if isinstance(obj, dict):
            sha: str = obj.get("sha", "")
            if sha:
                return sha
        direct_sha: str = ref_data.get("sha", "")
        if direct_sha:
            return direct_sha
    msg = f"Could not extract SHA from ref data: {ref_data!r}"
    raise ValueError(msg)
