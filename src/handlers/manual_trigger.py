"""CLI entry point for manually triggering the Jira-to-PR pipeline.

Usage::

    python -m src.handlers.manual_trigger --ticket GIFT-1234
    python -m src.handlers.manual_trigger --ticket GIFT-1234 --bedrock
    python -m src.handlers.manual_trigger --ticket GIFT-1234 --backend claude-agent-sdk
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from typing import Any

from src.agents.communication import MessageBus
from src.agents.orchestrator import Orchestrator
from src.agents.registry import AgentRegistry
from src.integrations.mcp_manager import MCPManager
from src.memory.client import MemoryClient
from src.workflows.pipeline import WorkflowPipeline

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trigger the Dev-AI pipeline for a Jira ticket",
    )
    parser.add_argument(
        "--ticket",
        required=True,
        help="Jira ticket key (e.g., GIFT-1234)",
    )
    parser.add_argument(
        "--bedrock",
        action="store_true",
        help="Enable real Bedrock model invocations (shorthand for --backend bedrock)",
    )
    parser.add_argument(
        "--backend",
        choices=["bedrock", "claude-agent-sdk", "stub"],
        default=None,
        help=(
            "LLM backend to use: 'bedrock' (AWS Bedrock converse API), "
            "'claude-agent-sdk' (autonomous agentic), or 'stub' (no LLM). "
            "Defaults to the 'backend' value in config/agents.yaml."
        ),
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", "us-east-1"),
        help="AWS region for Bedrock Runtime (default: us-east-1)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


async def _stub_mcp_call(tool_name: str, arguments: dict[str, Any]) -> Any:
    """Stub MCP callable for local development."""
    logger.debug("Stub MCP call: %s(%s)", tool_name, arguments)
    return {"_stub": True, "tool": tool_name, "args": arguments}


async def run_pipeline(
    ticket: str,
    *,
    backend: str = "stub",
    region: str = "us-east-1",
) -> None:
    """Initialize all dependencies and run the pipeline."""
    from src.agents.bedrock_client import BedrockClient
    from src.agents.claude_sdk_client import ClaudeSDKClient

    bedrock_client = None
    claude_sdk_client = None

    if backend == "bedrock":
        bedrock_client = BedrockClient(region=region)
        print(f"Backend: Bedrock (region={region})")
    elif backend == "claude-agent-sdk":
        claude_sdk_client = ClaudeSDKClient()
        print("Backend: Claude Agent SDK (autonomous agentic mode)")
    else:
        print(  # noqa: E501
            "Backend: stub (no LLM calls). Use --backend bedrock|claude-agent-sdk for real calls."
        )

    # Initialize MCP manager
    mcp_manager = MCPManager.create(mcp_call=_stub_mcp_call)

    # Initialize memory client
    memory_client = MemoryClient()

    # Initialize agent infrastructure
    message_bus = MessageBus()
    registry = AgentRegistry(
        message_bus=message_bus,
        bedrock_client=bedrock_client,
        claude_sdk_client=claude_sdk_client,
        mcp_call=_stub_mcp_call,
    )
    orchestrator = Orchestrator(
        registry=registry,
        message_bus=message_bus,
        bedrock_client=bedrock_client,
        claude_sdk_client=claude_sdk_client,
        mcp_call=_stub_mcp_call,
    )

    # Create and run the pipeline
    pipeline = WorkflowPipeline(
        jira_key=ticket,
        orchestrator=orchestrator,
        mcp_manager=mcp_manager,
        memory_client=memory_client,
    )

    print(f"Starting pipeline for {ticket}...")

    context = await pipeline.run()

    print(f"\nPipeline finished: {context.current_state.value}")
    print(f"Transitions: {len(context.transitions)}")
    if context.pr_url:
        print(f"PR: {context.pr_url}")
    if context.error_info:
        print(f"Error: {context.error_info}")

    # Print cost summary
    print(f"\nOrchestrator cost: ${orchestrator.token_usage.total_cost_usd:.4f}")
    print(f"  Input tokens: {orchestrator.token_usage.input_tokens}")
    print(f"  Output tokens: {orchestrator.token_usage.output_tokens}")


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Resolve backend: --bedrock flag is shorthand for --backend bedrock
    backend = args.backend
    if args.bedrock and backend is None:
        backend = "bedrock"
    if backend is None:
        backend = "stub"

    # Handle Ctrl+C gracefully
    loop = asyncio.new_event_loop()

    def _shutdown(sig: signal.Signals) -> None:
        print(f"\nReceived {sig.name}, shutting down...")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown, sig)

    try:
        loop.run_until_complete(
            run_pipeline(args.ticket, backend=backend, region=args.region)
        )
    except asyncio.CancelledError:
        print("Pipeline cancelled.")
        sys.exit(1)
    finally:
        loop.close()
        MCPManager.reset()


if __name__ == "__main__":
    main()
