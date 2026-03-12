"""Skill registry — loads skill definitions and provides access by tech stack."""

from __future__ import annotations

import logging
import pathlib
from functools import lru_cache
from typing import Any

import yaml

from src.schemas.skill import Skill, SkillSet, TechStack

logger = logging.getLogger(__name__)

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CONFIG_DIR = _PROJECT_ROOT / "config"
_PROMPTS_DIR = _PROJECT_ROOT / "src" / "prompts"


def _load_skills_yaml() -> dict[str, Any]:
    path = _CONFIG_DIR / "skills.yaml"
    with open(path) as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise TypeError(f"Expected dict from {path}, got {type(data).__name__}")
    return data


class SkillRegistry:
    """Loads skill definitions from ``config/skills.yaml`` and serves
    :class:`~src.schemas.skill.SkillSet` objects on request.

    Skill prompt files are loaded lazily and cached after first access.
    """

    def __init__(self, skills_config: dict[str, Any] | None = None) -> None:
        raw = skills_config or _load_skills_yaml()
        self._skills: dict[TechStack, Skill] = self._parse_skills(raw)
        self._prompt_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_skills(self, stacks: list[TechStack]) -> SkillSet:
        """Return a :class:`SkillSet` containing skills for all requested stacks.

        Unknown or unsupported stacks are silently skipped.
        """
        found: list[Skill] = []
        for stack in stacks:
            skill = self._skills.get(stack)
            if skill is not None:
                found.append(skill)
            else:
                logger.debug("SkillRegistry: no skill registered for %s", stack.value)

        primary = found[0].tech_stack if found else TechStack.UNKNOWN
        return SkillSet(skills=found, primary_stack=primary)

    def load_prompt(self, skill: Skill) -> str:
        """Load and cache the markdown prompt for *skill*."""
        if skill.prompt_file in self._prompt_cache:
            return self._prompt_cache[skill.prompt_file]

        prompt_path = _PROMPTS_DIR / skill.prompt_file
        if not prompt_path.exists():
            logger.warning(
                "SkillRegistry: prompt file not found: %s", prompt_path
            )
            return ""

        text = prompt_path.read_text(encoding="utf-8")
        self._prompt_cache[skill.prompt_file] = text
        return text

    @property
    def registered_stacks(self) -> list[TechStack]:
        return list(self._skills.keys())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_skills(raw: dict[str, Any]) -> dict[TechStack, Skill]:
        skills: dict[TechStack, Skill] = {}
        for name, cfg in raw.get("skills", {}).items():
            if not isinstance(cfg, dict):
                continue
            try:
                stack = TechStack(cfg.get("tech_stack", name))
                skill = Skill(
                    name=name,
                    tech_stack=stack,
                    description=cfg.get("description", ""),
                    prompt_file=cfg.get("prompt_file", f"skills/{name}.md"),
                    file_patterns=cfg.get("file_patterns", []),
                    keywords=cfg.get("keywords", []),
                )
                skills[stack] = skill
            except (ValueError, TypeError) as exc:
                logger.warning("SkillRegistry: skipping invalid skill '%s': %s", name, exc)
        return skills


@lru_cache(maxsize=1)
def get_default_registry() -> SkillRegistry:
    """Return a module-level singleton :class:`SkillRegistry`."""
    return SkillRegistry()
