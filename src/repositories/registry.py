"""Repository registry — loads repository definitions from config/repositories.yaml."""

from __future__ import annotations

import logging
import os
import pathlib
import re
from functools import lru_cache
from typing import Any

import yaml

from src.schemas.repository import InfraConfig, RepositoryConfig, SCMProvider, SharedService

logger = logging.getLogger(__name__)

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CONFIG_DIR = _PROJECT_ROOT / "config"

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand ``${VAR}`` placeholders in strings, lists, and dicts."""
    if isinstance(value, str):
        return _ENV_VAR_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    return value


def _load_repos_yaml() -> dict[str, Any]:
    path = _CONFIG_DIR / "repositories.yaml"
    with open(path) as fh:
        data = yaml.safe_load(fh)
    return _expand_env_vars(data) or {}


class RepoRegistry:
    """Loads repository definitions and provides lookup methods.

    Parameters
    ----------
    repos_config:
        Raw dict from ``config/repositories.yaml``. If *None*, loaded
        automatically.
    """

    def __init__(self, repos_config: dict[str, Any] | None = None) -> None:
        raw = repos_config or _load_repos_yaml()
        self._infra = InfraConfig(**raw.get("infra", {}))
        self._shared_services: list[SharedService] = [
            SharedService(**s) for s in raw.get("shared_services", [])
        ]
        self._repos: dict[str, RepositoryConfig] = {}
        for name, cfg in raw.get("repositories", {}).items():
            repo = RepositoryConfig(name=name, **cfg)
            self._repos[name] = repo

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def get(self, name: str) -> RepositoryConfig:
        """Return a specific repository by name, raising KeyError if missing."""
        return self._repos[name]

    def all(self) -> list[RepositoryConfig]:
        """Return all configured repositories."""
        return list(self._repos.values())

    def get_infra_config(self) -> InfraConfig:
        """Return infrastructure (local-infra) configuration."""
        return self._infra

    def get_shared_services(self) -> list[SharedService]:
        """Return shared service definitions (mysql, redis, etc.)."""
        return self._shared_services

    def get_shared_service(self, name: str) -> SharedService | None:
        """Return a shared service by name."""
        for svc in self._shared_services:
            if svc.name == name:
                return svc
        return None

    # ------------------------------------------------------------------
    # Lookups for routing
    # ------------------------------------------------------------------

    def find_by_label(self, label: str) -> list[RepositoryConfig]:
        """Return repos whose jira_labels contain *label* (case-insensitive)."""
        label_lower = label.lower()
        return [r for r in self._repos.values() if label_lower in [l.lower() for l in r.jira_labels]]

    def find_by_component(self, component: str) -> list[RepositoryConfig]:
        """Return repos whose jira_components contain *component* (case-insensitive)."""
        comp_lower = component.lower()
        return [
            r for r in self._repos.values()
            if comp_lower in [c.lower() for c in r.jira_components]
        ]

    def find_by_stack(self, stack: str) -> list[RepositoryConfig]:
        """Return repos that include *stack* in their tech_stacks."""
        stack_lower = stack.lower()
        return [r for r in self._repos.values() if stack_lower in r.tech_stacks]

    def find_by_scm(self, provider: SCMProvider) -> list[RepositoryConfig]:
        """Return repos using the given SCM provider."""
        return [r for r in self._repos.values() if r.scm == provider]

    def get_transitive_deps(self, repo_name: str) -> list[RepositoryConfig]:
        """Return all transitive repo dependencies in dependency order.

        Example: store-front depends on wallet-service which depends on pim.
        Returns [pim, wallet-service] for store-front.
        """
        seen: set[str] = set()
        result: list[RepositoryConfig] = []

        def _collect(name: str) -> None:
            if name in seen:
                return
            seen.add(name)
            try:
                repo = self._repos[name]
            except KeyError:
                logger.warning("Unknown repo dependency: %s", name)
                return
            for dep in repo.depends_on_repos:
                _collect(dep)
            result.append(repo)

        _collect(repo_name)
        # Remove self from result — only dependencies
        return [r for r in result if r.name != repo_name]


@lru_cache(maxsize=1)
def get_default_repo_registry() -> RepoRegistry:
    """Singleton RepoRegistry loaded from config/repositories.yaml."""
    return RepoRegistry()
