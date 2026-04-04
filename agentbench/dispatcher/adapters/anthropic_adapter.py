"""Anthropic agent adapter for AgentBench.

This module provides the AnthropicAdapter class for invoking Anthropic models
via the AsyncAnthropic client.
"""

import os
import time
from typing import Any

from anthropic import AnthropicError, AsyncAnthropic, RateLimitError

from agentbench.dispatcher.adapters.base import AgentAdapter
from agentbench.models.run import EvaluationRun
from agentbench.models.workflow import StepDefinition


class AnthropicAdapter:
    """Adapter for invoking Anthropic Claude models.

    This adapter uses the anthropic.AsyncAnthropic client to invoke models like
    claude-haiku-4-5 with temperature=0 for deterministic responses.

    Attributes:
        agent_id: Unique identifier for this agent (e.g., "claude-haiku-4-5").
        model: The Anthropic model name to use.
        temperature: Sampling temperature (default 0 for determinism).
        client: The AsyncAnthropic client instance.

    Example:
        >>> adapter = AnthropicAdapter(model="claude-haiku-4-5-20251001")
        >>> text, latency = await adapter.invoke(step, run, [])
    """

    def __init__(
        self,
        model: str,
        temperature: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        """Initialize the Anthropic adapter.

        Args:
            model: The Anthropic model name (e.g., "claude-haiku-4-5-20251001").
            temperature: Sampling temperature (default 0.0 for determinism).
            api_key: Optional API key. If not provided, reads from ANTHROPIC_API_KEY
                environment variable.

        Raises:
            ValueError: If no API key is provided or found in environment.
        """
        self.agent_id = model.split("-2025")[0] if "-2025" in model else model
        self.model = model
        self.temperature = temperature

        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "Anthropic API key required. Provide via api_key parameter "
                "or ANTHROPIC_API_KEY environment variable."
            )

        self.client = AsyncAnthropic(api_key=api_key)

    async def invoke(
        self,
        step: StepDefinition,
        run: EvaluationRun,
        conversation_history: list[dict],
    ) -> tuple[str, int]:
        """Invoke the Anthropic model for a workflow step.

        Args:
            step: The workflow step with prompt template.
            run: The evaluation run context.
            conversation_history: Previous conversation messages.

        Returns:
            Tuple of (response_text, latency_ms).

        Raises:
            TimeoutError: If the request exceeds step.timeout_ms.
            RuntimeError: If the API call fails.
        """
        # Build messages from conversation history for Anthropic format
        messages = self._build_messages(conversation_history, step.input)

        start_time = time.perf_counter()

        try:
            # Convert timeout_ms to seconds for asyncio.wait_for
            timeout_seconds = step.timeout_ms / 1000.0

            response = await self._invoke_with_timeout(
                messages=messages,
                timeout_seconds=timeout_seconds,
            )

            elapsed_ms = int((time.perf_counter() - start_time) * 1000)

            # Extract response text
            if not response.content:
                raise RuntimeError("Anthropic response contains no content")

            # Get text from the first content block
            content_block = response.content[0]
            if content_block.type != "text":
                raise RuntimeError(f"Unexpected content type: {content_block.type}")

            return (content_block.text, elapsed_ms)

        except TimeoutError:
            raise
        except Exception as e:
            # Wrap API errors in RuntimeError
            raise RuntimeError(f"Anthropic API error: {e}") from e

    def _build_messages(
        self,
        conversation_history: list[dict],
        prompt: str,
    ) -> list[dict[str, Any]]:
        """Build messages list for Anthropic API.

        Args:
            conversation_history: Previous conversation messages.
            prompt: The current prompt to send.

        Returns:
            List of message dicts formatted for Anthropic API.
        """
        messages: list[dict[str, Any]] = []

        # Add conversation history
        for msg in conversation_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Anthropic uses "assistant" instead of some other role names
            if role == "assistant":
                messages.append({"role": "assistant", "content": content})
            else:
                # Default to user role
                messages.append({"role": "user", "content": content})

        # Add the current prompt
        messages.append({"role": "user", "content": prompt})

        return messages

    async def _invoke_with_timeout(
        self,
        messages: list[dict[str, Any]],
        timeout_seconds: float,
    ) -> Any:
        """Make the Anthropic API call with timeout handling.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            timeout_seconds: Maximum time to wait for response.

        Returns:
            The Anthropic API response.

        Raises:
            TimeoutError: If the request times out.
            RuntimeError: For API authentication or rate limit errors.
        """
        import asyncio

        try:
            return await asyncio.wait_for(
                self._make_api_call(messages),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as e:
            raise TimeoutError(f"Anthropic request timed out after {timeout_seconds}s") from e

    async def _make_api_call(self, messages: list[dict[str, Any]]) -> Any:
        """Make the actual Anthropic API call.

        Args:
            messages: List of message dicts with 'role' and 'content'.

        Returns:
            The Anthropic API response.

        Raises:
            RuntimeError: For authentication or rate limit errors.
        """
        try:
            return await self.client.messages.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=4096,  # Required parameter for Anthropic
            )
        except RateLimitError as e:
            raise RuntimeError(f"Anthropic rate limit exceeded: {e}") from e
        except AnthropicError as e:
            raise RuntimeError(f"Anthropic API error: {e}") from e


# Type checking: AnthropicAdapter satisfies AgentAdapter protocol
_: AgentAdapter = AnthropicAdapter(model="claude-haiku-4-5-20251001", api_key="test")
