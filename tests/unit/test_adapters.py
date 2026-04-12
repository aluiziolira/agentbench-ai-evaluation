"""Unit tests for agent adapters.

Tests cover OpenAI and Anthropic adapters with mocked HTTP calls,
request shape validation, response parsing, latency measurement,
and error handling.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentbench.dispatcher.adapters import (
    ADAPTER_REGISTRY,
    AgentAdapter,
    AnthropicAdapter,
    OpenAIAdapter,
)
from agentbench.models import EvaluationRun, RunState, ScoringConfig, StepDefinition


def generate_uuid() -> str:
    """Generate a UUID4 string."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """Get current UTC time as ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def create_test_step(prompt: str = "Test prompt") -> StepDefinition:
    """Create a test step definition."""
    return StepDefinition(
        step_id="s1_test",
        order=0,
        input=prompt,
        timeout_ms=5000,
        scoring=ScoringConfig(strategy="finding_match"),
    )


def create_test_run(agent_id: str = "gpt-4o-mini") -> EvaluationRun:
    """Create a test evaluation run."""
    return EvaluationRun(
        run_id=generate_uuid(),
        benchmark_id=generate_uuid(),
        workflow_id="wf_pr_review_v1",
        workflow_version="1.0.0",
        case_set_id="pr_review_cases_v1",
        case_id="pr_001",
        agent_id=agent_id,
        agent_config={"temperature": 0},
        state=RunState.PENDING,
        current_step=0,
        created_at=now_iso(),
    )


