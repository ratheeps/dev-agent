"""Bitbucket REST API v2.0 client.

Implements SCMClient Protocol using httpx async HTTP.
Credentials: BITBUCKET_USERNAME + BITBUCKET_APP_PASSWORD env vars.
"""

from __future__ import annotations

import logging
import os

import httpx

from src.schemas.scm import SCMBranch, SCMPullRequest

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.bitbucket.org/2.0"


class BitbucketClient:
    """Async Bitbucket REST API client.

    Parameters
    ----------
    workspace:
        Bitbucket workspace slug (e.g. ``"giftbee"``).
    username:
        Bitbucket username for app-password auth. Defaults to
        ``BITBUCKET_USERNAME`` env var.
    app_password:
        Bitbucket app password. Defaults to ``BITBUCKET_APP_PASSWORD`` env var.
    """

    def __init__(
        self,
        workspace: str,
        username: str | None = None,
        app_password: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.workspace = workspace
        self._username = username or os.environ.get("BITBUCKET_USERNAME", "")
        self._app_password = app_password or os.environ.get("BITBUCKET_APP_PASSWORD", "")
        self._timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=_BASE_URL,
            auth=(self._username, self._app_password),
            timeout=self._timeout,
            headers={"Accept": "application/json"},
        )

    def _repo_url(self, repo: str) -> str:
        return f"/repositories/{self.workspace}/{repo}"

    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------

    async def create_branch(self, repo: str, branch: str, from_ref: str) -> SCMBranch:
        """Create a new branch from *from_ref*.

        Resolves the SHA of ``from_ref`` first, then creates the new branch.
        """
        async with self._client() as client:
            # Resolve source SHA
            ref_resp = await client.get(
                f"{self._repo_url(repo)}/refs/branches/{from_ref}"
            )
            ref_resp.raise_for_status()
            source_sha: str = ref_resp.json()["target"]["hash"]

            # Create new branch
            resp = await client.post(
                f"{self._repo_url(repo)}/refs/branches",
                json={"name": branch, "target": {"hash": source_sha}},
            )
            resp.raise_for_status()
            data = resp.json()
            sha: str = data["target"]["hash"]
            logger.info("Created Bitbucket branch %s/%s:%s from %s", self.workspace, repo, branch, from_ref)
            return SCMBranch(name=branch, sha=sha, repo=repo)

    # ------------------------------------------------------------------
    # Pull Requests
    # ------------------------------------------------------------------

    async def create_pull_request(
        self,
        repo: str,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str,
        reviewers: list[str] | None = None,
    ) -> SCMPullRequest:
        """Open a pull request."""
        payload: dict[str, object] = {
            "title": title,
            "description": body,
            "source": {"branch": {"name": head_branch}},
            "destination": {"branch": {"name": base_branch}},
            "close_source_branch": False,
        }
        if reviewers:
            payload["reviewers"] = [{"account_id": r} for r in reviewers]

        async with self._client() as client:
            resp = await client.post(
                f"{self._repo_url(repo)}/pullrequests",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        pr = SCMPullRequest(
            number=data["id"],
            url=data["links"]["html"]["href"],
            title=data["title"],
            body=data.get("description", ""),
            head_branch=head_branch,
            base_branch=base_branch,
            repo=repo,
            state=data.get("state", "OPEN").lower(),
        )
        logger.info("Created Bitbucket PR #%d for %s/%s", pr.number, self.workspace, repo)
        return pr

    async def get_pull_request(self, repo: str, pr_number: int) -> SCMPullRequest:
        """Fetch a single pull request."""
        async with self._client() as client:
            resp = await client.get(f"{self._repo_url(repo)}/pullrequests/{pr_number}")
            resp.raise_for_status()
            data = resp.json()

        return SCMPullRequest(
            number=data["id"],
            url=data["links"]["html"]["href"],
            title=data["title"],
            body=data.get("description", ""),
            head_branch=data["source"]["branch"]["name"],
            base_branch=data["destination"]["branch"]["name"],
            repo=repo,
            state=data.get("state", "OPEN").lower(),
        )

    async def add_pr_comment(self, repo: str, pr_number: int, body: str) -> None:
        """Post a comment on a pull request."""
        async with self._client() as client:
            resp = await client.post(
                f"{self._repo_url(repo)}/pullrequests/{pr_number}/comments",
                json={"content": {"raw": body}},
            )
            resp.raise_for_status()
        logger.debug("Added comment to Bitbucket PR #%d on %s", pr_number, repo)

    # ------------------------------------------------------------------
    # File Contents
    # ------------------------------------------------------------------

    async def get_file_contents(self, repo: str, path: str, ref: str) -> str:
        """Return file contents at the given ref as a string."""
        async with self._client() as client:
            resp = await client.get(f"{self._repo_url(repo)}/src/{ref}/{path}")
            resp.raise_for_status()
            return resp.text
