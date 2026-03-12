"""Skill prompt composer — injects technology skill content into agent system prompts."""

from __future__ import annotations

import logging

from src.schemas.skill import SkillSet, TechStack
from src.skills.registry import SkillRegistry, get_default_registry

logger = logging.getLogger(__name__)

_SKILLS_SECTION_HEADER = "\n\n---\n\n## Technology Skills\n\n"
_WORKER_CONTEXT_INTRO = (
    "You have been assigned a task requiring expertise in the following technologies. "
    "Apply the guidelines below for every piece of code you write or modify.\n\n"
)
_ORCHESTRATOR_CONTEXT_INTRO = (
    "The following technology stacks have been detected for this task. "
    "Factor these into your planning, subtask boundaries, and delegation decisions.\n\n"
)


class SkillComposer:
    """Composes technology skill guidelines into agent system prompts.

    For **workers**, the full skill prompt content is injected so the agent
    has complete coding guidelines at invocation time.

    For the **orchestrator**, a lighter summary is appended so it can make
    informed planning decisions (e.g. which files to target, how to split work)
    without inflating the prompt unnecessarily.
    """

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self._registry = registry or get_default_registry()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compose_worker_prompt(self, base_prompt: str, skill_set: SkillSet) -> str:
        """Return *base_prompt* enriched with full skill guidelines.

        Each detected skill's markdown prompt file is appended under a
        "Technology Skills" section, providing the worker with complete
        language/framework-specific coding guidelines.

        Parameters
        ----------
        base_prompt:
            The worker's base system prompt (from ``worker_system.md``).
        skill_set:
            Skills detected for the current task.
        """
        if skill_set.is_empty:
            return base_prompt

        sections: list[str] = [_WORKER_CONTEXT_INTRO]
        for skill in skill_set.skills:
            prompt_content = self._registry.load_prompt(skill)
            if prompt_content:
                sections.append(prompt_content)
                logger.debug(
                    "SkillComposer: injected worker skill '%s' (%d chars)",
                    skill.name,
                    len(prompt_content),
                )
            else:
                logger.warning(
                    "SkillComposer: no prompt content for skill '%s'", skill.name
                )

        if len(sections) == 1:  # Only intro, no actual content loaded
            return base_prompt

        return base_prompt + _SKILLS_SECTION_HEADER + "\n\n".join(sections)

    def compose_orchestrator_prompt(self, base_prompt: str, skill_set: SkillSet) -> str:
        """Return *base_prompt* with a lightweight skill context summary.

        Only the stack names and descriptions are appended — not the full
        coding guidelines — to keep the orchestrator prompt focused on planning.

        Parameters
        ----------
        base_prompt:
            The orchestrator's base system prompt (from ``orchestrator_system.md``).
        skill_set:
            Skills detected for the current task.
        """
        if skill_set.is_empty:
            return base_prompt

        lines: list[str] = [_ORCHESTRATOR_CONTEXT_INTRO]
        for skill in skill_set.skills:
            lines.append(f"- **{skill.tech_stack.value.title()}**: {skill.description}")

        lines.append(
            "\nEnsure subtasks are scoped to the appropriate technology boundaries "
            "and workers are given the relevant skill context when delegated."
        )

        return base_prompt + _SKILLS_SECTION_HEADER + "\n".join(lines)

    def compose_planning_context(self, skill_set: SkillSet) -> str:
        """Return a short skill context string for inclusion in planning prompts.

        Suitable for injecting into the per-ticket planning prompt sent to
        the orchestrator's ``think()`` call.
        """
        if skill_set.is_empty:
            return ""

        stack_names = ", ".join(s.tech_stack.value for s in skill_set.skills)
        descriptions = "\n".join(
            f"  - **{s.tech_stack.value}**: {s.description}" for s in skill_set.skills
        )
        return (
            f"\n**Detected Technology Stack**: {stack_names}\n"
            f"Apply these technology-specific constraints in your plan:\n{descriptions}\n"
        )

    # ------------------------------------------------------------------
    # Convenience factory
    # ------------------------------------------------------------------

    @staticmethod
    def build_skill_set_for_stacks(stacks: list[TechStack]) -> SkillSet:
        """Convenience method to build a SkillSet from a list of TechStack values."""
        return get_default_registry().get_skills(stacks)
