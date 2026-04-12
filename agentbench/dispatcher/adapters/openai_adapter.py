"""OpenAI agent adapter for AgentBench.

This module provides the OpenAIAdapter class for invoking OpenAI models
via the AsyncOpenAI client.
"""

import os
import time
from typing import Any

from openai import AsyncOpenAI, AuthenticationError, RateLimitError

from agentbench.dispatcher.adapters.base import AgentAdapter
from agentbench.models.run import EvaluationRun
from agentbench.models.workflow import StepDefinition


class OpenAIAdapter:
    """Adapter for invoking OpenAI models.

        This adapter uses the openai.AsyncOpenAI client to invoke models like
    gpt-4o-mini with temperature=0 for deterministic responses.

        Attributes:
            agent_id: Unique identifier for this agent (e.g., "gpt-4o-mini").
            model: The OpenAI model name to use.
            temperature: Sampling temperature (default 0 for determinism).
            client: The AsyncOpenAI client instance.

        Example:
            >>> adapter = OpenAIAdapter(model="gpt-4o-mini")
            >>> text, latency = await adapter.invoke(step, run, [])
    """

    def __init__(
        self,
        model: str,
        temperature: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        """Initialize the OpenAI adapter.

        Args:
            model: The OpenAI model name (e.g., "gpt-4o-mini").
            temperature: Sampling temperature (default 0.0 for determinism).
            api_key: Optional API key. If not provided, reads from OPENAI_API_KEY
                environment variable.

        Raises:
            ValueError: If no API key is provided or found in environment.
        """
        self.agent_id = model
        self.model = model
        self.temperature = temperature

        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OpenAI API key required. Provide via api_key parameter "
                "or OPENAI_API_KEY environment variable."
            )

        self.client = AsyncOpenAI(api_key=api_key)

    async def invoke(
        self,
        step: StepDefinition,
        run: EvaluationRun,
        conversation_history: list[dict],
    ) -> tuple[str, int]:
        """Invoke the OpenAI model for a workflow step.

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
        import logging

        logger = logging.getLogger(__name__)

        # Build messages from conversation history + new prompt
        messages: list[dict[str, Any]] = list(conversation_history)
        messages.append({"role": "user", "content": step.input})

        logger.info(
            f"[OPENAI] Invoking model={self.model}, agent_id={self.agent_id}, prompt_length={len(step.input)}"
        )
        logger.info(f"[OPENAI] Prompt preview: {step.input[:200]}...")

        start_time = time.perf_counter()

        try:
            # Convert timeout_ms to seconds for asyncio.wait_for
            timeout_seconds = step.timeout_ms / 1000.0

            logger.info(f"[OPENAI] Making API call with timeout={timeout_seconds}s")
            response = await self._invoke_with_timeout(
                messages=messages,
                timeout_seconds=timeout_seconds,
            )

            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            logger.info(f"[OPENAI] API call successful, elapsed_ms={elapsed_ms}")

            # Extract response text
            if not response.choices:
                logger.error("[OPENAI] Response contains no choices")
                raise RuntimeError("OpenAI response contains no choices")

            message = response.choices[0].message
            if message.content is None:
                logger.error("[OPENAI] Response message has no content")
                raise RuntimeError("OpenAI response message has no content")

            logger.info(f"[OPENAI] Response received: length={len(message.content)}")
            return (message.content, elapsed_ms)

        except TimeoutError:
            logger.warning("[OPENAI] Request timed out")
            raise
        except Exception as e:
            logger.error(f"[OPENAI] API error: {e}")
            # Wrap API errors in RuntimeError
            raise RuntimeError(f"OpenAI API error: {e}") from e

    async def _invoke_with_timeout(
        self,
        messages: list[dict[str, Any]],
        timeout_seconds: float,
    ) -> Any:
        """Make the OpenAI API call with timeout handling.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            timeout_seconds: Maximum time to wait for response.

        Returns:
            The OpenAI API response.

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
        except TimeoutError as e:
            raise TimeoutError(f"OpenAI request timed out after {timeout_seconds}s") from e

    async def _make_api_call(self, messages: list[dict[str, Any]]) -> Any:
        """Make the actual OpenAI API call.

        Args:
            messages: List of message dicts with 'role' and 'content'.

        Returns:
            The OpenAI API response.

        Raises:
            RuntimeError: For authentication or rate limit errors.
        """
        try:
            return await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
            )
        except AuthenticationError as e:
            raise RuntimeError(f"OpenAI authentication failed: {e}") from e
        except RateLimitError as e:
            raise RuntimeError(f"OpenAI rate limit exceeded: {e}") from e


# Type checking: OpenAIAdapter satisfies AgentAdapter protocol
_: AgentAdapter = OpenAIAdapter(model="gpt-4o-mini", api_key="test")
