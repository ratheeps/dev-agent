"""Abstract base class for all agents in the system."""

from __future__ import annotations

import abc
import logging
import pathlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import yaml

from src.agents.bedrock_client import BedrockClient, InvocationResult, ToolDefinition
from src.agents.claude_sdk_client import ClaudeSDKClient
from src.schemas.message import AgentMessage, MessageType
from src.schemas.task import SubTask, Task

logger = logging.getLogger(__name__)

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CONFIG_DIR = _PROJECT_ROOT / "config"


def _load_yaml(path: pathlib.Path) -> dict[str, Any]:
    """Read a YAML file and return its contents as a dict."""
    with open(path) as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise TypeError(f"Expected dict from {path}, got {type(data).__name__}")
    return data


def load_agents_config() -> dict[str, Any]:
    return _load_yaml(_CONFIG_DIR / "agents.yaml")


def load_limits_config() -> dict[str, Any]:
    return _load_yaml(_CONFIG_DIR / "limits.yaml")


def load_prompt(filename: str) -> str:
    """Load a markdown prompt file from ``src/prompts/``."""
    prompt_path = _PROJECT_ROOT / "src" / "prompts" / filename
    return prompt_path.read_text(encoding="utf-8")


# ------------------------------------------------------------------
# Token / cost tracking
# ------------------------------------------------------------------

