"""Tests for the ClaudeSDKClient wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.bedrock_client import InvocationResult
from src.agents.claude_sdk_client import MODEL_NAME_MAP, SDK_MODEL_COSTS, ClaudeSDKClient


class TestClaudeSDKClientInit:
    def test_defaults(self) -> None:
        client = ClaudeSDKClient()
        assert client._max_turns_default == 25
        assert client._permission_mode == "acceptEdits"
        assert "Read" in client._allowed_tools
        assert "Write" in client._allowed_tools
        assert "Bash" in client._allowed_tools
        assert client._cwd is None

    def test_custom_params(self) -> None:
        client = ClaudeSDKClient(
            max_turns_default=50,
            permission_mode="prompt",
            allowed_tools=["Read"],
            cwd="/workspace",
        )
        assert client._max_turns_default == 50
        assert client._permission_mode == "prompt"
        assert client._allowed_tools == ["Read"]
        assert client._cwd == "/workspace"


class TestModelMapping:
    def test_model_name_map_contains_opus(self) -> None:
        assert "claude-opus-4-6" in MODEL_NAME_MAP

    def test_model_name_map_contains_sonnet(self) -> None:
        assert "claude-sonnet-4-6" in MODEL_NAME_MAP

    def test_cost_table_contains_mapped_models(self) -> None:
        for model_id in MODEL_NAME_MAP.values():
            assert model_id in SDK_MODEL_COSTS


class TestCostEstimation:
    def test_estimate_cost_zero_tokens(self) -> None:
        cost = ClaudeSDKClient._estimate_cost("claude-sonnet-4-6-20250514", 0, 0)
        assert cost == 0.0

    def test_estimate_cost_known_model(self) -> None:
        # 1M input + 1M output at Sonnet rates = $3 + $15 = $18
        cost = ClaudeSDKClient._estimate_cost("claude-sonnet-4-6-20250514", 1_000_000, 1_000_000)
        assert abs(cost - 18.0) < 0.01

    def test_estimate_cost_unknown_model_uses_default(self) -> None:
        cost = ClaudeSDKClient._estimate_cost("unknown-model", 1_000_000, 1_000_000)
        # Falls back to {"input": 3.0, "output": 15.0}
        assert abs(cost - 18.0) < 0.01


class TestInvokeExtractsUserMessage:
    """Test that invoke() correctly extracts the user message from messages list."""

    @pytest.mark.asyncio
    async def test_invoke_extracts_last_user_message(self) -> None:
        client = ClaudeSDKClient()

        mock_result = InvocationResult(text="hello from sdk", stop_reason="end_turn")

        with patch.object(client, "_run_query", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_result
            messages = [
                {"role": "user", "content": [{"text": "hello world"}]},
            ]
            result = await client.invoke(
                model="claude-sonnet-4-6",
                system_prompt="system",
                messages=messages,
            )
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["user_prompt"] == "hello world"
            assert result.text == "hello from sdk"

    @pytest.mark.asyncio
    async def test_invoke_handles_string_content(self) -> None:
        client = ClaudeSDKClient()

        with patch.object(client, "_run_query", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = InvocationResult(text="response")
            messages = [{"role": "user", "content": "plain string content"}]
            await client.invoke(
                model="claude-sonnet-4-6",
                system_prompt="system",
                messages=messages,
            )
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["user_prompt"] == "plain string content"


class TestInvokeWithToolLoop:
    @pytest.mark.asyncio
    async def test_delegates_to_run_query(self) -> None:
        client = ClaudeSDKClient()

        expected = InvocationResult(text="result", stop_reason="end_turn")
        with patch.object(client, "_run_query", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = expected
            result = await client.invoke_with_tool_loop(
                model="claude-sonnet-4-6",
                system_prompt="system",
                user_message="do the thing",
                max_turns=10,
            )
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["max_turns"] == 10
            assert call_kwargs["user_prompt"] == "do the thing"
            assert result is expected


class TestRunQuery:
    @pytest.mark.asyncio
    async def test_raises_when_sdk_not_installed(self) -> None:
        client = ClaudeSDKClient()

        with patch.dict("sys.modules", {"claude_agent_sdk": None}):
            with pytest.raises(RuntimeError, match="claude-agent-sdk is not installed"):
                await client._run_query(
                    model="claude-sonnet-4-6",
                    system_prompt="system",
                    user_prompt="test",
                    max_turns=5,
                )

    @pytest.mark.asyncio
    async def test_accumulates_text_from_messages(self) -> None:
        client = ClaudeSDKClient()

        # Build a mock SDK module
        mock_text_block = MagicMock()
        mock_text_block.text = "hello world"

        mock_assistant_msg = MagicMock()
        mock_assistant_msg.content = [mock_text_block]

        mock_sdk = MagicMock()
        mock_sdk.ClaudeAgentOptions = MagicMock(return_value=MagicMock())

        # Make AssistantMessage and TextBlock check work via isinstance
        # We patch by making the mock classes match type checks
        mock_sdk.AssistantMessage = type(mock_assistant_msg)
        mock_sdk.TextBlock = type(mock_text_block)

        async def fake_query(prompt: str, options: object):  # type: ignore[misc]
            yield mock_assistant_msg

        mock_sdk.query = fake_query

        with patch.dict("sys.modules", {"claude_agent_sdk": mock_sdk}):
            result = await client._run_query(
                model="claude-sonnet-4-6",
                system_prompt="system",
                user_prompt="hello",
                max_turns=5,
            )

        assert result.stop_reason == "end_turn"
        assert isinstance(result, InvocationResult)
