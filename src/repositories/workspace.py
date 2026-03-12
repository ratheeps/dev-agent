"""Git workspace manager — clone, branch, commit, and push operations.

Uses asyncio.create_subprocess_exec for all git CLI commands so the
agent never needs MCP tools for local filesystem SCM operations.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from pathlib import Path

from src.schemas.repository import RepositoryConfig

logger = logging.getLogger(__name__)

BRANCH_PREFIX = "dev-ai"


async def _run_git(
    args: list[str],
    cwd: Path,
    *,
    check: bool = True,
) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    cmd = ["git"] + args
    logger.debug("git %s (cwd=%s)", shlex.join(args), cwd)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    stdout = stdout_b.decode().strip()
    stderr = stderr_b.decode().strip()
    rc = proc.returncode or 0
    if check and rc != 0:
        raise RuntimeError(
            f"git {shlex.join(args)} failed (rc={rc}): {stderr or stdout}"
        )
    return rc, stdout, stderr


class WorkspaceManager:
    """Manages local git workspaces for development agents.

    All operations work against the repo's ``local_path`` (already on disk
    from the developer's setup). In CI environments a clone step would run
    first; locally we assume the repos are already checked out.
    """

    # ------------------------------------------------------------------
    # Repo setup
    # ------------------------------------------------------------------

    async def ensure_repo(self, repo: RepositoryConfig) -> Path:
        """Return the local path, verifying it is a valid git repo.

        Raises RuntimeError if the path doesn't exist or isn't a git repo.
        """
        path = repo.local_path
        if not path.exists():
            raise RuntimeError(
                f"Repo directory not found: {path}. "
                "Clone it first or check local_path in repositories.yaml."
            )
        # Quick sanity check
        _, stdout, _ = await _run_git(["rev-parse", "--show-toplevel"], path)
        if not stdout:
            raise RuntimeError(f"{path} is not inside a git repository")
        return path

    async def clone(self, remote_url: str, target_dir: Path) -> Path:
        """Clone *remote_url* to *target_dir*. Used in CI/fresh environments."""
        if target_dir.exists():
            logger.info("Repo already cloned at %s, skipping", target_dir)
            return target_dir
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", remote_url, str(target_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_b = await proc.communicate()
        rc = proc.returncode or 0
        if rc != 0:
            raise RuntimeError(f"git clone {remote_url} failed: {stderr_b.decode()}")
        logger.info("Cloned %s → %s", remote_url, target_dir)
        return target_dir

    # ------------------------------------------------------------------
    # Branching
    # ------------------------------------------------------------------

    async def create_branch(self, repo: RepositoryConfig, jira_key: str) -> str:
        """Create and checkout feature branch ``dev-ai/{jira_key}``.

        If the branch already exists locally, just checks it out.
        Returns the branch name.
        """
        path = repo.local_path
        branch = f"{BRANCH_PREFIX}/{jira_key}"

        # Fetch latest from origin
        try:
            await _run_git(["fetch", "origin"], path)
        except RuntimeError as e:
            logger.warning("git fetch failed (offline?): %s", e)

        # Check if branch already exists locally
        _, stdout, _ = await _run_git(
            ["branch", "--list", branch], path, check=False
        )
        if stdout:
            await _run_git(["checkout", branch], path)
            logger.info("Checked out existing branch %s in %s", branch, path)
        else:
            base = f"origin/{repo.base_branch}"
            try:
                await _run_git(["checkout", "-b", branch, base], path)
            except RuntimeError:
                # Fall back to local base branch
                await _run_git(["checkout", "-b", branch, repo.base_branch], path)
            logger.info("Created branch %s from %s in %s", branch, base, path)

        return branch

    async def current_branch(self, repo_path: Path) -> str:
        """Return the name of the currently checked-out branch."""
        _, stdout, _ = await _run_git(["branch", "--show-current"], repo_path)
        return stdout

    # ------------------------------------------------------------------
    # Committing
    # ------------------------------------------------------------------

    async def commit(
        self,
        repo_path: Path,
        message: str,
        files: list[str] | None = None,
    ) -> str:
        """Stage files and create a commit. Returns the new commit SHA.

        Parameters
        ----------
        files:
            Specific paths to stage. Defaults to ``git add .`` (all changes).
        """
        if files:
            await _run_git(["add", "--"] + files, repo_path)
        else:
            await _run_git(["add", "."], repo_path)

        # Check if there's anything to commit
        rc, stdout, _ = await _run_git(
            ["diff", "--cached", "--quiet"], repo_path, check=False
        )
        if rc == 0:
            logger.info("Nothing to commit in %s", repo_path)
            _, sha, _ = await _run_git(["rev-parse", "HEAD"], repo_path)
            return sha

        await _run_git(["commit", "-m", message], repo_path)
        _, sha, _ = await _run_git(["rev-parse", "HEAD"], repo_path)
        logger.info("Committed %s in %s: %s", sha[:8], repo_path, message)
        return sha

    # ------------------------------------------------------------------
    # Pushing
    # ------------------------------------------------------------------

    async def push(self, repo_path: Path, branch: str) -> None:
        """Push *branch* to origin, setting upstream if needed."""
        try:
            await _run_git(
                ["push", "--set-upstream", "origin", branch], repo_path
            )
            logger.info("Pushed %s to origin", branch)
        except RuntimeError as e:
            logger.error("Push failed: %s", e)
            raise

    # ------------------------------------------------------------------
    # Status / Info
    # ------------------------------------------------------------------

    async def get_status(self, repo_path: Path) -> dict[str, list[str]]:
        """Return a summary of working-tree status."""
        _, stdout, _ = await _run_git(
            ["status", "--porcelain"], repo_path, check=False
        )
        modified, added, deleted, untracked = [], [], [], []
        for line in stdout.splitlines():
            if not line:
                continue
            xy, filename = line[:2], line[3:].strip()
            if "M" in xy:
                modified.append(filename)
            elif "A" in xy or xy == "??":
                if xy == "??":
                    untracked.append(filename)
                else:
                    added.append(filename)
            elif "D" in xy:
                deleted.append(filename)
        return {
            "modified": modified,
            "added": added,
            "deleted": deleted,
            "untracked": untracked,
        }

    async def get_diff(self, repo_path: Path, staged: bool = True) -> str:
        """Return the current diff (staged or unstaged)."""
        args = ["diff"]
        if staged:
            args.append("--cached")
        _, stdout, _ = await _run_git(args, repo_path, check=False)
        return stdout
