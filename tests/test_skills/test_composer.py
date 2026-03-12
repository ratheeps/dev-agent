"""Tests for the SkillComposer — prompt enrichment with technology skills."""

from __future__ import annotations

import pytest

from src.schemas.skill import Skill, SkillSet, TechStack
from src.skills.composer import SkillComposer
from src.skills.registry import SkillRegistry


def make_skill(stack: TechStack, name: str = "") -> Skill:
    return Skill(
        name=name or stack.value,
        tech_stack=stack,
        description=f"Expert {stack.value} development",
        prompt_file=f"skills/{stack.value}.md",
    )


def make_skill_set(*stacks: TechStack) -> SkillSet:
    skills = [make_skill(s) for s in stacks]
    primary = skills[0].tech_stack if skills else TechStack.UNKNOWN
    return SkillSet(skills=skills, primary_stack=primary)


@pytest.fixture()
def real_composer() -> SkillComposer:
    """Composer backed by the real registry (reads actual skill prompt files)."""
    return SkillComposer()


@pytest.fixture()
def mock_registry(tmp_path: pytest.TempPathFactory) -> SkillRegistry:
    """A registry backed by a minimal config that doesn't require real files."""
    cfg: dict = {
        "skills": {
            "react": {
                "tech_stack": "react",
                "description": "React expert",
                "prompt_file": "skills/react.md",
                "file_patterns": [],
                "keywords": [],
            },
            "typescript": {
                "tech_stack": "typescript",
                "description": "TypeScript expert",
                "prompt_file": "skills/typescript.md",
                "file_patterns": [],
                "keywords": [],
            },
        }
    }
    return SkillRegistry(skills_config=cfg)


class TestComposePlanningContext:
    def test_empty_skill_set_returns_empty_string(self) -> None:
        composer = SkillComposer()
        result = composer.compose_planning_context(SkillSet())
        assert result == ""

    def test_includes_stack_names(self) -> None:
        composer = SkillComposer()
        skill_set = make_skill_set(TechStack.REACT, TechStack.TYPESCRIPT)
        result = composer.compose_planning_context(skill_set)
        assert "react" in result
        assert "typescript" in result

    def test_includes_descriptions(self) -> None:
        composer = SkillComposer()
        skill_set = make_skill_set(TechStack.LARAVEL)
        result = composer.compose_planning_context(skill_set)
        assert "laravel" in result.lower()


class TestComposeOrchestratorPrompt:
    def test_empty_skill_set_returns_base_prompt(self) -> None:
        composer = SkillComposer()
        base = "You are an orchestrator."
        result = composer.compose_orchestrator_prompt(base, SkillSet())
        assert result == base

    def test_appends_technology_skills_section(self) -> None:
        composer = SkillComposer()
        base = "You are an orchestrator."
        skill_set = make_skill_set(TechStack.REACT)
        result = composer.compose_orchestrator_prompt(base, skill_set)
        assert "Technology Skills" in result
        assert base in result

    def test_lists_detected_stacks(self) -> None:
        composer = SkillComposer()
        base = "System prompt."
        skill_set = make_skill_set(TechStack.PHP, TechStack.LARAVEL)
        result = composer.compose_orchestrator_prompt(base, skill_set)
        assert "php" in result.lower() or "Php" in result
        assert "laravel" in result.lower() or "Laravel" in result

    def test_does_not_include_full_skill_content(self, mock_registry: SkillRegistry) -> None:
        """Orchestrator prompt should only have summary, not full skill docs."""
        composer = SkillComposer(mock_registry)
        base = "Orchestrator."
        skill_set = mock_registry.get_skills([TechStack.REACT])
        result = composer.compose_orchestrator_prompt(base, skill_set)
        # The orchestrator version should NOT load the full markdown content
        # (it only appends descriptions)
        assert "## Component Architecture" not in result  # react.md content


class TestComposeWorkerPrompt:
    def test_empty_skill_set_returns_base_prompt(self) -> None:
        composer = SkillComposer()
        base = "You are a worker."
        result = composer.compose_worker_prompt(base, SkillSet())
        assert result == base

    def test_appends_technology_skills_section(self, real_composer: SkillComposer) -> None:
        base = "Worker base prompt."
        skill_set = real_composer._registry.get_skills([TechStack.REACT])
        if skill_set.is_empty:
            pytest.skip("React skill not loaded in registry")
        result = real_composer.compose_worker_prompt(base, skill_set)
        assert "Technology Skills" in result
        assert base in result

    def test_includes_full_skill_content(self, real_composer: SkillComposer) -> None:
        """Worker prompt should include actual skill guidelines."""
        base = "Worker."
        skill_set = real_composer._registry.get_skills([TechStack.REACT])
        if skill_set.is_empty:
            pytest.skip("React skill not loaded")
        result = real_composer.compose_worker_prompt(base, skill_set)
        # react.md contains these sections
        assert "React" in result
        assert len(result) > len(base) + 100  # Significantly enriched

    def test_multiple_skills_all_included(self, real_composer: SkillComposer) -> None:
        base = "Worker."
        skill_set = real_composer._registry.get_skills(
            [TechStack.REACT, TechStack.TYPESCRIPT]
        )
        if len(skill_set.skills) < 2:
            pytest.skip("Not all skills loaded")
        result = real_composer.compose_worker_prompt(base, skill_set)
        assert "React" in result
        assert "TypeScript" in result

    def test_missing_prompt_file_skips_gracefully(self, mock_registry: SkillRegistry) -> None:
        """If a skill's prompt file doesn't exist, it's skipped without error."""
        composer = SkillComposer(mock_registry)
        base = "Worker."
        # mock_registry skills point to real files that exist
        # We test that the method doesn't raise even if a file is absent
        skill = Skill(
            name="missing",
            tech_stack=TechStack.PYTHON,
            description="Python",
            prompt_file="skills/nonexistent_xyz.md",
        )
        skill_set = SkillSet(skills=[skill], primary_stack=TechStack.PYTHON)
        # Should not raise; missing content is skipped
        result = composer.compose_worker_prompt(base, skill_set)
        assert base in result


class TestBuildSkillSetForStacks:
    def test_returns_skill_set(self) -> None:
        skill_set = SkillComposer.build_skill_set_for_stacks([TechStack.REACT])
        assert isinstance(skill_set, SkillSet)

    def test_unknown_stack_returns_empty(self) -> None:
        skill_set = SkillComposer.build_skill_set_for_stacks([TechStack.UNKNOWN])
        assert skill_set.is_empty
