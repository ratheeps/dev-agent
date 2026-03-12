"""Technology stack auto-detection from Jira issues and repository file listings."""

from __future__ import annotations

import logging
import re

from src.schemas.skill import DetectionResult, TechStack

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Signal definitions
# ---------------------------------------------------------------------------

# Keywords searched in Jira issue text (title, description, labels, components)
JIRA_KEYWORDS: dict[TechStack, list[str]] = {
    TechStack.REACT: [
        "react", "reactjs", "react.js", "jsx", "react component", "react hook",
        "react native", "redux", "zustand", "react query",
    ],
    TechStack.NEXTJS: [
        "nextjs", "next.js", "next js", "app router", "pages router",
        "vercel", "ssr", "ssg", "isr", "server component", "client component",
    ],
    TechStack.TYPESCRIPT: [
        "typescript", "ts", "tsx", ".ts file", "type safety", "typed",
        "interface", "generic type", "tsconfig",
    ],
    TechStack.PHP: [
        "php", "composer", "psr", "phpunit", "phpstan", "symfony",
        "wordpress", "drupal",
    ],
    TechStack.LARAVEL: [
        "laravel", "eloquent", "artisan", "blade", "sanctum", "passport",
        "livewire", "inertia", "fortify", "sail",
    ],
    TechStack.PYTHON: [
        "python", "fastapi", "django", "flask", "pydantic", "pytest", "asyncio",
    ],
}

# File path/extension patterns that indicate a tech stack
# Each entry: (pattern_regex, stack, confidence_score)
REPO_PATTERNS: list[tuple[str, TechStack, float]] = [
    # React
    (r"\.jsx$", TechStack.REACT, 0.7),
    (r"\.tsx$", TechStack.REACT, 0.5),  # could also be TS-only, lower weight
    (r"react", TechStack.REACT, 0.3),
    (r"components/.*\.tsx?$", TechStack.REACT, 0.4),
    # Next.js (more specific than React — add React signal too)
    (r"next\.config\.(js|ts|mjs)$", TechStack.NEXTJS, 1.0),
    (r"^app/(layout|page|loading|error)\.(tsx|jsx)$", TechStack.NEXTJS, 0.9),
    (r"^pages/.*\.(tsx|jsx)$", TechStack.NEXTJS, 0.7),
    (r"\.next/", TechStack.NEXTJS, 0.8),
    # TypeScript
    (r"tsconfig\.json$", TechStack.TYPESCRIPT, 0.9),
    (r"tsconfig\.\w+\.json$", TechStack.TYPESCRIPT, 0.7),
    (r"\.ts$", TechStack.TYPESCRIPT, 0.3),
    (r"\.tsx$", TechStack.TYPESCRIPT, 0.4),
    (r"\.d\.ts$", TechStack.TYPESCRIPT, 0.8),
    # PHP
    (r"\.php$", TechStack.PHP, 0.5),
    (r"composer\.json$", TechStack.PHP, 0.9),
    (r"composer\.lock$", TechStack.PHP, 0.8),
    # Laravel
    (r"artisan$", TechStack.LARAVEL, 1.0),
    (r"^app/Http/Controllers/", TechStack.LARAVEL, 0.9),
    (r"^app/Models/", TechStack.LARAVEL, 0.8),
    (r"^database/migrations/", TechStack.LARAVEL, 0.9),
    (r"^resources/views/.*\.blade\.php$", TechStack.LARAVEL, 1.0),
    (r"^routes/(web|api)\.php$", TechStack.LARAVEL, 0.9),
    # Python
    (r"pyproject\.toml$", TechStack.PYTHON, 0.8),
    (r"requirements\.txt$", TechStack.PYTHON, 0.7),
    (r"setup\.py$", TechStack.PYTHON, 0.7),
    (r"\.py$", TechStack.PYTHON, 0.3),
]

# When Next.js is detected, also infer React (Next.js is a React framework)
IMPLIES: dict[TechStack, list[TechStack]] = {
    TechStack.NEXTJS: [TechStack.REACT],
    TechStack.LARAVEL: [TechStack.PHP],
}

# Maximum confidence score per signal source (cap at 1.0 after summing)
MAX_CONFIDENCE = 1.0


