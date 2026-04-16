"""Base agent adapter protocol for AgentBench.

This module defines the AgentAdapter protocol that all provider adapters
must implement, ensuring a consistent interface for invoking AI agents.
"""

from typing import Any, Protocol, runtime_checkable

from agentbench.models.run import EvaluationRun
from agentbench.models.workflow import StepDefinition


@runtime_checkable
class AgentAdapter(Protocol):
    """Protocol for agent adapters.

    All agent adapters must implement this interface to be usable
    by the step dispatcher. The protocol ensures consistent invocation
    behavior across different AI providers (e.g., OpenAI, Anthropic).

    Attributes:
        agent_id: Unique identifier for this agent adapter.

    Example:
        >>> class MyAdapter:
        ...     agent_id = "my-agent"
        ...
        ...     async def invoke(self, step, run, conversation_history):
        ...         # Invocation logic here
        ...         return ("response text", 1500)
    """

    agent_id: str

    async def invoke(
        self,
        step: StepDefinition,
        run: EvaluationRun,
        conversation_history: list[dict[str, Any]],
    ) -> tuple[str, int]:
        """Invoke the agent, returning (response_text, latency_ms).

        Implementations should use temperature=0 for determinism and measure
        latency from request start to response completion.

        Raises:
            TimeoutError: If invocation exceeds the step timeout.
            RuntimeError: If the API call fails or returns invalid response.
        """
        ...
