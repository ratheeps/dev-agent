"""Adapter wrapping GitHubRepoClient to satisfy the SCMClient Protocol."""

from __future__ import annotations

import logging
from typing import Any

from src.integrations.github.repo_client import GitHubRepoClient
from src.schemas.scm import SCMBranch, SCMPullRequest

logger = logging.getLogger(__name__)


class GitHubSCMAdapter:
    """Thin adapter so GitHubRepoClient satisfies the SCMClient Protocol.

    Parameters
    ----------
    client:
        Existing GitHubRepoClient instance.
    org:
        GitHub org / owner for all repo operations.
    """

    def __init__(self, client: GitHubRepoClient, org: str) -> None:
        self._client = client
        self._org = org

    async def create_branch(self, repo: str, branch: str, from_ref: str) -> SCMBranch:
        data = await self._client.create_branch(
            owner=self._org,
            repo=repo,
            branch=branch,
            from_ref=from_ref,
        )
        sha: str = data.get("sha", data.get("object", {}).get("sha", ""))
        return SCMBranch(name=branch, sha=sha, repo=repo)

    async def create_pull_request(
        self,
        repo: str,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str,
        reviewers: list[str] | None = None,
    ) -> SCMPullRequest:
        gh_pr = await self._client.create_pull_request(
            owner=self._org,
            repo=repo,
            title=title,
            body=body,
            head=head_branch,
            base=base_branch,
        )
        return SCMPullRequest(
            number=gh_pr.number,
            url=gh_pr.html_url,
            title=gh_pr.title,
            body=gh_pr.body or "",
            head_branch=head_branch,
            base_branch=base_branch,
            repo=repo,
            state=gh_pr.state,
        )

    async def get_pull_request(self, repo: str, pr_number: int) -> SCMPullRequest:
        gh_pr = await self._client.get_pull_request(
            owner=self._org,
            repo=repo,
            pr_number=pr_number,
        )
        return SCMPullRequest(
            number=gh_pr.number,
            url=gh_pr.html_url,
            title=gh_pr.title,
            body=gh_pr.body or "",
            head_branch=gh_pr.head.ref if gh_pr.head is not None else "",
            base_branch=gh_pr.base.ref if gh_pr.base is not None else "",
            repo=repo,
            state=gh_pr.state,
        )

    async def add_pr_comment(self, repo: str, pr_number: int, body: str) -> None:
        await self._client._call(  # noqa: SLF001
            self._client._tool("create_issue_comment"),
            {"owner": self._org, "repo": repo, "issue_number": pr_number, "body": body},
        )

    async def get_file_contents(self, repo: str, path: str, ref: str) -> str:
        raw: Any = await self._client._call(  # noqa: SLF001
            self._client._tool("get_file_contents"),
            {"owner": self._org, "repo": repo, "path": path, "ref": ref},
        )
        if isinstance(raw, dict):
            return str(raw.get("content", ""))
        return str(raw)