class TestOpenAIAdapter:
    """Tests for OpenAIAdapter."""

    def test_init_with_api_key(self) -> None:
        """Test initialization with explicit API key."""
        adapter = OpenAIAdapter(model="gpt-4o-mini", api_key="test-key")
        assert adapter.agent_id == "gpt-4o-mini"
        assert adapter.model == "gpt-4o-mini"
        assert adapter.temperature == 0.0

    def test_init_with_custom_temperature(self) -> None:
        """Test initialization with custom temperature."""
        adapter = OpenAIAdapter(model="gpt-4o-mini", api_key="test-key", temperature=0.5)
        assert adapter.temperature == 0.5

    def test_init_without_api_key_raises(self, monkeypatch) -> None:
        """Test that initialization fails without API key."""
        # Ensure env var is not set
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with pytest.raises(ValueError, match="OpenAI API key required"):
            OpenAIAdapter(model="gpt-4o-mini")

    def test_init_with_env_var(self, monkeypatch) -> None:
        """Test initialization with API key from environment."""
        monkeypatch.setenv("OPENAI_API_KEY", "env-test-key")

        adapter = OpenAIAdapter(model="gpt-4o-mini")
        assert adapter.agent_id == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_invoke_success(self) -> None:
        """Test successful invocation returns text and latency."""
        adapter = OpenAIAdapter(model="gpt-4o-mini", api_key="test-key")

        # Mock the API response
        mock_message = MagicMock()
        mock_message.content = "Test response"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        # Patch the client's chat.completions.create
        with patch.object(
            adapter.client.chat.completions,
            "create",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            step = create_test_step("Test prompt")
            run = create_test_run()

            text, latency = await adapter.invoke(step, run, [])

            assert text == "Test response"
            assert latency >= 0  # Latency should be non-negative

    @pytest.mark.asyncio
    async def test_invoke_with_conversation_history(self) -> None:
        """Test invocation includes conversation history in messages."""
        adapter = OpenAIAdapter(model="gpt-4o-mini", api_key="test-key")

        mock_message = MagicMock()
        mock_message.content = "Response"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        create_mock = AsyncMock(return_value=mock_response)

        with patch.object(
            adapter.client.chat.completions, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = create_mock

            step = create_test_step("Current prompt")
            run = create_test_run()
            history = [
                {"role": "user", "content": "Previous message"},
                {"role": "assistant", "content": "Previous response"},
            ]

            await adapter.invoke(step, run, history)

            # Verify the call was made
            assert mock_create.called
            call_args = mock_create.call_args[1]

            # Check messages include history + current prompt
            assert "messages" in call_args
            messages = call_args["messages"]
            assert len(messages) == 3
            assert messages[0] == {"role": "user", "content": "Previous message"}
            assert messages[1] == {"role": "assistant", "content": "Previous response"}
            assert messages[2] == {"role": "user", "content": "Current prompt"}

            # Check other parameters
            assert call_args["model"] == "gpt-4o-mini"
            assert call_args["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_invoke_uses_temperature_zero(self) -> None:
        """Test that invocation uses temperature=0 for determinism."""
        adapter = OpenAIAdapter(model="gpt-4o-mini", api_key="test-key")

        mock_message = MagicMock()
        mock_message.content = "Response"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch.object(
            adapter.client.chat.completions,
            "create",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_create:
            step = create_test_step()
            run = create_test_run()

            await adapter.invoke(step, run, [])

            call_args = mock_create.call_args[1]
            assert call_args["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_invoke_timeout(self) -> None:
        """Test that timeout is enforced."""
        adapter = OpenAIAdapter(model="gpt-4o-mini", api_key="test-key")

        # Mock a slow response that exceeds timeout
        async def slow_response(*args, **kwargs):
            import asyncio

            await asyncio.sleep(10)  # Sleep longer than timeout
            return MagicMock()

        with patch.object(
            adapter.client.chat.completions,
            "create",
            new_callable=AsyncMock,
            side_effect=slow_response,
        ):
            step = create_test_step()
            step.timeout_ms = 100  # Very short timeout
            run = create_test_run()

            with pytest.raises(TimeoutError):
                await adapter.invoke(step, run, [])

    @pytest.mark.asyncio
    async def test_invoke_empty_choices_raises_runtime_error(self) -> None:
        """Test that empty choices raises RuntimeError."""
        adapter = OpenAIAdapter(model="gpt-4o-mini", api_key="test-key")

        mock_response = MagicMock()
        mock_response.choices = []

        with patch.object(
            adapter.client.chat.completions,
            "create",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            step = create_test_step()
            run = create_test_run()

            with pytest.raises(RuntimeError, match="no choices"):
                await adapter.invoke(step, run, [])

    @pytest.mark.asyncio
    async def test_invoke_none_content_raises_runtime_error(self) -> None:
        """Test that None content raises RuntimeError."""
        adapter = OpenAIAdapter(model="gpt-4o-mini", api_key="test-key")

        mock_message = MagicMock()
        mock_message.content = None

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch.object(
            adapter.client.chat.completions,
            "create",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            step = create_test_step()
            run = create_test_run()

            with pytest.raises(RuntimeError, match="no content"):
                await adapter.invoke(step, run, [])

    @pytest.mark.asyncio
    async def test_invoke_api_error_raises_runtime_error(self) -> None:
        """Test that API errors are wrapped in RuntimeError."""
        adapter = OpenAIAdapter(model="gpt-4o-mini", api_key="test-key")

        with patch.object(
            adapter.client.chat.completions,
            "create",
            new_callable=AsyncMock,
            side_effect=Exception("API Error"),
        ):
            step = create_test_step()
            run = create_test_run()

            with pytest.raises(RuntimeError, match="OpenAI API error"):
                await adapter.invoke(step, run, [])

    def test_adapter_implements_protocol(self) -> None:
        """Test that OpenAIAdapter implements AgentAdapter protocol."""

        adapter = OpenAIAdapter(model="gpt-4o-mini", api_key="test-key")

        # This should not raise TypeError if the protocol is satisfied
        assert isinstance(adapter, AgentAdapter)


class TestAnthropicAdapter:
    """Tests for AnthropicAdapter."""

    def test_init_with_api_key(self) -> None:
        """Test initialization with explicit API key."""
        adapter = AnthropicAdapter(model="claude-haiku-4-5-20251001", api_key="test-key")
        # agent_id strips the date suffix
        assert adapter.agent_id == "claude-haiku-4-5"
        assert adapter.model == "claude-haiku-4-5-20251001"
        assert adapter.temperature == 0.0

    def test_init_without_date_suffix(self) -> None:
        """Test initialization with model without date suffix."""
        adapter = AnthropicAdapter(model="claude-haiku", api_key="test-key")
        assert adapter.agent_id == "claude-haiku"

    def test_init_with_custom_temperature(self) -> None:
        """Test initialization with custom temperature."""
        adapter = AnthropicAdapter(
            model="claude-haiku-4-5-20251001",
            api_key="test-key",
            temperature=0.5,
        )
        assert adapter.temperature == 0.5

    def test_init_without_api_key_raises(self, monkeypatch) -> None:
        """Test that initialization fails without API key."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        with pytest.raises(ValueError, match="Anthropic API key required"):
            AnthropicAdapter(model="claude-haiku-4-5-20251001")

    def test_init_with_env_var(self, monkeypatch) -> None:
        """Test initialization with API key from environment."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-test-key")

        adapter = AnthropicAdapter(model="claude-haiku-4-5-20251001")
        assert adapter.agent_id == "claude-haiku-4-5"

    @pytest.mark.asyncio
    async def test_invoke_success(self) -> None:
        """Test successful invocation returns text and latency."""
        adapter = AnthropicAdapter(model="claude-haiku-4-5-20251001", api_key="test-key")

        # Mock the API response
        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = "Test response"

        mock_response = MagicMock()
        mock_response.content = [mock_content]

        with patch.object(
            adapter.client.messages,
            "create",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            step = create_test_step("Test prompt")
            run = create_test_run(agent_id="claude-haiku-4-5")

            text, latency = await adapter.invoke(step, run, [])

            assert text == "Test response"
            assert latency >= 0

    @pytest.mark.asyncio
    async def test_invoke_with_conversation_history(self) -> None:
        """Test invocation includes conversation history."""
        adapter = AnthropicAdapter(model="claude-haiku-4-5-20251001", api_key="test-key")

        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = "Response"

        mock_response = MagicMock()
        mock_response.content = [mock_content]

        with patch.object(
            adapter.client.messages,
            "create",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_create:
            step = create_test_step("Current prompt")
            run = create_test_run(agent_id="claude-haiku-4-5")
            history = [
                {"role": "user", "content": "Previous message"},
                {"role": "assistant", "content": "Previous response"},
            ]

            await adapter.invoke(step, run, history)

            # Verify the call was made
            assert mock_create.called
            call_args = mock_create.call_args[1]

            # Check messages include history + current prompt
            assert "messages" in call_args
            messages = call_args["messages"]
            assert len(messages) == 3
            assert messages[0] == {"role": "user", "content": "Previous message"}
            assert messages[1] == {"role": "assistant", "content": "Previous response"}
            assert messages[2] == {"role": "user", "content": "Current prompt"}

            # Check other parameters
            assert call_args["model"] == "claude-haiku-4-5-20251001"
            assert call_args["temperature"] == 0.0
            assert call_args["max_tokens"] == 4096

    @pytest.mark.asyncio
    async def test_invoke_uses_temperature_zero(self) -> None:
        """Test that invocation uses temperature=0 for determinism."""
        adapter = AnthropicAdapter(model="claude-haiku-4-5-20251001", api_key="test-key")

        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = "Response"

        mock_response = MagicMock()
        mock_response.content = [mock_content]

        with patch.object(
            adapter.client.messages,
            "create",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_create:
            step = create_test_step()
            run = create_test_run(agent_id="claude-haiku-4-5")

            await adapter.invoke(step, run, [])

            call_args = mock_create.call_args[1]
            assert call_args["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_invoke_timeout(self) -> None:
        """Test that timeout is enforced."""
        adapter = AnthropicAdapter(model="claude-haiku-4-5-20251001", api_key="test-key")

        # Mock a slow response that exceeds timeout
        async def slow_response(*args, **kwargs):
            import asyncio

            await asyncio.sleep(10)
            return MagicMock(content=[MagicMock(type="text", text="")])

        with patch.object(
            adapter.client.messages,
            "create",
            new_callable=AsyncMock,
            side_effect=slow_response,
        ):
            step = create_test_step()
            step.timeout_ms = 100  # Very short timeout
            run = create_test_run(agent_id="claude-haiku-4-5")

            with pytest.raises(TimeoutError):
                await adapter.invoke(step, run, [])

    @pytest.mark.asyncio
    async def test_invoke_empty_content_raises_runtime_error(self) -> None:
        """Test that empty content raises RuntimeError."""
        adapter = AnthropicAdapter(model="claude-haiku-4-5-20251001", api_key="test-key")

        mock_response = MagicMock()
        mock_response.content = []

        with patch.object(
            adapter.client.messages,
            "create",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            step = create_test_step()
            run = create_test_run(agent_id="claude-haiku-4-5")

            with pytest.raises(RuntimeError, match="no content"):
                await adapter.invoke(step, run, [])

    @pytest.mark.asyncio
    async def test_invoke_non_text_content_raises_runtime_error(self) -> None:
        """Test that non-text content type raises RuntimeError."""
        adapter = AnthropicAdapter(model="claude-haiku-4-5-20251001", api_key="test-key")

        mock_content = MagicMock()
        mock_content.type = "image"  # Non-text type

        mock_response = MagicMock()
        mock_response.content = [mock_content]

        with patch.object(
            adapter.client.messages,
            "create",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            step = create_test_step()
            run = create_test_run(agent_id="claude-haiku-4-5")

            with pytest.raises(RuntimeError, match="Unexpected content type"):
                await adapter.invoke(step, run, [])

    @pytest.mark.asyncio
    async def test_invoke_api_error_raises_runtime_error(self) -> None:
        """Test that API errors are wrapped in RuntimeError."""
        adapter = AnthropicAdapter(model="claude-haiku-4-5-20251001", api_key="test-key")

        with patch.object(
            adapter.client.messages,
            "create",
            new_callable=AsyncMock,
            side_effect=Exception("API Error"),
        ):
            step = create_test_step()
            run = create_test_run(agent_id="claude-haiku-4-5")

            with pytest.raises(RuntimeError, match="Anthropic API error"):
                await adapter.invoke(step, run, [])

    def test_adapter_implements_protocol(self) -> None:
        """Test that AnthropicAdapter implements AgentAdapter protocol."""

        adapter = AnthropicAdapter(model="claude-haiku-4-5-20251001", api_key="test-key")

        # This should not raise TypeError if the protocol is satisfied
        assert isinstance(adapter, AgentAdapter)


class TestAdapterRegistry:
    """Tests for ADAPTER_REGISTRY."""

    def test_registry_contains_openai(self, monkeypatch) -> None:
        """Test that registry contains gpt-4o-mini adapter."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        assert "gpt-4o-mini" in ADAPTER_REGISTRY
        adapter = ADAPTER_REGISTRY["gpt-4o-mini"]
        assert isinstance(adapter, OpenAIAdapter)
        assert adapter.agent_id == "gpt-4o-mini"
        assert adapter.model == "gpt-4o-mini"
        assert adapter.temperature == 0.0

    def test_registry_contains_anthropic(self, monkeypatch) -> None:
        """Test that registry contains claude-haiku-4-5 adapter."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        assert "claude-haiku-4-5" in ADAPTER_REGISTRY
        adapter = ADAPTER_REGISTRY["claude-haiku-4-5"]
        assert isinstance(adapter, AnthropicAdapter)
        assert adapter.agent_id == "claude-haiku-4-5"
        assert adapter.model == "claude-haiku-4-5-20251001"
        assert adapter.temperature == 0.0

    def test_registry_adapters_implement_protocol(self, monkeypatch) -> None:
        """Test that all registry adapters implement AgentAdapter protocol."""
        # Set both env vars so adapters can be created
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        for agent_id, adapter in ADAPTER_REGISTRY.items():
            assert isinstance(adapter, AgentAdapter), f"{agent_id} must implement AgentAdapter"

    def test_registry_keys_match_agent_ids(self, monkeypatch) -> None:
        """Test that registry keys match the adapter agent_ids."""
        # Set both env vars so adapters can be created
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        for agent_id, adapter in ADAPTER_REGISTRY.items():
            assert adapter.agent_id == agent_id, (
                f"Registry key {agent_id} must match adapter.agent_id"
            )

