"""Opus orchestrator agent — plans work and delegates to Sonnet workers."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from src.agents.base import BaseAgent, load_prompt
from src.agents.bedrock_client import BedrockClient
from src.agents.claude_sdk_client import ClaudeSDKClient
from src.agents.communication import MessageBus
from src.agents.registry import AgentRegistry
from src.repositories.registry import RepoRegistry, get_default_repo_registry
from src.schemas.message import MessageType
from src.schemas.plan import AgentType, Plan, PlanStep
from src.schemas.skill import DetectionResult, SkillSet, TechStack
from src.schemas.task import SubTask, Task, TaskStatus
from src.skills.composer import SkillComposer
from src.skills.detector import SkillDetector
from src.skills.registry import get_default_registry

logger = logging.getLogger(__name__)

_ORCHESTRATOR_PROMPT_FILE = "orchestrator_system.md"


class Orchestrator(BaseAgent):
    """Lead architect agent backed by Claude Opus 4.6.

    Responsible for:
    1. Ingesting Jira tickets and linked context (Confluence, Figma).
    2. Breaking the ticket into an ordered implementation plan.
    3. Delegating subtasks to Sonnet worker agents.
    4. Monitoring progress and handling failures.
    5. Aggregating worker results into a final deliverable.
    """

    def __init__(
        self,
        *,
        registry: AgentRegistry,
        message_bus: MessageBus,
        agent_id: str | None = None,
        bedrock_client: BedrockClient | None = None,
        claude_sdk_client: ClaudeSDKClient | None = None,
        mcp_call: Any | None = None,
        repo_registry: RepoRegistry | None = None,
    ) -> None:
        system_prompt = load_prompt(_ORCHESTRATOR_PROMPT_FILE)
        super().__init__(
            agent_id=agent_id,
            model="claude-opus-4-6",
            role="orchestrator",
            system_prompt=system_prompt,
            bedrock_client=bedrock_client,
            claude_sdk_client=claude_sdk_client,
            mcp_call=mcp_call,
        )
        self._registry = registry
        self._message_bus = message_bus
        self._message_handler = message_bus
        self._registry.register_orchestrator(self.agent_id)
        self._worker_results: dict[str, dict[str, Any]] = {}
        self._skill_detector = SkillDetector()
        self._skill_composer = SkillComposer(get_default_registry())
        self._repo_registry = repo_registry or get_default_repo_registry()

    # ------------------------------------------------------------------
    # Primary workflow
    # ------------------------------------------------------------------

    async def run(self, task: Task | SubTask) -> dict[str, Any]:
        """End-to-end orchestration for a top-level *task*.

        1. Ingest external context.
        2. Plan the implementation.
        3. Delegate to workers.
        4. Monitor and collect results.
        5. Aggregate into a single output.
        """
        if not isinstance(task, Task):
            raise TypeError("Orchestrator.run() expects a Task, not a SubTask")

        task.mark_status(TaskStatus.PLANNING)
        logger.info("Orchestrator %s: starting task %s (%s)", self.agent_id, task.id, task.jira_key)

        # Step 1 — gather context
        context = await self.ingest_ticket(task.jira_key)
        task.context.update(context)

        # Step 2 — build plan
        plan = await self.create_plan(task)

        # Step 3+4 — delegate and monitor
        task.mark_status(TaskStatus.IN_PROGRESS)
        results = await self.delegate(plan, task)

        # Step 5 — aggregate
        task.mark_status(TaskStatus.REVIEW)
        aggregated = await self.aggregate_results(results, task)

        task.mark_status(TaskStatus.COMPLETED)
        logger.info("Orchestrator %s: task %s completed", self.agent_id, task.id)
        return aggregated

    # ------------------------------------------------------------------
    # 1. Context ingestion
    # ------------------------------------------------------------------

    async def ingest_ticket(self, jira_key: str) -> dict[str, Any]:
        """Fetch the Jira issue and any linked Confluence / Figma context."""
        context: dict[str, Any] = {}

        # Jira issue
        jira_result = await self.call_mcp_tool(
            server="atlassian",
            tool="getJiraIssue",
            args={"issueIdOrKey": jira_key},
        )
        context["jira_issue"] = jira_result.data

        # Linked Confluence pages (best-effort)
        confluence_result = await self.call_mcp_tool(
            server="atlassian",
            tool="search",
            args={"query": jira_key, "limit": 5},
        )
        context["confluence_pages"] = confluence_result.data

        # Figma designs (best-effort)
        figma_result = await self.call_mcp_tool(
            server="figma",
            tool="get_file",
            args={"query": jira_key},
        )
        context["figma_designs"] = figma_result.data

        # Detect tech stack from Jira issue data
        detection: DetectionResult = self._skill_detector.detect_from_jira(
            jira_result.data
        )
        if detection.detected_stacks:
            context["detected_skills"] = detection.to_dict()
            skill_set = get_default_registry().get_skills(detection.top_stacks())
            # Enrich the orchestrator's own system prompt with skill context
            self.system_prompt = self._skill_composer.compose_orchestrator_prompt(
                load_prompt(_ORCHESTRATOR_PROMPT_FILE), skill_set
            )
            logger.info(
                "Orchestrator %s: detected stacks=%s",
                self.agent_id,
                [s.value for s in detection.detected_stacks],
            )

        logger.info(
            "Orchestrator %s: ingested context for %s",
            self.agent_id,
            jira_key,
        )
        return context

    # ------------------------------------------------------------------
    # 2. Planning
    # ------------------------------------------------------------------

    async def create_plan(self, task: Task) -> Plan:
        """Produce an implementation plan for *task*.

        When a Bedrock client is configured, the orchestrator uses Claude
        Opus to analyze the ticket context and generate a structured plan.
        Falls back to converting existing subtasks if no LLM is available.
        """
        # If Bedrock is available, use LLM to generate the plan
        if self._bedrock is not None:
            return await self._create_plan_with_llm(task)

        # Fallback: convert existing subtasks to plan steps
        steps: list[PlanStep] = []
        for st in task.subtasks:
            steps.append(
                PlanStep(
                    id=st.id,
                    description=st.description or st.title,
                    file_paths=list(st.file_paths),
                    dependencies=list(st.dependencies),
                    agent_type=AgentType.WORKER,
                )
            )

        plan = Plan(
            task_id=task.id,
            subtasks=steps,
            estimated_complexity="medium",
            context_summary=f"Implementation plan for {task.jira_key}: {task.title}",
        )
        plan.build_dependency_graph()

        logger.info(
            "Orchestrator %s: plan created (fallback) — %d steps",
            self.agent_id,
            len(steps),
        )
        return plan

    async def _create_plan_with_llm(self, task: Task) -> Plan:
        """Use Claude Opus via Bedrock to generate an implementation plan."""
        # Build skill context for the planning prompt
        skill_context = ""
        detected_skills_data = task.context.get("detected_skills")
        if detected_skills_data and isinstance(detected_skills_data, dict):
            stacks = [
                TechStack(s)
                for s in detected_skills_data.get("detected_stacks", [])
                if s in [t.value for t in TechStack]
            ]
            if stacks:
                skill_set = get_default_registry().get_skills(stacks)
                skill_context = self._skill_composer.compose_planning_context(skill_set)

        # Build multi-repo context for the planning prompt
        target_repos = task.context.get("target_repositories", [])
        repo_context = ""
        if target_repos:
            repo_names = [r["repo"] if isinstance(r, dict) else r for r in target_repos]
            repo_context = (
                f"\n**Target Repositories:** {', '.join(repo_names)}\n"
                "Group subtasks by repository. Backend repos (wallet-service, pim) "
                "should precede frontend repos (store-front, admin-portal).\n"
            )

        planning_prompt = (
            f"Analyze this Jira ticket and create a structured implementation plan.\n\n"
            f"**Ticket:** {task.jira_key} — {task.title}\n"
            f"**Description:** {task.description}\n"
            f"**Context:** {json.dumps(task.context, default=str, indent=2)}\n"
            f"{skill_context}\n"
            f"{repo_context}\n"
            f"Respond with a JSON object containing:\n"
            f"- \"subtasks\": array of objects with: id, description, file_paths (array), "
            f"dependencies (array of subtask ids), complexity (low/medium/high), "
            f"repository (repo name this subtask belongs to)\n"
            f"- \"estimated_complexity\": overall complexity (low/medium/high)\n"
            f"- \"context_summary\": one-paragraph summary\n\n"
            f"Return ONLY valid JSON, no markdown fences."
        )

        result = await self.think(planning_prompt, max_tokens=8192)

        try:
            plan_data = json.loads(result.text)
        except json.JSONDecodeError:
            logger.warning(
                "Orchestrator %s: LLM returned invalid JSON for plan, using fallback",
                self.agent_id,
            )
            return await self.create_plan.__wrapped__(self, task)  # type: ignore[attr-defined, no-any-return]

        steps: list[PlanStep] = []
        for st_data in plan_data.get("subtasks", []):
            steps.append(
                PlanStep(
                    id=st_data.get("id", ""),
                    description=st_data.get("description", ""),
                    file_paths=st_data.get("file_paths", []),
                    dependencies=st_data.get("dependencies", []),
                    agent_type=AgentType.WORKER,
                )
            )

        plan = Plan(
            task_id=task.id,
            subtasks=steps,
            estimated_complexity=plan_data.get("estimated_complexity", "medium"),
            context_summary=plan_data.get("context_summary", ""),
        )
        plan.build_dependency_graph()

        logger.info(
            "Orchestrator %s: LLM plan created — %d steps, complexity=%s",
            self.agent_id,
            len(steps),
            plan.estimated_complexity,
        )
        return plan

    # ------------------------------------------------------------------
    # 3. Delegation
    # ------------------------------------------------------------------

    async def delegate(
        self,
        plan: Plan,
        task: Task,
    ) -> dict[str, dict[str, Any]]:
        """Spawn workers for each wave of the plan and collect results."""
        waves = plan.execution_order()
        all_results: dict[str, dict[str, Any]] = {}

        step_map = {step.id: step for step in plan.subtasks}

        # Resolve skill set from task context for worker enrichment
        skill_set: SkillSet | None = None
        detected_skills_data = task.context.get("detected_skills")
        if detected_skills_data and isinstance(detected_skills_data, dict):
            stacks = [
                TechStack(s)
                for s in detected_skills_data.get("detected_stacks", [])
                if s in [t.value for t in TechStack]
            ]
            if stacks:
                skill_set = get_default_registry().get_skills(stacks)

        for wave_idx, wave_ids in enumerate(waves):
            logger.info(
                "Orchestrator %s: executing wave %d/%d — %s",
                self.agent_id,
                wave_idx + 1,
                len(waves),
                wave_ids,
            )
            wave_tasks: list[asyncio.Task[dict[str, Any]]] = []
            worker_ids: list[str] = []

            for step_id in wave_ids:
                step = step_map[step_id]

                # Build a SubTask from the PlanStep
                subtask = self._step_to_subtask(step, task.id)
                task.subtasks.append(subtask)

                # Attach repo config to subtask context for worker dev loop
                step_repo = getattr(step, "repository", None) or task.context.get("repository", "")
                if step_repo:
                    try:
                        repo_cfg = self._repo_registry.get(step_repo)
                        subtask_context: dict[str, Any] = {
                            "repo_config": {
                                "name": repo_cfg.name,
                                "local_path": str(repo_cfg.local_path),
                                "dev_url": repo_cfg.dev_url,
                                "base_branch": repo_cfg.base_branch,
                                "tech_stacks": repo_cfg.tech_stacks,
                                "test_cmd": repo_cfg.test_cmd,
                                "e2e_test_cmd": repo_cfg.e2e_test_cmd,
                            },
                            "repository": step_repo,
                            "dev_url": repo_cfg.dev_url or "",
                        }
                        # Merge with task context
                        merged_context = {**task.context, **subtask_context}
                    except KeyError:
                        merged_context = task.context
                else:
                    merged_context = task.context

                worker = await self._registry.spawn_worker(subtask, skill_set=skill_set)
                worker_ids.append(worker.agent_id)

                # Send assignment message
                assignment = self.build_message(
                    to_agent=worker.agent_id,
                    message_type=MessageType.TASK_ASSIGNMENT,
                    payload={
                        "subtask": subtask.model_dump(mode="json"),
                        "context": merged_context,
                    },
                )
                await self.send_message(assignment)

                # Launch the worker
                async_task = asyncio.create_task(
                    self._run_worker_with_retry(worker, subtask)
                )
                wave_tasks.append(async_task)

            # Wait for the entire wave to finish
            wave_results = await asyncio.gather(*wave_tasks, return_exceptions=True)

            for wid, result in zip(worker_ids, wave_results):
                if isinstance(result, BaseException):
                    logger.error(
                        "Orchestrator %s: worker %s failed with %s",
                        self.agent_id,
                        wid,
                        result,
                    )
                    all_results[wid] = {"error": str(result)}
                else:
                    all_results[wid] = result

                await self._registry.remove_worker(wid)

        return all_results

    async def _run_worker_with_retry(
        self,
        worker: Any,
        subtask: SubTask,
    ) -> dict[str, Any]:
        """Execute a worker, retrying once on failure before escalating."""
        retry_limit: int = int(
            self._agents_config.get("worker", {}).get("retry_count", 1)
        )
        last_error: BaseException | None = None

        for attempt in range(1 + retry_limit):
            try:
                async with worker:
                    result: dict[str, Any] = await worker.run(subtask)
                    subtask.mark_status(TaskStatus.COMPLETED)
                    subtask.result = result
                    return result
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Orchestrator %s: worker attempt %d/%d failed — %s",
                    self.agent_id,
                    attempt + 1,
                    1 + retry_limit,
                    exc,
                )

        # All retries exhausted — escalate
        subtask.mark_status(TaskStatus.FAILED)
        escalation = self.build_message(
            to_agent="*",
            message_type=MessageType.ESCALATION,
            payload={
                "subtask_id": subtask.id,
                "error": str(last_error),
                "message": "Worker exhausted retries — human review required",
            },
        )
        await self.send_message(escalation)
        return {"error": str(last_error), "escalated": True}

    # ------------------------------------------------------------------
    # 4. Monitoring helpers
    # ------------------------------------------------------------------

    async def monitor(self, poll_interval: float = 2.0) -> None:
        """Poll the message bus for status updates from active workers.

        This is a convenience coroutine that can be run alongside
        :meth:`delegate` when more granular progress tracking is desired.
        """
        while self._registry.active_worker_count > 0:
            messages = await self._message_bus.get_messages(
                self.agent_id, timeout=poll_interval
            )
            for msg in messages:
                await self.receive_message(msg)
                if msg.message_type == MessageType.RESULT:
                    self._worker_results[msg.from_agent] = msg.payload
                elif msg.message_type == MessageType.ERROR:
                    logger.error(
                        "Orchestrator %s: error from %s — %s",
                        self.agent_id,
                        msg.from_agent,
                        msg.payload,
                    )

    # ------------------------------------------------------------------
    # 5. Result aggregation
    # ------------------------------------------------------------------

    async def aggregate_results(
        self,
        results: dict[str, dict[str, Any]],
        task: Task,
    ) -> dict[str, Any]:
        """Combine worker outputs into a summary suitable for PR creation."""
        changed_files: list[str] = []
        errors: list[dict[str, Any]] = []
        commits: list[str] = []

        for worker_id, result in results.items():
            if "error" in result:
                errors.append({"worker": worker_id, **result})
            else:
                changed_files.extend(result.get("changed_files", []))
                if result.get("commit_sha"):
                    commits.append(result["commit_sha"])

        return {
            "task_id": task.id,
            "jira_key": task.jira_key,
            "changed_files": sorted(set(changed_files)),
            "commits": commits,
            "errors": errors,
            "subtask_count": len(task.subtasks),
            "completed": task.completed_subtask_count,
            "progress_pct": task.progress_pct,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _step_to_subtask(step: PlanStep, parent_task_id: str) -> SubTask:
        """Convert a :class:`PlanStep` into a :class:`SubTask`."""
        return SubTask(
            id=step.id,
            parent_task_id=parent_task_id,
            title=step.description,
            description=step.description,
            file_paths=list(step.file_paths),
            dependencies=list(step.dependencies),
        )