@dataclass
class TokenUsage:
    """Accumulates token consumption and estimated cost for an agent."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0
    calls: int = 0

    def record(
        self,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_cost_usd += cost_usd
        self.calls += 1

    @property
    def exceeded_ceiling(self) -> bool:
        """Check if total cost has exceeded the daily ceiling."""
        return False  # Checked against limits in _check_cost_guard


# ------------------------------------------------------------------
# MCP tool invocation result
# ------------------------------------------------------------------

@dataclass
class MCPToolResult:
    """Represents the result of an MCP tool call."""

    server: str
    tool: str
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# ------------------------------------------------------------------
# Base agent
# ------------------------------------------------------------------

class BaseAgent(abc.ABC):
    """Abstract base for orchestrator and worker agents.

    Subclasses must implement :meth:`run`.  The base class provides shared
    infrastructure: Bedrock model invocation, MCP tool calls, message
    helpers, config loading, token tracking, and async context-manager
    support.
    """

    def __init__(
        self,
        *,
        agent_id: str | None = None,
        model: str,
        role: str,
        system_prompt: str = "",
        bedrock_client: BedrockClient | None = None,
        claude_sdk_client: ClaudeSDKClient | None = None,
        mcp_call: Any | None = None,
    ) -> None:
        self.agent_id: str = agent_id or f"{role}-{uuid.uuid4().hex[:8]}"
        self.model: str = model
        self.role: str = role
        self.system_prompt: str = system_prompt
        self.token_usage: TokenUsage = TokenUsage()
        self.created_at: datetime = datetime.now(timezone.utc)
        self._running: bool = False
        self._message_handler: Any | None = None  # set by communication layer

        # Bedrock client for LLM calls
        self._bedrock: BedrockClient | None = bedrock_client

        # Claude Agent SDK client (autonomous agentic backend)
        self._claude_sdk: ClaudeSDKClient | None = claude_sdk_client

        # MCP callable: async (tool_name, arguments) -> Any
        self._mcp_call: Any | None = mcp_call

        # Load config at construction time so subclasses can reference it.
        self._agents_config: dict[str, Any] = load_agents_config()
        self._limits_config: dict[str, Any] = load_limits_config()

        self._daily_ceiling_usd: float = float(
            self._limits_config.get("cost", {}).get("daily_ceiling_usd", 50.0)
        )

        # Resolve which backend to use from config
        self._backend: str = self._agents_config.get("backend", "bedrock")

        logger.info(
            "Agent created: id=%s model=%s role=%s backend=%s",
            self.agent_id, model, role, self._backend,
        )

    # -- lifecycle --------------------------------------------------

    async def __aenter__(self) -> BaseAgent:
        self._running = True
        logger.info("Agent started: %s", self.agent_id)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self._running = False
        logger.info(
            "Agent stopped: %s  tokens_in=%d tokens_out=%d cost=$%.4f",
            self.agent_id,
            self.token_usage.input_tokens,
            self.token_usage.output_tokens,
            self.token_usage.total_cost_usd,
        )

    # -- abstract interface -----------------------------------------

    @abc.abstractmethod
    async def run(self, task: Task | SubTask) -> dict[str, Any]:
        """Execute the agent's primary workflow for the given task.

        Returns a result dict whose shape depends on the agent type.
        """

    # -- LLM invocation via Bedrock or Claude Agent SDK ---------------------------------

    async def think(
        self,
        prompt: str,
        *,
        tools: list[ToolDefinition] | None = None,
        tool_executor: Any | None = None,
        max_tokens: int = 4096,
    ) -> InvocationResult:
        """Send a prompt to the agent's model and return the result.

        Backend selection is driven by ``agents.yaml`` ``backend`` field:
        - ``"claude-agent-sdk"``: uses :class:`ClaudeSDKClient` for autonomous
          agentic operation (file I/O, bash, multi-turn tool use).
        - ``"bedrock"``: uses :class:`BedrockClient` (Bedrock converse API).
        - Falls back to stub when neither client is configured.
        """
        self._check_cost_guard()

        result: InvocationResult | None = None

        if self._backend == "claude-agent-sdk" and self._claude_sdk is not None:
            result = await self._invoke_with_sdk(prompt, tools=tools, max_tokens=max_tokens)
        elif self._backend == "bedrock" and self._bedrock is not None:
            result = await self._invoke_with_bedrock(
                prompt, tools=tools, tool_executor=tool_executor, max_tokens=max_tokens
            )
        elif self._bedrock is not None:
            # Bedrock available as fallback even if backend=claude-agent-sdk
            logger.warning(
                "Agent %s: backend='%s' but SDK not configured — falling back to Bedrock",
                self.agent_id,
                self._backend,
            )
            result = await self._invoke_with_bedrock(
                prompt, tools=tools, tool_executor=tool_executor, max_tokens=max_tokens
            )
        else:
            logger.warning(
                "Agent %s: no backend configured — returning stub response",
                self.agent_id,
            )
            return InvocationResult(
                text=f"[stub] Agent {self.agent_id} would process: {prompt[:100]}...",
                stop_reason="end_turn",
            )

        # Track usage
        self.token_usage.record(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
        )

        logger.info(
            "Agent %s: think complete backend=%s tokens_in=%d tokens_out=%d cost=$%.4f",
            self.agent_id,
            self._backend,
            result.input_tokens,
            result.output_tokens,
            result.cost_usd,
        )

        return result

    async def _invoke_with_sdk(
        self,
        prompt: str,
        *,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
    ) -> InvocationResult:
        """Invoke via the Claude Agent SDK backend."""
        assert self._claude_sdk is not None
        sdk_cfg = self._agents_config.get("claude_agent_sdk", {})
        max_turns_key = (
            "max_turns_orchestrator" if self.role == "orchestrator" else "max_turns_worker"
        )
        max_turns: int = int(sdk_cfg.get(max_turns_key, 25))

        return await self._claude_sdk.invoke_with_tool_loop(
            model=self.model,
            system_prompt=self.system_prompt,
            user_message=prompt,
            tools=tools,
            max_tokens=max_tokens,
            max_turns=max_turns,
        )

    async def _invoke_with_bedrock(
        self,
        prompt: str,
        *,
        tools: list[ToolDefinition] | None = None,
        tool_executor: Any | None = None,
        max_tokens: int = 4096,
    ) -> InvocationResult:
        """Invoke via the Bedrock converse API backend."""
        assert self._bedrock is not None
        if tools and tool_executor:
            return await self._bedrock.invoke_with_tool_loop(
                model=self.model,
                system_prompt=self.system_prompt,
                user_message=prompt,
                tools=tools,
                tool_executor=tool_executor,
                max_tokens=max_tokens,
            )
        messages = [{"role": "user", "content": [{"text": prompt}]}]
        return await self._bedrock.invoke(
            model=self.model,
            system_prompt=self.system_prompt,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
        )

    def _check_cost_guard(self) -> None:
        """Halt if daily cost ceiling is exceeded."""
        if self.token_usage.total_cost_usd >= self._daily_ceiling_usd:
            raise RuntimeError(
                f"Agent {self.agent_id}: daily cost ceiling "
                f"${self._daily_ceiling_usd:.2f} exceeded "
                f"(current: ${self.token_usage.total_cost_usd:.2f})"
            )

    # -- messaging ---------------------------------------------------

    async def send_message(self, message: AgentMessage) -> None:
        """Publish *message* to the communication bus.

        If no message handler is wired, the message is logged and dropped.
        """
        if self._message_handler is not None:
            await self._message_handler.publish(message)
        else:
            logger.warning(
                "No message handler on agent %s — dropping message %s",
                self.agent_id,
                message.id,
            )

    async def receive_message(self, message: AgentMessage) -> None:
        """Handle an incoming *message*.

        The default implementation logs the message.  Subclasses override
        this to react to specific :class:`MessageType` values.
        """
        logger.info(
            "Agent %s received %s from %s",
            self.agent_id,
            message.message_type.value,
            message.from_agent,
        )

    def build_message(
        self,
        *,
        to_agent: str,
        message_type: MessageType,
        payload: dict[str, Any] | None = None,
    ) -> AgentMessage:
        """Convenience factory for creating an :class:`AgentMessage`."""
        return AgentMessage(
            from_agent=self.agent_id,
            to_agent=to_agent,
            message_type=message_type,
            payload=payload or {},
        )

    # -- MCP tool invocation ----------------------------------------

    async def call_mcp_tool(
        self,
        server: str,
        tool: str,
        args: dict[str, Any] | None = None,
    ) -> MCPToolResult:
        """Invoke an MCP tool on *server*.

        If an ``mcp_call`` callable was provided, it is used to execute the
        tool. Otherwise returns a stub result for local development.
        """
        logger.info(
            "MCP tool call: agent=%s server=%s tool=%s",
            self.agent_id,
            server,
            tool,
        )

        if self._mcp_call is not None:
            try:
                result_data = await self._mcp_call(tool, args or {})
                return MCPToolResult(
                    server=server,
                    tool=tool,
                    success=True,
                    data=result_data if isinstance(result_data, dict) else {"result": result_data},
                )
            except Exception as exc:
                logger.error("MCP tool %s.%s failed: %s", server, tool, exc)
                return MCPToolResult(
                    server=server,
                    tool=tool,
                    success=False,
                    error=str(exc),
                )

        # Stub for local development
        return MCPToolResult(
            server=server,
            tool=tool,
            success=True,
            data={"_stub": True, "args": args or {}},
        )
