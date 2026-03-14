"""AgentCore Runtime entrypoint.

This module is the main entry point when the agent system is deployed
on AWS Bedrock AgentCore Runtime or as an ECS worker. It initializes
the agent infrastructure, connects to DynamoDB memory, and processes
tasks from SQS.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from typing import Any

import boto3

from src.agents.bedrock_client import BedrockClient
from src.agents.claude_sdk_client import ClaudeSDKClient
from src.agents.communication import MessageBus
from src.agents.orchestrator import Orchestrator
from src.agents.registry import AgentRegistry
from src.integrations.mcp_manager import MCPManager
from src.memory.client import MemoryClient
from src.memory.config import MemoryConfig
from src.repositories.env_manager import EnvFileManager
from src.repositories.environment import DevEnvironmentManager
from src.repositories.hosts import HostManager
from src.repositories.registry import RepoRegistry, get_default_repo_registry
from src.repositories.workspace import WorkspaceManager
from src.workflows.pipeline import WorkflowPipeline

logger = logging.getLogger(__name__)


class AgentCoreEntrypoint:
    """Main entrypoint for Bedrock AgentCore Runtime deployment.

    Manages the lifecycle of the orchestrator, worker pool, and all
    supporting infrastructure (Bedrock client, MCP connections, memory,
    message bus).
    """

    def __init__(self) -> None:
        self._bedrock_client: BedrockClient | None = None
        self._claude_sdk_client: ClaudeSDKClient | None = None
        self._mcp_manager: MCPManager | None = None
        self._memory_client: MemoryClient | None = None
        self._message_bus: MessageBus | None = None
        self._registry: AgentRegistry | None = None
        self._orchestrator: Orchestrator | None = None
        self._shutdown_event = asyncio.Event()
        # Repository infrastructure
        self._repo_registry: RepoRegistry | None = None
        self._workspace_manager: WorkspaceManager | None = None
        self._dev_env_manager: DevEnvironmentManager | None = None
        self._host_manager: HostManager | None = None
        self._env_file_manager: EnvFileManager | None = None

    async def initialize(self, mcp_call: Any = None) -> None:
        """Set up all components.

        Parameters
        ----------
        mcp_call:
            Optional MCP tool invocation callable. If not provided, MCP
            tools will use stub responses.
        """
        logger.info("Initializing AgentCore entrypoint")

        region = os.environ.get("AWS_REGION", "us-east-1")

        # Load backend preference from config
        import pathlib as _pathlib  # noqa: PLC0415

        import yaml as _yaml  # noqa: PLC0415
        _cfg_path = _pathlib.Path(__file__).resolve().parents[2] / "config" / "agents.yaml"
        _agents_cfg: dict[str, Any] = _yaml.safe_load(_cfg_path.read_text()) or {}
        backend: str = _agents_cfg.get("backend", "bedrock")

        # Initialize the appropriate LLM backend(s)
        if backend in ("bedrock", "both"):
            self._bedrock_client = BedrockClient(region=region)
            logger.info("Bedrock client initialized (region=%s)", region)

        if backend in ("claude-agent-sdk", "both"):
            sdk_cfg = _agents_cfg.get("claude_agent_sdk", {})
            allowed_tools_cfg = sdk_cfg.get("allowed_tools", {})
            self._claude_sdk_client = ClaudeSDKClient(
                max_turns_default=int(sdk_cfg.get("max_turns_worker", 25)),
                permission_mode=sdk_cfg.get("permission_mode", "acceptEdits"),
                allowed_tools=allowed_tools_cfg.get("worker", ["Read", "Write", "Bash"]),
                cwd=sdk_cfg.get("cwd"),
            )
            logger.info("Claude Agent SDK client initialized (backend=%s)", backend)

        # Memory
        memory_config = MemoryConfig(aws_region=region)
        self._memory_client = MemoryClient(config=memory_config)

        # MCP
        async def _default_mcp_call(tool: str, args: dict[str, Any]) -> Any:
            logger.debug("Default MCP call: %s(%s)", tool, args)
            return {"_stub": True, "tool": tool}

        self._mcp_manager = MCPManager.create(
            mcp_call=mcp_call or _default_mcp_call
        )

        # Agent infrastructure — pass both clients + MCP to all agents
        self._message_bus = MessageBus()

        # Repository infrastructure
        self._repo_registry = get_default_repo_registry()
        infra_cfg = self._repo_registry.get_infra_config()
        self._workspace_manager = WorkspaceManager()
        self._host_manager = HostManager(infra_cfg)
        self._env_file_manager = EnvFileManager(infra_cfg)
        self._dev_env_manager = DevEnvironmentManager(
            infra_config=infra_cfg,
            shared_services=self._repo_registry.get_shared_services(),
            registry=self._repo_registry,
        )

        self._registry = AgentRegistry(
            message_bus=self._message_bus,
            bedrock_client=self._bedrock_client,
            claude_sdk_client=self._claude_sdk_client,
            mcp_call=mcp_call or _default_mcp_call,
            repo_registry=self._repo_registry,
            workspace_manager=self._workspace_manager,
            dev_env_manager=self._dev_env_manager,
            host_manager=self._host_manager,
            env_file_manager=self._env_file_manager,
        )
        self._orchestrator = Orchestrator(
            registry=self._registry,
            message_bus=self._message_bus,
            bedrock_client=self._bedrock_client,
            claude_sdk_client=self._claude_sdk_client,
            mcp_call=mcp_call or _default_mcp_call,
            repo_registry=self._repo_registry,
        )

        # Seed semantic memory with golden rules
        claude_md_path = os.environ.get("CLAUDE_MD_PATH", "CLAUDE.md")
        if os.path.exists(claude_md_path):
            count = await self._memory_client.seed_from_claude_md(claude_md_path)
            logger.info("Seeded %d rules from %s", count, claude_md_path)

        logger.info("AgentCore entrypoint initialized")

    async def handle_task(self, jira_key: str) -> dict[str, Any]:
        """Process a single Jira ticket through the full pipeline.

        This is the main handler invoked by AgentCore Runtime when a
        task arrives (via API Gateway webhook or manual trigger).
        """
        if self._orchestrator is None or self._mcp_manager is None or self._memory_client is None:
            raise RuntimeError("Entrypoint not initialized — call initialize() first")

        logger.info("Handling task: %s", jira_key)

        pipeline = WorkflowPipeline(
            jira_key=jira_key,
            orchestrator=self._orchestrator,
            mcp_manager=self._mcp_manager,
            memory_client=self._memory_client,
        )

        context = await pipeline.run()

        return {
            "workflow_id": context.workflow_id,
            "jira_key": context.jira_key,
            "final_state": context.current_state.value,
            "pr_url": context.pr_url,
            "transitions": len(context.transitions),
            "error": context.error_info or None,
        }

    async def poll_sqs(self) -> None:
        """Long-poll SQS for task messages and process them.

        Runs until the shutdown event is set. Each message is expected
        to contain a JSON body with an 'issue_key' field.
        """
        queue_url = os.environ.get("SQS_QUEUE_URL", "")
        if not queue_url:
            logger.error("SQS_QUEUE_URL not set — cannot poll for tasks")
            return

        region = os.environ.get("AWS_REGION", "us-east-1")
        sqs = boto3.client("sqs", region_name=region)
        logger.info("Starting SQS polling loop (queue=%s)", queue_url)

        while not self._shutdown_event.is_set():
            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: sqs.receive_message(
                        QueueUrl=queue_url,
                        MaxNumberOfMessages=1,
                        WaitTimeSeconds=20,
                        MessageAttributeNames=["All"],
                    ),
                )

                messages = response.get("Messages", [])
                if not messages:
                    continue

                for message in messages:
                    receipt_handle = message["ReceiptHandle"]
                    body = json.loads(message["Body"])
                    issue_key = body.get("issue_key", "")

                    if not issue_key:
                        logger.warning(
                            "SQS message missing issue_key, skipping: %s",
                            message["MessageId"],
                        )
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda rh=receipt_handle: sqs.delete_message(
                                QueueUrl=queue_url, ReceiptHandle=rh,
                            ),
                        )
                        continue

                    logger.info("Processing task from SQS: %s", issue_key)
                    try:
                        result = await self.handle_task(issue_key)
                        logger.info(
                            "Task completed: %s — state=%s",
                            issue_key,
                            result["final_state"],
                        )
                    except Exception:
                        logger.exception("Task failed: %s", issue_key)

                    # Delete message after processing (success or failure)
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda rh=receipt_handle: sqs.delete_message(
                            QueueUrl=queue_url, ReceiptHandle=rh,
                        ),
                    )

            except Exception:
                if not self._shutdown_event.is_set():
                    logger.exception("Error in SQS polling loop")
                    await asyncio.sleep(5)

    async def shutdown(self) -> None:
        """Gracefully shut down all components."""
        logger.info("Shutting down AgentCore entrypoint")
        self._shutdown_event.set()

        if self._registry is not None:
            await self._registry.shutdown_all()

        MCPManager.reset()
        logger.info("Shutdown complete")


class HealthCheck:
    """Simple health check endpoint for AgentCore Runtime."""

    def __init__(self, entrypoint: AgentCoreEntrypoint) -> None:
        self._entrypoint = entrypoint

    async def check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "initialized": self._entrypoint._orchestrator is not None,
        }


async def _run_worker() -> None:
    """Main async entry point for the SQS worker process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    entrypoint = AgentCoreEntrypoint()
    loop = asyncio.get_event_loop()

    # Handle graceful shutdown signals
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(entrypoint.shutdown()))

    await entrypoint.initialize()
    await entrypoint.poll_sqs()
    await entrypoint.shutdown()


def main() -> None:
    """Synchronous entry point for `python -m src.runtime.entrypoint`."""
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
