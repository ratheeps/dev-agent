"""PR review monitoring and response loop."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.integrations.github.repo_client import GitHubRepoClient
from src.integrations.mcp_manager import MCPManager
from src.integrations.teams.notification_client import TeamsNotificationClient

logger = logging.getLogger(__name__)

# Default review polling interval in seconds
DEFAULT_POLL_INTERVAL = 60
# Maximum time to wait for a review before timing out (2 hours)
DEFAULT_REVIEW_TIMEOUT = 7200


class ReviewLoopHandler:
    """Monitors PR reviews and handles change requests."""

    def __init__(self, *, mcp_manager: MCPManager) -> None:
        self._mcp = mcp_manager

    async def monitor_review(
        self,
        *,
        pr_number: int,
        owner: str,
        repo: str,
        github_client: GitHubRepoClient,
        teams_client: TeamsNotificationClient,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        timeout: int = DEFAULT_REVIEW_TIMEOUT,
    ) -> dict[str, Any]:
        """Poll for review status until approved, changes requested, or timeout.

        Returns a dict with keys:
        - approved: bool
        - changes_requested: bool
        - comments: list of review comments
        - timed_out: bool
        """
        logger.info(
            "ReviewLoop: monitoring PR #%d on %s/%s (poll=%ds, timeout=%ds)",
            pr_number,
            owner,
            repo,
            poll_interval,
            timeout,
        )

        elapsed = 0
        seen_comments: set[str] = set()

        while elapsed < timeout:
            # Fetch PR status
            pr_data = await github_client.get_pull_request(
                owner=owner,
                repo=repo,
                pr_number=pr_number,
            )

            # Check if merged
            if pr_data.get("merged", False):
                logger.info("ReviewLoop: PR #%d was merged", pr_number)
                return {"approved": True, "changes_requested": False, "comments": [], "timed_out": False}

            # Check review state
            state = pr_data.get("review_state", "")
            if state == "APPROVED":
                logger.info("ReviewLoop: PR #%d approved", pr_number)
                return {"approved": True, "changes_requested": False, "comments": [], "timed_out": False}

            if state == "CHANGES_REQUESTED":
                # Fetch comments for context
                comments = await github_client.list_pull_request_comments(
                    owner=owner,
                    repo=repo,
                    pr_number=pr_number,
                )
                new_comments = [
                    c for c in comments
                    if c.get("id", "") not in seen_comments
                ]
                for c in new_comments:
                    seen_comments.add(c.get("id", ""))

                logger.info(
                    "ReviewLoop: PR #%d has changes requested (%d new comments)",
                    pr_number,
                    len(new_comments),
                )
                return {
                    "approved": False,
                    "changes_requested": True,
                    "comments": new_comments,
                    "timed_out": False,
                }

            # Check for new comments
            comments = await github_client.list_pull_request_comments(
                owner=owner,
                repo=repo,
                pr_number=pr_number,
            )
            new_comments = [
                c for c in comments
                if c.get("id", "") not in seen_comments
            ]
            for c in new_comments:
                seen_comments.add(c.get("id", ""))
                await self._handle_comment(c, pr_number, teams_client)

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        # Timed out
        logger.warning("ReviewLoop: PR #%d review timed out after %ds", pr_number, timeout)
        await teams_client.send_message(
            channel_id="dev-ai-notifications",
            message=f"**Review timeout**: PR #{pr_number} has been waiting for review for {timeout // 60} minutes.",
        )
        return {"approved": False, "changes_requested": False, "comments": [], "timed_out": True}

    async def _handle_comment(
        self,
        comment: dict[str, Any],
        pr_number: int,
        teams_client: TeamsNotificationClient,
    ) -> None:
        """Process a new review comment."""
        body = comment.get("body", "")
        author = comment.get("user", {}).get("login", "unknown")
        logger.info(
            "ReviewLoop: new comment on PR #%d by %s: %s",
            pr_number,
            author,
            body[:100],
        )

    @staticmethod
    def parse_review_comment(comment: dict[str, Any]) -> dict[str, Any]:
        """Parse a review comment into a structured format.

        Returns dict with: action (approve/request_changes/comment), body, file_path, line.
        """
        return {
            "action": comment.get("state", "comment").lower(),
            "body": comment.get("body", ""),
            "file_path": comment.get("path", ""),
            "line": comment.get("line", 0),
            "author": comment.get("user", {}).get("login", ""),
        }
