"""Tests for the SkillDetector — tech stack auto-detection from Jira and repo data."""

from __future__ import annotations

import pytest

from src.schemas.skill import TechStack
from src.skills.detector import SkillDetector


@pytest.fixture()
def detector() -> SkillDetector:
    return SkillDetector()


class TestDetectFromJira:
    def test_detects_react_from_label(self, detector: SkillDetector) -> None:
        issue = {
            "fields": {
                "summary": "Build a new UI page",
                "description": "We need a React component for the dashboard",
                "labels": ["react", "frontend"],
            }
        }
        result = detector.detect_from_jira(issue)
        assert TechStack.REACT in result.detected_stacks

    def test_detects_laravel_from_description(self, detector: SkillDetector) -> None:
        issue = {
            "fields": {
                "summary": "Add API endpoint",
                "description": (  # noqa: E501
                    "Use Laravel Eloquent to create a new user endpoint with Artisan command"
                ),
                "labels": [],
            }
        }
        result = detector.detect_from_jira(issue)
        assert TechStack.LARAVEL in result.detected_stacks

    def test_laravel_implies_php(self, detector: SkillDetector) -> None:
        issue = {
            "fields": {
                "summary": "Laravel feature",
                "description": "Add a new Laravel controller",
                "labels": ["laravel"],
            }
        }
        result = detector.detect_from_jira(issue)
        assert TechStack.LARAVEL in result.detected_stacks
        assert TechStack.PHP in result.detected_stacks

    def test_detects_nextjs_from_summary(self, detector: SkillDetector) -> None:
        issue = {
            "fields": {
                "summary": "Migrate pages to Next.js App Router",
                "description": "Move to SSR with server components",
                "labels": [],
            }
        }
        result = detector.detect_from_jira(issue)
        assert TechStack.NEXTJS in result.detected_stacks

    def test_nextjs_implies_react(self, detector: SkillDetector) -> None:
        issue = {
            "fields": {
                "summary": "Next.js page",
                "description": "Create a new nextjs page",
                "labels": [],
            }
        }
        result = detector.detect_from_jira(issue)
        assert TechStack.NEXTJS in result.detected_stacks
        assert TechStack.REACT in result.detected_stacks

    def test_detects_typescript_keyword(self, detector: SkillDetector) -> None:
        issue = {
            "fields": {
                "summary": "Add TypeScript types",
                "description": "Convert the codebase to TypeScript with strict tsconfig",
                "labels": [],
            }
        }
        result = detector.detect_from_jira(issue)
        assert TechStack.TYPESCRIPT in result.detected_stacks

    def test_detects_php_from_label(self, detector: SkillDetector) -> None:
        issue = {
            "fields": {
                "summary": "Fix PHP service",
                "description": "Update the composer.json and refactor",
                "labels": ["php", "backend"],
            }
        }
        result = detector.detect_from_jira(issue)
        assert TechStack.PHP in result.detected_stacks

    def test_no_detection_on_empty(self, detector: SkillDetector) -> None:
        result = detector.detect_from_jira({})
        assert result.detected_stacks == []

    def test_confidence_above_zero_for_detected(self, detector: SkillDetector) -> None:
        issue = {"fields": {"summary": "react component", "description": "", "labels": []}}
        result = detector.detect_from_jira(issue)
        assert result.confidence.get(TechStack.REACT.value, 0) > 0

    def test_signals_populated(self, detector: SkillDetector) -> None:
        issue = {"fields": {"summary": "Build with React", "description": "", "labels": []}}
        result = detector.detect_from_jira(issue)
        assert len(result.signals) > 0
        assert result.source == "jira"


class TestDetectFromRepo:
    def test_detects_nextjs_from_config(self, detector: SkillDetector) -> None:
        files = ["next.config.ts", "app/layout.tsx", "app/page.tsx"]
        result = detector.detect_from_repo(files)
        assert TechStack.NEXTJS in result.detected_stacks

    def test_detects_typescript_from_tsconfig(self, detector: SkillDetector) -> None:
        files = ["tsconfig.json", "src/index.ts"]
        result = detector.detect_from_repo(files)
        assert TechStack.TYPESCRIPT in result.detected_stacks

    def test_detects_laravel_from_artisan(self, detector: SkillDetector) -> None:
        files = ["artisan", "app/Http/Controllers/UserController.php", "composer.json"]
        result = detector.detect_from_repo(files)
        assert TechStack.LARAVEL in result.detected_stacks

    def test_laravel_implies_php_in_repo(self, detector: SkillDetector) -> None:
        files = ["artisan", "routes/web.php"]
        result = detector.detect_from_repo(files)
        assert TechStack.LARAVEL in result.detected_stacks
        assert TechStack.PHP in result.detected_stacks

    def test_detects_react_jsx(self, detector: SkillDetector) -> None:
        files = ["src/components/Button.jsx", "src/App.jsx"]
        result = detector.detect_from_repo(files)
        assert TechStack.REACT in result.detected_stacks

    def test_detects_php_from_composer(self, detector: SkillDetector) -> None:
        files = ["composer.json", "src/Service.php"]
        result = detector.detect_from_repo(files)
        assert TechStack.PHP in result.detected_stacks

    def test_empty_file_list_yields_no_stacks(self, detector: SkillDetector) -> None:
        result = detector.detect_from_repo([])
        assert result.detected_stacks == []

    def test_source_is_repo(self, detector: SkillDetector) -> None:
        result = detector.detect_from_repo(["tsconfig.json"])
        assert result.source == "repo"

    def test_confidence_capped_at_one(self, detector: SkillDetector) -> None:
        # Many TypeScript signals should not push confidence above 1.0
        files = [
            "tsconfig.json", "tsconfig.base.json",
            "src/index.ts", "src/types.d.ts",
            "app/layout.tsx", "app/page.tsx",
        ]
        result = detector.detect_from_repo(files)
        for score in result.confidence.values():
            assert score <= 1.0


class TestMergeResults:
    def test_merge_combines_stacks(self, detector: SkillDetector) -> None:
        jira_result = detector.detect_from_jira(
            {"fields": {"summary": "React feature", "description": "", "labels": []}}
        )
        repo_result = detector.detect_from_repo(["tsconfig.json"])
        merged = detector.merge_results(jira_result, repo_result)
        assert TechStack.REACT in merged.detected_stacks
        assert TechStack.TYPESCRIPT in merged.detected_stacks
        assert merged.source == "merged"

    def test_merge_caps_confidence(self, detector: SkillDetector) -> None:
        issue = {
            "fields": {
                "summary": "laravel laravel laravel",
                "description": "laravel laravel artisan eloquent blade",
                "labels": ["laravel"],
            }
        }
        r1 = detector.detect_from_jira(issue)
        r2 = detector.detect_from_jira(issue)
        merged = detector.merge_results(r1, r2)
        for score in merged.confidence.values():
            assert score <= 1.0

    def test_merge_empty(self, detector: SkillDetector) -> None:
        merged = detector.merge_results()
        assert merged.detected_stacks == []
