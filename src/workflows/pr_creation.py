"""PR creation and management handler."""

from __future__ import annotations

import logging
from typing import Any

from src.integrations.atlassian.jira_client import JiraClient
from src.integrations.mcp_manager import MCPManager
from src.integrations.scm.protocol import SCMClient
from src.integrations.teams.notification_client import TeamsNotificationClient
from src.repositories.registry import RepoRegistry, get_default_repo_registry
from src.schemas.plan import Plan
from src.schemas.scm import SCMPullRequest
from src.schemas.task import Task

logger = logging.getLogger(__name__)


class PRCreationHandler:
    """Creates pull requests with auto-generated descriptions and notifications."""

    def __init__(
        self,
        *,
        mcp_manager: MCPManager,
        repo_registry: RepoRegistry | None = None,
    ) -> None:
        self._mcp = mcp_manager
        self._repo_registry = repo_registry or get_default_repo_registry()

    async def create_pr(
        self,
        *,
        task: Task,
        plan: Plan,
        branch: str,
        scm_client: SCMClient,
        jira_client: JiraClient,
        teams_client: TeamsNotificationClient,
    ) -> dict[str, Any]:
        """Create a PR for a single repo, link to Jira, and notify Teams.

        Returns dict with pr_url, pr_number, and repo.
        """
        repo_name = task.context.get("repository", "")

        # Determine base branch from registry
        base_branch = "main"
        try:
            repo_config = self._repo_registry.get(repo_name)
            base_branch = repo_config.base_branch
        except KeyError:
            logger.warning("Repo %s not in registry, defaulting base to main", repo_name)

        title = f"[{task.jira_key}] {task.title}"
        body = self.generate_pr_description(task, plan)

        pr: SCMPullRequest = await scm_client.create_pull_request(
            repo=repo_name,
            title=title,
            body=body,
            head_branch=branch,
            base_branch=base_branch,
        )

        logger.info("PRCreation: created PR #%d — %s", pr.number, pr.url)

        await jira_client.add_comment(
            key=task.jira_key,
            body=f"PR created by Dev-AI: {pr.url}",
        )

        await teams_client.send_message(
            channel_id="dev-ai-notifications",
            message=(
                f"**New PR for {task.jira_key}**\n"
                f"Repo: `{repo_name}`\n"
                f"Title: {title}\n"
                f"Branch: `{branch}` → `{base_branch}`\n"
                f"PR: {pr.url}\n"
                f"Subtasks completed: {task.completed_subtask_count}/{len(task.subtasks)}"
            ),
        )

        return {
            "pr_url": pr.url,
            "pr_number": pr.number,
            "title": title,
            "repo": repo_name,
        }

    async def create_prs(
        self,
        *,
        task: Task,
        plan: Plan,
        branch: str,
        scm_clients: dict[str, SCMClient],
        jira_client: JiraClient,
        teams_client: TeamsNotificationClient,
    ) -> list[dict[str, Any]]:
        """Create PRs for all target repositories in the task.

        Parameters
        ----------
        scm_clients:
            Dict mapping repo name → SCMClient for that repo.
        """
        target_repos = task.context.get("target_repositories", [])
        if not target_repos:
            primary = task.context.get("repository", "")
            if primary:
                target_repos = [{"repo": primary}]

        created_prs: list[dict[str, Any]] = []
        pr_urls: list[str] = []

        for repo_info in target_repos:
            repo_name = repo_info["repo"] if isinstance(repo_info, dict) else repo_info
            scm = scm_clients.get(repo_name)
            if scm is None:
                logger.warning("No SCM client for repo %s, skipping PR", repo_name)
                continue

            try:
                base_branch = "main"
                try:
                    repo_config = self._repo_registry.get(repo_name)
                    base_branch = repo_config.base_branch
                except KeyError:
                    pass

                title = f"[{task.jira_key}] {task.title}"
                body = self.generate_pr_description(task, plan)

                pr = await scm.create_pull_request(
                    repo=repo_name,
                    title=title,
                    body=body,
                    head_branch=branch,
                    base_branch=base_branch,
                )
                created_prs.append({
                    "pr_url": pr.url,
                    "pr_number": pr.number,
                    "repo": repo_name,
                    "title": title,
                })
                pr_urls.append(pr.url)
                logger.info("Created PR #%d for %s: %s", pr.number, repo_name, pr.url)
            except Exception as e:
                logger.error("Failed to create PR for %s: %s", repo_name, e)
                created_prs.append({"repo": repo_name, "error": str(e)})

        # Single Jira comment with all PRs
        if pr_urls:
            pr_list = "\n".join(f"- {url}" for url in pr_urls)
            await jira_client.add_comment(
                key=task.jira_key,
                body=f"Dev-AI created {len(pr_urls)} PR(s):\n{pr_list}",
            )

        # Teams summary
        repos_str = ", ".join(
            r["repo"] for r in created_prs if "error" not in r
        )
        await teams_client.send_message(
            channel_id="dev-ai-notifications",
            message=(
                f"**{len(pr_urls)} PR(s) ready for {task.jira_key}**\n"
                f"Repos: {repos_str}\n"
                + "\n".join(f"- {url}" for url in pr_urls)
            ),
        )

        return created_prs

    @staticmethod
    def generate_pr_description(task: Task, plan: Plan) -> str:
        """Generate a markdown PR body."""
        changed_files: list[str] = []
        for subtask in task.subtasks:
            changed_files.extend(subtask.file_paths)
        changed_files = sorted(set(changed_files))

        subtask_list = "\n".join(
            f"- [x] {step.description}" for step in plan.subtasks
        )

        file_list = "\n".join(f"- `{f}`" for f in changed_files) if changed_files else "- N/A"

        target_repos = task.context.get("target_repositories", [])
        repos_str = (
            ", ".join(r["repo"] if isinstance(r, dict) else r for r in target_repos)
            if target_repos
            else task.context.get("repository", "unknown")
        )

        return f"""## Summary

Automated implementation for [{task.jira_key}] — {task.title}

{task.description}

## Changes

### Subtasks Completed
{subtask_list}

### Files Modified
{file_list}

## Test Plan
- [ ] All existing tests pass
- [ ] New tests added for changed functionality
- [ ] E2E tests pass (for frontend changes)
- [ ] Manual verification of acceptance criteria

## Context
- **Jira:** {task.jira_key}
- **Repositories:** {repos_str}
- **Complexity:** {plan.estimated_complexity}
- **Subtasks:** {len(plan.subtasks)}

---
*Generated by Dev-AI Agent System*
"""
