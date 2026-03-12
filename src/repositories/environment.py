"""Dev environment manager — starts/stops Docker services via local-infra Taskfile.

Wraps `task` CLI commands to manage the full Docker stack for a target
repository. Handles transitive dependency resolution:
  store-front → wallet-service → pim → mysql, redis
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from typing import Any

from src.repositories.registry import RepoRegistry
from src.schemas.repository import InfraConfig, RepositoryConfig, SharedService

logger = logging.getLogger(__name__)

_HEALTH_CHECK_RETRIES = 10
_HEALTH_CHECK_INTERVAL = 3.0  # seconds


async def _run_cmd(
    args: list[str],
    cwd: Any,  # Path
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run a subprocess command, returning (returncode, stdout, stderr)."""
    import os
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    logger.debug("$ %s (cwd=%s)", shlex.join(args), cwd)
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=merged_env,
    )
    stdout_b, stderr_b = await proc.communicate()
    stdout = stdout_b.decode().strip()
    stderr = stderr_b.decode().strip()
    rc = proc.returncode or 0
    if check and rc != 0:
        raise RuntimeError(
            f"Command {shlex.join(args)} failed (rc={rc}): {stderr or stdout}"
        )
    return rc, stdout, stderr


class DevEnvironmentManager:
    """Manages Docker dev environment for GiftBee repositories.

    Uses the ``task`` CLI (Taskfile) from local-infra to start/stop services.

    Parameters
    ----------
    infra_config:
        InfraConfig with local_infra_path and task_binary.
    shared_services:
        List of SharedService definitions (mysql, redis, etc.).
    registry:
        RepoRegistry for dependency resolution.
    """

    def __init__(
        self,
        infra_config: InfraConfig,
        shared_services: list[SharedService],
        registry: RepoRegistry,
    ) -> None:
        self._infra = infra_config
        self._shared_services = {s.name: s for s in shared_services}
        self._registry = registry
        self._task = infra_config.task_binary

    # ------------------------------------------------------------------
    # Service lifecycle
    # ------------------------------------------------------------------

    async def start_services(self, repo: RepositoryConfig) -> None:
        """Start all services required for *repo* (including deps).

        Order:
        1. Shared base services (mysql, redis, nginx, mailpit)
        2. Dependent repos (e.g. pim before wallet-service)
        3. Target repo itself
        """
        logger.info("Starting services for %s", repo.name)

        # Step 1: Base shared services
        await self._run_task("base:up")

        # Step 2: Dependent repos in dependency order
        deps = self._registry.get_transitive_deps(repo.name)
        for dep_repo in deps:
            if dep_repo.task_up:
                await self._run_task(dep_repo.task_up)
                logger.info("Started dep service: %s", dep_repo.name)

        # Step 3: Target repo
        if repo.task_up:
            await self._run_task(repo.task_up)
            logger.info("Started target service: %s", repo.name)

        # Step 4: Health checks
        await self._wait_healthy()

    async def stop_services(self, repo: RepositoryConfig) -> None:
        """Stop services for *repo* (reverse dependency order)."""
        logger.info("Stopping services for %s", repo.name)

        if repo.task_down:
            await self._run_task(repo.task_down, check=False)

        deps = list(reversed(self._registry.get_transitive_deps(repo.name)))
        for dep_repo in deps:
            if dep_repo.task_down:
                await self._run_task(dep_repo.task_down, check=False)

    async def run_migrations(self, repo: RepositoryConfig) -> None:
        """Run database migrations for *repo* if a migrate task is configured."""
        if repo.task_migrate:
            logger.info("Running migrations for %s", repo.name)
            await self._run_task(repo.task_migrate)
        else:
            logger.debug("No migration task for %s", repo.name)

    # ------------------------------------------------------------------
    # Testing
    # ------------------------------------------------------------------

    async def run_tests(self, repo: RepositoryConfig) -> dict[str, Any]:
        """Execute the repo's unit/integration test suite.

        Returns a dict with keys: success, output, returncode.
        """
        if not repo.test_cmd:
            logger.warning("No test_cmd configured for %s", repo.name)
            return {"success": True, "output": "No test_cmd configured", "returncode": 0}

        logger.info("Running tests for %s: %s", repo.name, repo.test_cmd)
        args = shlex.split(repo.test_cmd)
        rc, stdout, stderr = await _run_cmd(
            args,
            cwd=self._infra.local_infra_path,
            check=False,
        )
        output = stdout or stderr
        success = rc == 0
        if success:
            logger.info("Tests passed for %s", repo.name)
        else:
            logger.error("Tests FAILED for %s (rc=%d): %s", repo.name, rc, output)
        return {"success": success, "output": output, "returncode": rc}

    async def run_e2e_tests(
        self,
        repo: RepositoryConfig,
        grep: str | None = None,
    ) -> dict[str, Any]:
        """Execute the repo's e2e Playwright test suite.

        Parameters
        ----------
        grep:
            Optional test filter pattern passed to playwright ``--grep``.
        """
        if not repo.e2e_test_cmd:
            logger.warning("No e2e_test_cmd configured for %s", repo.name)
            return {"success": True, "output": "No e2e tests configured", "returncode": 0}

        cmd = repo.e2e_test_cmd
        if grep:
            cmd = f"{cmd} -- --grep {shlex.quote(grep)}"

        logger.info("Running e2e tests for %s: %s", repo.name, cmd)
        args = shlex.split(cmd)
        rc, stdout, stderr = await _run_cmd(
            args,
            cwd=self._infra.local_infra_path,
            check=False,
        )
        output = stdout or stderr
        success = rc == 0
        if success:
            logger.info("E2E tests passed for %s", repo.name)
        else:
            logger.error("E2E tests FAILED for %s (rc=%d):\n%s", repo.name, rc, output)
        return {"success": success, "output": output, "returncode": rc}

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    async def check_health(self, service: SharedService) -> bool:
        """Run the health check command for *service*. Returns True if healthy."""
        if not service.health_check:
            return True
        args = shlex.split(service.health_check)
        rc, _, _ = await _run_cmd(
            args,
            cwd=self._infra.local_infra_path,
            check=False,
        )
        return rc == 0

    async def _wait_healthy(self) -> None:
        """Poll health checks until all services with checks are healthy."""
        services_with_checks = [s for s in self._shared_services.values() if s.health_check]
        if not services_with_checks:
            await asyncio.sleep(2)  # brief pause even if no explicit checks
            return

        for attempt in range(_HEALTH_CHECK_RETRIES):
            results = await asyncio.gather(
                *[self.check_health(s) for s in services_with_checks],
                return_exceptions=True,
            )
            all_healthy = all(r is True for r in results)
            if all_healthy:
                logger.info("All services healthy after %d checks", attempt + 1)
                return
            logger.debug(
                "Health check attempt %d/%d — waiting...", attempt + 1, _HEALTH_CHECK_RETRIES
            )
            await asyncio.sleep(_HEALTH_CHECK_INTERVAL)

        logger.warning("Services may not be fully healthy after %d attempts", _HEALTH_CHECK_RETRIES)

    async def get_running_services(self) -> list[str]:
        """Return names of currently running Docker containers."""
        rc, stdout, _ = await _run_cmd(
            ["docker", "compose", "ps", "--format", "{{.Name}}"],
            cwd=self._infra.local_infra_path,
            check=False,
        )
        if rc != 0 or not stdout:
            return []
        return [line.strip() for line in stdout.splitlines() if line.strip()]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_task(self, task_name: str, *, check: bool = True) -> tuple[int, str, str]:
        """Run `task <task_name>` from local_infra_path."""
        return await _run_cmd(
            [self._task, task_name],
            cwd=self._infra.local_infra_path,
            check=check,
        )
