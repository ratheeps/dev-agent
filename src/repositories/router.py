"""Repository router — maps Jira issues to target repositories.

Scoring strategy (additive confidence):
- Jira label exact match → +0.4 per match
- Jira component match   → +0.35 per match
- Description keyword    → +0.2 per match (capped at +0.4)
- Tech stack match       → +0.15 per match (capped at +0.3)
Repos with confidence > 0.3 are returned, sorted descending.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.repositories.registry import RepoRegistry, get_default_repo_registry
from src.schemas.repository import RepoRouteResult, RouteSignal

logger = logging.getLogger(__name__)


class RepoRouter:
    """Routes a Jira issue to one or more repositories.

    Parameters
    ----------
    registry:
        RepoRegistry to look up repo configs. Defaults to singleton.
    """

    _CONFIDENCE_THRESHOLD = 0.3

    def __init__(self, registry: RepoRegistry | None = None) -> None:
        self._registry = registry or get_default_repo_registry()

    def route(
        self,
        jira_issue: dict[str, Any],
        detected_stacks: list[str] | None = None,
    ) -> list[RepoRouteResult]:
        """Score all repos against the Jira issue and return matches.

        Parameters
        ----------
        jira_issue:
            Dict with keys: ``labels``, ``components``, ``summary``,
            ``description``.
        detected_stacks:
            Tech stacks already detected by SkillDetector (e.g. ``["nextjs"]``).

        Returns
        -------
        list[RepoRouteResult]
            Matched repos sorted by confidence desc. Empty if no match > threshold.
        """
        labels: list[str] = [l.lower() for l in jira_issue.get("labels", [])]
        components: list[str] = [c.lower() for c in jira_issue.get("components", [])]
        text = " ".join(filter(None, [
            jira_issue.get("summary", ""),
            jira_issue.get("description", ""),
        ])).lower()
        stacks = [s.lower() for s in (detected_stacks or [])]

        results: list[RepoRouteResult] = []

        for repo in self._registry.all():
            # Skip infra-only repos from automatic routing
            if repo.name == "local-infra":
                continue

            signals: list[RouteSignal] = []
            confidence = 0.0

            # Label matching (+0.4 each)
            for label in repo.jira_labels:
                if label.lower() in labels:
                    signals.append(RouteSignal(source="label", value=label, confidence=0.4))
                    confidence += 0.4

            # Component matching (+0.35 each)
            for comp in repo.jira_components:
                if comp.lower() in components:
                    signals.append(RouteSignal(source="component", value=comp, confidence=0.35))
                    confidence += 0.35

            # Description keyword matching (capped at +0.4 total)
            kw_boost = 0.0
            for label in repo.jira_labels:
                if label.lower() in text and kw_boost < 0.4:
                    boost = min(0.2, 0.4 - kw_boost)
                    signals.append(RouteSignal(source="keyword", value=label, confidence=boost))
                    kw_boost += boost
                    confidence += boost

            # Tech stack matching (capped at +0.3 total)
            stack_boost = 0.0
            for stack in repo.tech_stacks:
                if stack.lower() in stacks and stack_boost < 0.3:
                    boost = min(0.15, 0.3 - stack_boost)
                    signals.append(RouteSignal(source="stack", value=stack, confidence=boost))
                    stack_boost += boost
                    confidence += boost

            if confidence >= self._CONFIDENCE_THRESHOLD:
                results.append(
                    RepoRouteResult(
                        repo_name=repo.name,
                        confidence=round(min(confidence, 1.0), 3),
                        signals=signals,
                    )
                )

        results.sort(key=lambda r: r.confidence, reverse=True)
        logger.info(
            "Routed Jira issue to repos: %s",
            [(r.repo_name, r.confidence) for r in results],
        )
        return results

    def route_primary(
        self,
        jira_issue: dict[str, Any],
        detected_stacks: list[str] | None = None,
    ) -> str | None:
        """Return the single highest-confidence repo name, or None."""
        results = self.route(jira_issue, detected_stacks)
        return results[0].repo_name if results else None
