"""Tests for RepoRouter."""

from __future__ import annotations

import pytest
import yaml

from src.repositories.registry import RepoRegistry
from src.repositories.router import RepoRouter

ROUTER_YAML = """
infra:
  local_infra_path: /tmp/local-infra
  task_binary: task
  host_entries: []

shared_services: []

repositories:
  wallet-service:
    scm: bitbucket
    org: giftbee
    base_branch: dev
    tech_stacks: [php, laravel]
    jira_labels: [wallet, api, backend]
    jira_components: [Wallet Service, API, Backend]
    local_path: /tmp/wallet-service
    dev_url: https://wallet.giftbee.test
    env_template: .env.example
    required_env_vars: []
    depends_on_services: [mysql]
    depends_on_repos: [pim]

  store-front:
    scm: bitbucket
    org: giftbee
    base_branch: main
    tech_stacks: [nextjs, react, typescript]
    jira_labels: [storefront, store-front, frontend, customer]
    jira_components: [Store Front, Customer Portal]
    local_path: /tmp/store-front
    env_template: .env.example
    required_env_vars: []
    depends_on_services: [nginx]
    depends_on_repos: [wallet-service]

  admin-portal:
    scm: bitbucket
    org: giftbee
    base_branch: dev
    tech_stacks: [nextjs, react, typescript]
    jira_labels: [admin, corporate, backoffice]
    jira_components: [Admin Portal, Corporate Portal]
    local_path: /tmp/admin-portal
    env_template: .env.example
    required_env_vars: []
    depends_on_services: [nginx]
    depends_on_repos: [wallet-service]

  pim:
    scm: bitbucket
    org: giftbee
    base_branch: dev
    tech_stacks: [php]
    jira_labels: [pim, catalog, pimcore]
    jira_components: [PIM, Product Catalog]
    local_path: /tmp/pim
    env_template: .env.example
    required_env_vars: []
    depends_on_services: [mysql]
    depends_on_repos: []

  local-infra:
    scm: bitbucket
    org: giftbee
    base_branch: dev
    tech_stacks: []
    jira_labels: [infra]
    jira_components: [Infrastructure]
    local_path: /tmp/local-infra
    env_template: .env.example
    required_env_vars: []
    depends_on_services: []
    depends_on_repos: []
"""


@pytest.fixture()
def router() -> RepoRouter:
    raw = yaml.safe_load(ROUTER_YAML)
    registry = RepoRegistry(repos_config=raw)
    return RepoRouter(registry=registry)


class TestRepoRouterByLabel:
    def test_matches_wallet_label(self, router: RepoRouter) -> None:
        issue = {"labels": ["wallet"], "components": [], "summary": "", "description": ""}
        results = router.route(issue)
        assert any(r.repo_name == "wallet-service" for r in results)

    def test_matches_storefront_label(self, router: RepoRouter) -> None:
        issue = {"labels": ["storefront"], "components": [], "summary": "", "description": ""}
        results = router.route(issue)
        assert any(r.repo_name == "store-front" for r in results)

    def test_higher_confidence_for_better_match(self, router: RepoRouter) -> None:
        issue = {
            "labels": ["wallet", "api"],
            "components": ["Wallet Service"],
            "summary": "wallet",
            "description": "",
        }
        results = router.route(issue)
        wallet = next(r for r in results if r.repo_name == "wallet-service")
        assert wallet.confidence >= 0.7


class TestRepoRouterByComponent:
    def test_matches_component(self, router: RepoRouter) -> None:
        issue = {"labels": [], "components": ["Store Front"], "summary": "", "description": ""}
        results = router.route(issue)
        assert any(r.repo_name == "store-front" for r in results)

    def test_matches_admin_component(self, router: RepoRouter) -> None:
        issue = {"labels": [], "components": ["Admin Portal"], "summary": "", "description": ""}
        results = router.route(issue)
        assert any(r.repo_name == "admin-portal" for r in results)


class TestRepoRouterByStack:
    def test_matches_laravel_stack(self, router: RepoRouter) -> None:
        issue = {"labels": [], "components": [], "summary": "", "description": ""}
        results = router.route(issue, detected_stacks=["laravel", "php"])
        assert any(r.repo_name == "wallet-service" for r in results)

    def test_matches_nextjs_stack(self, router: RepoRouter) -> None:
        issue = {"labels": [], "components": [], "summary": "", "description": ""}
        results = router.route(issue, detected_stacks=["nextjs", "react"])
        # Both store-front and admin-portal match nextjs
        names = {r.repo_name for r in results}
        assert "store-front" in names or "admin-portal" in names


class TestRepoRouterOrdering:
    def test_sorted_by_confidence_descending(self, router: RepoRouter) -> None:
        issue = {
            "labels": ["wallet", "api"],
            "components": ["API"],
            "summary": "wallet api",
            "description": "",
        }
        results = router.route(issue)
        confidences = [r.confidence for r in results]
        assert confidences == sorted(confidences, reverse=True)

    def test_infra_not_routed(self, router: RepoRouter) -> None:
        issue = {
            "labels": ["infra"],
            "components": ["Infrastructure"],
            "summary": "infra",
            "description": "",
        }
        results = router.route(issue)
        names = [r.repo_name for r in results]
        assert "local-infra" not in names

    def test_threshold_filters_weak_matches(self, router: RepoRouter) -> None:
        issue = {"labels": [], "components": [], "summary": "generic task", "description": ""}
        results = router.route(issue)
        for r in results:
            assert r.confidence >= router._CONFIDENCE_THRESHOLD


class TestRepoRouterPrimary:
    def test_route_primary_returns_best(self, router: RepoRouter) -> None:
        issue = {
            "labels": ["wallet"],
            "components": ["Wallet Service"],
            "summary": "",
            "description": "",
        }
        primary = router.route_primary(issue)
        assert primary == "wallet-service"

    def test_route_primary_no_match_returns_none(self, router: RepoRouter) -> None:
        issue = {"labels": [], "components": [], "summary": "xyz", "description": ""}
        primary = router.route_primary(issue)
        assert primary is None
