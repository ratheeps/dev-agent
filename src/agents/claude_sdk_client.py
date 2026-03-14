"""Claude Agent SDK client — async wrapper around the claude-agent-sdk package.

Provides the same interface as :class:`~src.agents.bedrock_client.BedrockClient`
so agents can swap between backends transparently via config.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agents.bedrock_client import InvocationResult, ToolDefinition
from src.settings import get_settings

logger = logging.getLogger(__name__)


def _build_model_name_map() -> dict[str, str]:
    """Derive SDK model names from settings (strip ``us.anthropic.`` prefix and version suffix)."""
    settings = get_settings()
    result: dict[str, str] = {}
    for short_name, bedrock_id in [
        ("claude-opus-4-6", settings.opus_model_id),
        ("claude-sonnet-4-6", settings.sonnet_model_id),
    ]:
        # "us.anthropic.claude-opus-4-6-20250609-v1:0" → "claude-opus-4-6-20250609"
        name = bedrock_id
        if name.startswith("us.anthropic."):
            name = name[len("us.anthropic."):]
        # Remove trailing version suffix like "-v1:0"
        if ":0" in name:
            name = name[: name.rindex("-v")]
        result[short_name] = name
    return result


# Map our config model names to Claude model identifiers
MODEL_NAME_MAP: dict[str, str] = _build_model_name_map()

# Approximate cost per 1M tokens (USD) — mirrors bedrock_client.py for cost parity
SDK_MODEL_COSTS: dict[str, dict[str, float]] = {
    "claude-opus-4-6-20250609": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6-20250514": {"input": 3.0, "output": 15.0},
}


class ClaudeSDKClient:
    """Async wrapper around the ``claude-agent-sdk`` package.

    Provides autonomous agentic capabilities (file I/O, bash execution,
    multi-turn tool use) on top of the Claude Code CLI, with the same
    public interface as :class:`~src.agents.bedrock_client.BedrockClient`.

    Parameters
    ----------
    max_turns_default:
        Default maximum number of agentic turns per invocation.
    permission_mode:
        Controls how the agent handles file/system changes.
        - ``"acceptEdits"``: automatically accept all file edits (autonomous mode)
        - ``"prompt"``: prompt for confirmation (interactive mode)
    allowed_tools:
        List of tools the agent is permitted to use.
        Defaults to Read, Write, Bash for full code implementation capability.
    cwd:
        Working directory for the agent's file operations.
    """

    def __init__(
        self,
        *,
        max_turns_default: int = 25,
        permission_mode: str = "acceptEdits",
        allowed_tools: list[str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self._max_turns_default = max_turns_default
        self._permission_mode = permission_mode
        self._allowed_tools = allowed_tools or ["Read", "Write", "Bash"]
        self._cwd = cwd

    # ------------------------------------------------------------------
    # Public interface (mirrors BedrockClient)
    # ------------------------------------------------------------------

    async def invoke(
        self,
        *,
        model: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> InvocationResult:
        """Invoke Claude via the Agent SDK for a single prompt.

        Extracts the last user message from *messages* and passes it as the
        prompt to the SDK's ``query()`` function.

        Parameters
        ----------
        model:
            Model name (e.g. ``"claude-sonnet-4-6"``).
        system_prompt:
            System prompt text (injected via ``ClaudeAgentOptions``).
        messages:
            Conversation messages.  The last user-role message is used as prompt.
        tools:
            MCP tool definitions (forwarded as context; SDK manages its own tools).
        max_tokens:
            Not directly supported by the SDK; kept for interface compatibility.
        temperature:
            Not directly supported by the SDK; kept for interface compatibility.
        """
        # Extract the most recent user message as the prompt
        user_prompt = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("text"):
                            user_prompt = block["text"]
                            break
                elif isinstance(content, str):
                    user_prompt = content
                break

        if not user_prompt:
            user_prompt = str(messages[-1]) if messages else ""

        return await self._run_query(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_turns=self._max_turns_default,
        )

    async def invoke_with_tool_loop(
        self,
        *,
        model: str,
        system_prompt: str,
        user_message: str,
        tools: list[ToolDefinition] | None = None,
        tool_executor: Any = None,
        max_tokens: int = 4096,
        max_turns: int = 25,
    ) -> InvocationResult:
        """Invoke Claude via the Agent SDK with autonomous tool execution.

        The SDK handles its own tool-use loop (Read/Write/Bash) natively,
        so this method simply delegates to :meth:`_run_query` with the
        specified ``max_turns``.  The *tool_executor* parameter is kept for
        interface compatibility but is not used.
        """
        return await self._run_query(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_message,
            max_turns=max_turns,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run_query(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_turns: int,
    ) -> InvocationResult:
        """Run a query against the Claude Agent SDK and return an InvocationResult."""
        try:
            from claude_agent_sdk import (  # type: ignore[import-not-found]
                AssistantMessage,
                ClaudeAgentOptions,
                TextBlock,
                query,
            )
        except ImportError as exc:
            raise RuntimeError(
                "claude-agent-sdk is not installed. "
                "Run: uv pip install 'claude-agent-sdk>=0.1'"
            ) from exc

        model_id = MODEL_NAME_MAP.get(model, model)

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            allowed_tools=self._allowed_tools,
            permission_mode=self._permission_mode,
            max_turns=max_turns,
            **({"cwd": self._cwd} if self._cwd else {}),
        )

        collected_text = ""
        input_tokens = 0
        output_tokens = 0

        async for message in query(prompt=user_prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        collected_text += block.text
            # Accumulate token counts from usage metadata if present
            if hasattr(message, "usage") and message.usage:
                input_tokens += getattr(message.usage, "input_tokens", 0)
                output_tokens += getattr(message.usage, "output_tokens", 0)

        cost_usd = self._estimate_cost(model_id, input_tokens, output_tokens)

        logger.info(
            "ClaudeSDKClient: query complete model=%s tokens_in=%d tokens_out=%d cost=$%.4f",
            model_id,
            input_tokens,
            output_tokens,
            cost_usd,
        )

        return InvocationResult(
            text=collected_text,
            tool_calls=[],
            stop_reason="end_turn",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )

    @staticmethod
    def _estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost in USD based on token counts."""
        costs = SDK_MODEL_COSTS.get(model_id, {"input": 3.0, "output": 15.0})
        return (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000
