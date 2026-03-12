""".env file manager for GiftBee repositories.

Ensures .env files exist, validates required vars, and creates test env
files from templates. NEVER commits .env files (all are in .gitignore).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from src.schemas.repository import InfraConfig, RepositoryConfig

logger = logging.getLogger(__name__)


def _read_env(path: Path) -> dict[str, str]:
    """Parse a .env file, returning a dict of key→value pairs."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _write_env(path: Path, updates: dict[str, str]) -> None:
    """Update specific keys in an existing .env file (or create it)."""
    existing_lines: list[str] = []
    if path.exists():
        existing_lines = path.read_text().splitlines()

    updated_keys: set[str] = set()
    new_lines: list[str] = []

    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key, _, _ = stripped.partition("=")
        key = key.strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            updated_keys.add(key)
        else:
            new_lines.append(line)

    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    path.write_text("\n".join(new_lines) + "\n")


class EnvFileManager:
    """Manages .env files across GiftBee repositories.

    Parameters
    ----------
    infra_config:
        InfraConfig with local_infra_path.
    """

    def __init__(self, infra_config: InfraConfig) -> None:
        self._infra = infra_config

    # ------------------------------------------------------------------
    # Dev env setup
    # ------------------------------------------------------------------

    def ensure_env(self, repo: RepositoryConfig) -> list[str]:
        """Ensure .env exists for *repo* and validate required vars.

        Returns a list of validation warnings (empty if all good).
        """
        repo_path = repo.local_path
        env_path = repo_path / ".env"
        template_path = repo_path / repo.env_template

        if not env_path.exists():
            if template_path.exists():
                shutil.copy(template_path, env_path)
                logger.info("Copied %s → %s", template_path, env_path)
            else:
                logger.warning("No .env or template found in %s", repo_path)
                return [f"Missing .env and template {repo.env_template} in {repo_path}"]

        return self.validate_env(repo)

    def ensure_test_env(self, repo: RepositoryConfig) -> list[str]:
        """Ensure test .env exists for e2e testing.

        Copies env_test_template → .env.test (or .env.testing) if missing.
        Sets TEST_BASE_URL to repo's dev_url for local testing.
        Returns validation warnings.
        """
        if not repo.env_test_template:
            return []

        repo_path = repo.local_path
        template_path = repo_path / repo.env_test_template

        # Determine test env file name
        if repo.env_test_template.endswith(".example"):
            target_name = repo.env_test_template.replace(".example", "")
        else:
            target_name = repo.env_test_template
        target_path = repo_path / target_name

        if not target_path.exists():
            if template_path.exists():
                shutil.copy(template_path, target_path)
                logger.info("Copied %s → %s", template_path, target_path)
            else:
                logger.warning("No test env template found: %s", template_path)
                return [f"Missing test env template: {template_path}"]

        # Update TEST_BASE_URL to point at local dev URL
        if repo.dev_url:
            current = _read_env(target_path)
            if current.get("TEST_BASE_URL", "") != repo.dev_url:
                _write_env(target_path, {"TEST_BASE_URL": repo.dev_url})
                logger.info("Set TEST_BASE_URL=%s in %s", repo.dev_url, target_path)

        return []

    def ensure_infra_env(self, repos: dict[str, RepositoryConfig]) -> list[str]:
        """Ensure local-infra/.env is correct with repo paths.

        Validates WALLET_SERVICE_DIR, STORE_FRONT_DIR, ADMIN_PORTAL, PIM_DIR
        match the actual filesystem paths from repositories.yaml.
        Returns a list of warnings.
        """
        infra_path = self._infra.local_infra_path
        env_path = infra_path / ".env"
        template_path = infra_path / ".env.example"

        if not env_path.exists():
            if template_path.exists():
                shutil.copy(template_path, env_path)
                logger.info("Copied local-infra .env.example → .env")
            else:
                return ["Missing local-infra/.env and .env.example"]

        # Map from env var name → repo name
        path_var_map = {
            "WALLET_SERVICE_DIR": "wallet-service",
            "STORE_FRONT_DIR": "store-front",
            "ADMIN_PORTAL": "admin-portal",
            "PIM_DIR": "pim",
        }

        current_env = _read_env(env_path)
        updates: dict[str, str] = {}
        warnings: list[str] = []

        for var, repo_name in path_var_map.items():
            if repo_name not in repos:
                continue
            expected = str(repos[repo_name].local_path)
            actual = current_env.get(var, "")
            if actual != expected:
                updates[var] = expected
                warnings.append(f"Updated {var}: {actual!r} → {expected!r}")

        if updates:
            # Backup original
            backup = env_path.with_suffix(".env.bak")
            shutil.copy(env_path, backup)
            logger.info("Backed up %s → %s", env_path, backup)
            _write_env(env_path, updates)
            logger.info("Updated local-infra/.env with %d path corrections", len(updates))

        return warnings

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_env(self, repo: RepositoryConfig) -> list[str]:
        """Check that all required_env_vars are set in the repo's .env.

        Returns a list of issues (empty if all good).
        """
        env_path = repo.local_path / ".env"
        if not env_path.exists():
            return [f"Missing .env in {repo.local_path}"]

        env_vars = _read_env(env_path)
        issues: list[str] = []
        for var in repo.required_env_vars:
            value = env_vars.get(var, "")
            if not value or value in {"changeme", "your_value_here", ""}:
                issues.append(f"{repo.name}/.env: {var} is not set or is a placeholder")

        if issues:
            logger.warning("Env validation issues for %s: %s", repo.name, issues)
        else:
            logger.debug("Env validation passed for %s", repo.name)
        return issues

    def get_env_summary(self, repo: RepositoryConfig) -> dict[str, Any]:
        """Return a non-secret summary of the repo's env state."""
        env_path = repo.local_path / ".env"
        exists = env_path.exists()
        issues = self.validate_env(repo) if exists else [".env missing"]
        return {
            "repo": repo.name,
            "env_exists": exists,
            "issues": issues,
            "valid": len(issues) == 0,
        }