class SkillDetector:
    """Detects technology stacks from Jira issue data and repository file listings.

    Detection is purely heuristic (keyword matching + file patterns) and
    requires no LLM.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_from_jira(self, issue_data: dict[str, object]) -> DetectionResult:
        """Detect tech stacks from a Jira issue dict.

        Scans the issue summary, description, labels, and components for
        technology keywords.

        Parameters
        ----------
        issue_data:
            Raw Jira issue data (as returned by the Jira MCP ``getJiraIssue``
            tool or the Atlassian REST API).
        """
        text = self._extract_jira_text(issue_data).lower()
        confidence: dict[str, float] = {}
        signals: list[str] = []

        for stack, keywords in JIRA_KEYWORDS.items():
            for keyword in keywords:
                if re.search(r"\b" + re.escape(keyword) + r"\b", text):
                    score = confidence.get(stack.value, 0.0) + 0.4
                    confidence[stack.value] = min(MAX_CONFIDENCE, score)
                    signals.append(f"jira keyword '{keyword}' → {stack.value}")

        # Apply implication rules
        confidence, signals = self._apply_implications(confidence, signals)

        detected = [TechStack(s) for s, v in confidence.items() if v > 0]
        logger.debug(
            "SkillDetector.detect_from_jira: detected=%s confidence=%s",
            [d.value for d in detected],
            confidence,
        )
        return DetectionResult(
            detected_stacks=detected,
            confidence=confidence,
            signals=signals,
            source="jira",
        )

    def detect_from_repo(self, file_list: list[str]) -> DetectionResult:
        """Detect tech stacks from a list of repository file paths.

        Parameters
        ----------
        file_list:
            List of file paths relative to the repository root
            (e.g. ``["src/app/page.tsx", "next.config.ts", ...]``).
        """
        confidence: dict[str, float] = {}
        signals: list[str] = []
        pattern_cache: list[tuple[re.Pattern[str], TechStack, float]] = [
            (re.compile(pat, re.IGNORECASE), stack, score)
            for pat, stack, score in REPO_PATTERNS
        ]

        for file_path in file_list:
            for compiled, stack, score in pattern_cache:
                if compiled.search(file_path):
                    current = confidence.get(stack.value, 0.0)
                    # Use max not sum for file patterns to avoid over-counting
                    confidence[stack.value] = max(current, score)
                    signals.append(f"file '{file_path}' matches pattern → {stack.value}")

        confidence, signals = self._apply_implications(confidence, signals)

        detected = [TechStack(s) for s, v in confidence.items() if v > 0]
        logger.debug(
            "SkillDetector.detect_from_repo: detected=%s confidence=%s",
            [d.value for d in detected],
            confidence,
        )
        return DetectionResult(
            detected_stacks=detected,
            confidence=confidence,
            signals=signals,
            source="repo",
        )

    def merge_results(self, *results: DetectionResult) -> DetectionResult:
        """Merge multiple :class:`DetectionResult` objects into one.

        Confidences are combined additively and capped at 1.0.
        """
        if not results:
            return DetectionResult(source="merged")

        merged = results[0]
        for result in results[1:]:
            merged = merged.merge(result)

        merged = DetectionResult(
            detected_stacks=merged.detected_stacks,
            confidence={k: min(MAX_CONFIDENCE, v) for k, v in merged.confidence.items()},
            signals=merged.signals,
            source="merged",
        )
        return merged

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_jira_text(issue_data: dict[str, object]) -> str:
        """Flatten Jira issue data into a single string for keyword scanning."""
        parts: list[str] = []

        # Top-level fields
        for field in ("summary", "description", "key"):
            value = issue_data.get(field)
            if isinstance(value, str):
                parts.append(value)

        # Nested fields object
        fields = issue_data.get("fields", {})
        if isinstance(fields, dict):
            for field in ("summary", "description"):
                value = fields.get(field)
                if isinstance(value, str):
                    parts.append(value)

            # Labels (list of strings)
            labels = fields.get("labels", [])
            if isinstance(labels, list):
                parts.extend(str(lbl) for lbl in labels)

            # Components (list of dicts with 'name')
            components = fields.get("components", [])
            if isinstance(components, list):
                for comp in components:
                    if isinstance(comp, dict) and comp.get("name"):
                        parts.append(str(comp["name"]))

            # Custom fields that might contain tech keywords
            for key, value in fields.items():
                if key.startswith("customfield_") and isinstance(value, str):
                    parts.append(value)

        return " ".join(parts)

    @staticmethod
    def _apply_implications(
        confidence: dict[str, float],
        signals: list[str],
    ) -> tuple[dict[str, float], list[str]]:
        """Apply implication rules: if stack A is detected, also signal stack B."""
        new_signals = list(signals)
        for stack, implied_stacks in IMPLIES.items():
            if confidence.get(stack.value, 0.0) > 0:
                for implied in implied_stacks:
                    if implied.value not in confidence:
                        confidence[implied.value] = 0.5
                        new_signals.append(
                            f"{stack.value} implies {implied.value} (auto-added)"
                        )
        return confidence, new_signals
