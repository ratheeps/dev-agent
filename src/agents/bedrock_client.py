"""Bedrock Runtime client for invoking Claude models.

Provides a typed async wrapper around the Bedrock Runtime ``converse`` API
that handles tool-use loops, token tracking, and cost estimation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from src.settings import get_settings

logger = logging.getLogger(__name__)

# Bedrock model IDs — read from settings for environment-level overrides
OPUS_MODEL_ID = get_settings().opus_model_id
SONNET_MODEL_ID = get_settings().sonnet_model_id

# Cost per 1M tokens (USD) — update as pricing changes
MODEL_COSTS: dict[str, dict[str, float]] = {
    OPUS_MODEL_ID: {"input": 15.0, "output": 75.0},
    SONNET_MODEL_ID: {"input": 3.0, "output": 15.0},
}

# Map our config model names to Bedrock model IDs
MODEL_ID_MAP: dict[str, str] = {
    "claude-opus-4-6": OPUS_MODEL_ID,
    "claude-sonnet-4-6": SONNET_MODEL_ID,
}


@dataclass
class ConversationTurn:
    """A single turn in the conversation with the model."""

    role: str  # "user" or "assistant"
    content: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ToolDefinition:
    """MCP tool definition formatted for Bedrock Converse API."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)

    def to_bedrock_format(self) -> dict[str, Any]:
        return {
            "toolSpec": {
                "name": self.name,
                "description": self.description,
                "inputSchema": {
                    "json": self.input_schema,
                },
            },
        }


@dataclass
class InvocationResult:
    """Result from a single model invocation."""

    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class BedrockClient:
    """Async wrapper around AWS Bedrock Runtime ``converse`` API.

    Handles:
    - Model invocation with system prompts and tools
    - Automatic tool-use loops (call model → execute tools → feed results back)
    - Token counting and cost estimation
    - Retry on throttling

    Parameters
    ----------
    region:
        AWS region for Bedrock Runtime.
    max_retries:
        Boto3 retry count for throttled requests.
    """

    def __init__(
        self,
        *,
        region: str = "us-east-1",
        max_retries: int = 3,
    ) -> None:
        self._region = region
        boto_config = BotoConfig(
            region_name=region,
            retries={"max_attempts": max_retries, "mode": "adaptive"},
        )
        self._client = boto3.client("bedrock-runtime", config=boto_config)

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
        """Invoke a Claude model via Bedrock Converse API.

        Parameters
        ----------
        model:
            Model name (e.g. "claude-opus-4-6") or full Bedrock model ID.
        system_prompt:
            System prompt text.
        messages:
            Conversation messages in Bedrock Converse format.
        tools:
            Optional list of tool definitions for tool use.
        max_tokens:
            Maximum output tokens.
        temperature:
            Sampling temperature.

        Returns
        -------
        InvocationResult with text response, any tool calls, and token usage.
        """
        model_id = MODEL_ID_MAP.get(model, model)

        request: dict[str, Any] = {
            "modelId": model_id,
            "system": [{"text": system_prompt}],
            "messages": messages,
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        }

        if tools:
            request["toolConfig"] = {
                "tools": [t.to_bedrock_format() for t in tools],
            }

        try:
            response = await asyncio.to_thread(
                self._client.converse, **request
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            logger.error(
                "Bedrock invocation failed: %s — %s", error_code, exc
            )
            raise

        return self._parse_response(response, model_id)

    async def invoke_with_tool_loop(
        self,
        *,
        model: str,
        system_prompt: str,
        user_message: str,
        tools: list[ToolDefinition] | None = None,
        tool_executor: Any = None,
        max_tokens: int = 4096,
        max_turns: int = 20,
    ) -> InvocationResult:
        """Invoke a model with automatic tool-use loop.

        When the model responds with tool_use, calls ``tool_executor`` for each
        tool, feeds the results back, and continues until the model produces
        a final text response or ``max_turns`` is reached.

        Parameters
        ----------
        tool_executor:
            Async callable: ``async (tool_name: str, tool_input: dict) -> Any``
        """
        model_id = MODEL_ID_MAP.get(model, model)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": [{"text": user_message}]},
        ]

        total_input_tokens = 0
        total_output_tokens = 0

        for turn in range(max_turns):
            result = await self.invoke(
                model=model,
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
            )

            total_input_tokens += result.input_tokens
            total_output_tokens += result.output_tokens

            if not result.tool_calls or tool_executor is None:
                # Final response — no more tool calls
                result.input_tokens = total_input_tokens
                result.output_tokens = total_output_tokens
                result.cost_usd = self._estimate_cost(
                    model_id, total_input_tokens, total_output_tokens
                )
                return result

            # Build assistant message with tool_use blocks
            assistant_content: list[dict[str, Any]] = []
            if result.text:
                assistant_content.append({"text": result.text})
            for tc in result.tool_calls:
                assistant_content.append({
                    "toolUse": {
                        "toolUseId": tc["id"],
                        "name": tc["name"],
                        "input": tc["input"],
                    },
                })
            messages.append({"role": "assistant", "content": assistant_content})

            # Execute each tool and build tool_result message
            tool_results: list[dict[str, Any]] = []
            for tc in result.tool_calls:
                try:
                    tool_output = await tool_executor(tc["name"], tc["input"])
                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tc["id"],
                            "content": [{"json": tool_output if isinstance(tool_output, dict) else {"result": str(tool_output)}}],
                        },
                    })
                except Exception as exc:
                    logger.warning("Tool %s failed: %s", tc["name"], exc)
                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tc["id"],
                            "content": [{"text": f"Error: {exc}"}],
                            "status": "error",
                        },
                    })

            messages.append({"role": "user", "content": tool_results})

        logger.warning("Tool loop reached max_turns=%d", max_turns)
        return InvocationResult(
            text="[Max tool-use turns reached]",
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cost_usd=self._estimate_cost(
                model_id, total_input_tokens, total_output_tokens
            ),
        )

    def _parse_response(
        self, response: dict[str, Any], model_id: str
    ) -> InvocationResult:
        """Parse a Bedrock Converse response into an InvocationResult."""
        output = response.get("output", {})
        message = output.get("message", {})
        content_blocks = message.get("content", [])

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        for block in content_blocks:
            if "text" in block:
                text_parts.append(block["text"])
            elif "toolUse" in block:
                tu = block["toolUse"]
                tool_calls.append({
                    "id": tu["toolUseId"],
                    "name": tu["name"],
                    "input": tu.get("input", {}),
                })

        usage = response.get("usage", {})
        input_tokens = usage.get("inputTokens", 0)
        output_tokens = usage.get("outputTokens", 0)

        return InvocationResult(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=response.get("stopReason", ""),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=self._estimate_cost(model_id, input_tokens, output_tokens),
        )

    @staticmethod
    def _estimate_cost(
        model_id: str, input_tokens: int, output_tokens: int
    ) -> float:
        costs = MODEL_COSTS.get(model_id, {"input": 0.0, "output": 0.0})
        return (
            (input_tokens / 1_000_000) * costs["input"]
            + (output_tokens / 1_000_000) * costs["output"]
        )
