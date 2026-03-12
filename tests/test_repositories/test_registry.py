"""Tests for RepoRegistry."""

from __future__ import annotations

import pytest
import yaml

from src.repositories.registry import RepoRegistry
from src.schemas.repository import SCMProvider

MINIMAL_YAML = """
infra:
  local_infra_path: /tmp/local-infra
  task_binary: task
  host_entries:
    - "127.0.0.1 wallet.giftbee.test"

shared_services:
  - name: mysql
    task_cmd: base:up
    port: 3306
  - name: redis
    task_cmd: base:up
    port: 6379

repositories:
  wallet-service:
    scm: bitbucket
    org: giftbee
    base_branch: dev
    tech_stacks: [php, laravel]
    jira_labels: [wallet, api]
    jira_components: [Wallet Service, API]
    local_path: /tmp/wallet-service
    dev_url: https://wallet.giftbee.test
    task_up: wallet-service:up
    task_down: wallet-service:down
    test_cmd: "docker compose exec wallet php artisan test"
    env_template: .env.example
    required_env_vars: [DB_HOST]
    depends_on_services: [mysql, redis]
    depends_on_repos: [pim]

  pim:
    scm: bitbucket
    org: giftbee
    base_branch: dev
    tech_stacks: [php]
    jira_labels: [pim, catalog]
    jira_components: [PIM]
    local_path: /tmp/pim
    dev_url: http://pim.giftbee.test
    task_up: pim:up
    task_down: pim:down
    test_cmd: "docker compose exec pim vendor/bin/codecept run"
    env_template: .env.example
    required_env_vars: []
    depends_on_services: [mysql]
    depends_on_repos: []

  store-front:
    scm: bitbucket
    org: giftbee
    base_branch: main
    tech_stacks: [nextjs, react, typescript]
    jira_labels: [storefront, frontend]
    jira_components: [Store Front]
    local_path: /tmp/store-front
    dev_url: https://myaccount.giftbee.test
    task_up: store-front:up
    task_down: store-front:down
    test_cmd: "docker compose exec store-front npm test"
    e2e_test_cmd: "docker compose exec store-front npm run test:e2e"
    e2e_test_dir: tests/e2e/specs
    e2e_page_objects_dir: tests/e2e/pages
    env_template: .env.example
    required_env_vars: [NEXT_APP_API_BASE_URL]
    depends_on_services: [mysql, nginx]
    depends_on_repos: [wallet-service]
"""


@pytest.fixture()
def registry() -> RepoRegistry:
    raw = yaml.safe_load(MINIMAL_YAML)
    return RepoRegistry(repos_config=raw)


class TestRepoRegistryBasics:
    def test_get_existing_repo(self, registry: RepoRegistry) -> None:
        repo = registry.get("wallet-service")
        assert repo.name == "wallet-service"
        assert repo.scm == SCMProvider.BITBUCKET

    def test_get_missing_repo_raises(self, registry: RepoRegistry) -> None:
        with pytest.raises(KeyError):
            registry.get("nonexistent")

    def test_all_returns_all_repos(self, registry: RepoRegistry) -> None:
        repos = registry.all()
        names = {r.name for r in repos}
        assert names == {"wallet-service", "pim", "store-front"}

    def test_infra_config(self, registry: RepoRegistry) -> None:
        infra = registry.get_infra_config()
        assert infra.task_binary == "task"
        assert len(infra.host_entries) == 1

    def test_shared_services(self, registry: RepoRegistry) -> None:
        services = registry.get_shared_services()
        names = {s.name for s in services}
        assert "mysql" in names
        assert "redis" in names

    def test_get_shared_service(self, registry: RepoRegistry) -> None:
        mysql = registry.get_shared_service("mysql")
        assert mysql is not None
        assert mysql.port == 3306

    def test_get_shared_service_missing(self, registry: RepoRegistry) -> None:
        assert registry.get_shared_service("nonexistent") is None


class TestRepoRegistryLookups:
    def test_find_by_label(self, registry: RepoRegistry) -> None:
        results = registry.find_by_label("wallet")
        assert len(results) == 1
        assert results[0].name == "wallet-service"

    def test_find_by_label_case_insensitive(self, registry: RepoRegistry) -> None:
        results = registry.find_by_label("WALLET")
        assert len(results) == 1

    def test_find_by_label_no_match(self, registry: RepoRegistry) -> None:
        results = registry.find_by_label("unknown_label")
        assert results == []

    def test_find_by_component(self, registry: RepoRegistry) -> None:
        results = registry.find_by_component("PIM")
        assert len(results) == 1
        assert results[0].name == "pim"

    def test_find_by_component_case_insensitive(self, registry: RepoRegistry) -> None:
        results = registry.find_by_component("store front")
        assert len(results) == 1

    def test_find_by_stack(self, registry: RepoRegistry) -> None:
        results = registry.find_by_stack("nextjs")
        assert len(results) == 1
        assert results[0].name == "store-front"

    def test_find_by_scm(self, registry: RepoRegistry) -> None:
        results = registry.find_by_scm(SCMProvider.BITBUCKET)
        assert len(results) == 3

    def test_find_by_stack_multiple(self, registry: RepoRegistry) -> None:
        results = registry.find_by_stack("php")
        names = {r.name for r in results}
        assert names == {"wallet-service", "pim"}


class TestRepoRegistryDependencies:
    def test_transitive_deps_single_level(self, registry: RepoRegistry) -> None:
        deps = registry.get_transitive_deps("wallet-service")
        dep_names = [r.name for r in deps]
        assert "pim" in dep_names
        assert "wallet-service" not in dep_names

    def test_transitive_deps_two_levels(self, registry: RepoRegistry) -> None:
        deps = registry.get_transitive_deps("store-front")
        dep_names = [r.name for r in deps]
        assert "pim" in dep_names
        assert "wallet-service" in dep_names
        assert "store-front" not in dep_names
        # pim must come before wallet-service
        assert dep_names.index("pim") < dep_names.index("wallet-service")

    def test_transitive_deps_no_deps(self, registry: RepoRegistry) -> None:
        deps = registry.get_transitive_deps("pim")
        assert deps == []


class TestRepositoryConfigProperties:
    def test_is_frontend(self, registry: RepoRegistry) -> None:
        store = registry.get("store-front")
        assert store.is_frontend is True
        wallet = registry.get("wallet-service")
        assert wallet.is_frontend is False

    def test_has_e2e(self, registry: RepoRegistry) -> None:
        store = registry.get("store-front")
        assert store.has_e2e is True
        wallet = registry.get("wallet-service")
        assert wallet.has_e2e is False
