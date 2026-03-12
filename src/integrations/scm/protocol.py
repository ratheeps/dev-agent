"""SCM-agnostic client protocol.

Defines the interface that Bitbucket and GitHub adapters must satisfy.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.schemas.scm import SCMBranch, SCMPullRequest


@runtime_checkable
class SCMClient(Protocol):
    """Protocol for source-control management clients.

    Implementations: BitbucketClient, GitHubSCMAdapter.
    """

    async def create_pull_request(
        self,
        repo: str,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str,
        reviewers: list[str] | None = None,
    ) -> SCMPullRequest:
        """Open a pull request and return the result."""
        ...

    async def get_pull_request(self, repo: str, pr_number: int) -> SCMPullRequest:
        """Fetch a single pull request by number."""
        ...

    async def add_pr_comment(self, repo: str, pr_number: int, body: str) -> None:
        """Post a comment on an existing pull request."""
        ...

    async def get_file_contents(self, repo: str, path: str, ref: str) -> str:
        """Return file contents at the given ref as a string."""
        ...

    async def create_branch(self, repo: str, branch: str, from_ref: str) -> SCMBranch:
        """Create a new branch from *from_ref* and return it."""
        ...
