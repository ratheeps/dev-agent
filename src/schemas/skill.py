"""Pydantic models for technology skill detection and composition."""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, Field


class TechStack(str, enum.Enum):
    """Supported technology stacks for skill-aware code generation."""

    REACT = "react"
    NEXTJS = "nextjs"
    TYPESCRIPT = "typescript"
    PHP = "php"
    LARAVEL = "laravel"
    PYTHON = "python"
    UNKNOWN = "unknown"


class Skill(BaseModel):
    """A technology-specific coding skill that can be injected into agent prompts."""

    name: str
    tech_stack: TechStack
    description: str = ""
    prompt_file: str = Field(
        ...,
        description="Path to skill markdown file relative to src/prompts/",
    )
    file_patterns: list[str] = Field(
        default_factory=list,
        description="Glob patterns for files that indicate this skill (e.g. '*.tsx')",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Keywords found in Jira descriptions/labels that signal this skill",
    )


class SkillSet(BaseModel):
    """A collection of skills detected for a task."""

    skills: list[Skill] = Field(default_factory=list)
    primary_stack: TechStack = TechStack.UNKNOWN

    @property
    def stack_names(self) -> list[str]:
        return [s.tech_stack.value for s in self.skills]

    @property
    def is_empty(self) -> bool:
        return len(self.skills) == 0

    def has_stack(self, stack: TechStack) -> bool:
        return any(s.tech_stack == stack for s in self.skills)


class DetectionResult(BaseModel):
    """Result of tech stack detection from various signals."""

    detected_stacks: list[TechStack] = Field(default_factory=list)
    confidence: dict[str, float] = Field(
        default_factory=dict,
        description="Confidence score per stack (0.0 – 1.0)",
    )
    signals: list[str] = Field(
        default_factory=list,
        description="Human-readable descriptions of signals that triggered detection",
    )
    source: str = Field(
        default="unknown",
        description="Origin of this detection: 'jira' | 'repo' | 'merged'",
    )

    def top_stacks(self, min_confidence: float = 0.3) -> list[TechStack]:
        """Return stacks above the confidence threshold, sorted by score."""
        return [
            TechStack(stack)
            for stack, score in sorted(self.confidence.items(), key=lambda x: x[1], reverse=True)
            if score >= min_confidence
        ]

    def merge(self, other: DetectionResult) -> DetectionResult:
        """Merge another detection result into this one, combining confidences."""
        combined: dict[str, float] = dict(self.confidence)
        for stack, score in other.confidence.items():
            combined[stack] = min(1.0, combined.get(stack, 0.0) + score)

        all_stacks = list({TechStack(s) for s in combined if combined[s] > 0})
        all_signals = list({*self.signals, *other.signals})

        return DetectionResult(
            detected_stacks=all_stacks,
            confidence=combined,
            signals=all_signals,
            source="merged",
        )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
