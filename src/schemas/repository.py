"""Repository configuration schemas for multi-repo workflow."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class SCMProvider(str, Enum):
    BITBUCKET = "bitbucket"
    GITHUB = "github"


class SharedService(BaseModel):
    name: str
    task_cmd: str
    health_check: str | None = None
    port: int | None = None


class InfraConfig(BaseModel):
    local_infra_path: Path
    task_binary: str = "task"
    host_entries: list[str] = Field(default_factory=list)


class RepositoryConfig(BaseModel):
    name: str  # set by registry after loading
    scm: SCMProvider
    org: str
    base_branch: str
    tech_stacks: list[str] = Field(default_factory=list)
    jira_labels: list[str] = Field(default_factory=list)
    jira_components: list[str] = Field(default_factory=list)
    local_path: Path
    dev_url: str | None = None
    task_up: str | None = None
    task_down: str | None = None
    task_migrate: str | None = None
    test_cmd: str | None = None
    e2e_test_cmd: str | None = None
    e2e_test_dir: str | None = None
    e2e_page_objects_dir: str | None = None
    env_template: str = ".env.example"
    env_test_template: str | None = None
    required_env_vars: list[str] = Field(default_factory=list)
    depends_on_services: list[str] = Field(default_factory=list)
    depends_on_repos: list[str] = Field(default_factory=list)

    @property
    def is_frontend(self) -> bool:
        return any(s in self.tech_stacks for s in ["nextjs", "react"])

    @property
    def has_e2e(self) -> bool:
        return self.e2e_test_cmd is not None


class RouteSignal(BaseModel):
    source: str  # "label", "component", "keyword", "stack"
    value: str
    confidence: float


class RepoRouteResult(BaseModel):
    repo_name: str
    confidence: float
    signals: list[RouteSignal] = Field(default_factory=list)
