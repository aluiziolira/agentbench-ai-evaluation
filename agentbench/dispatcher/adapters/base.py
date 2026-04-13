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
        """Invoke the agent for a workflow step.

        Args:
            step: The workflow step definition containing the prompt template.
            run: The evaluation run context with case and agent information.
            conversation_history: List of previous messages in the conversation,
                each as a dict with 'role' and 'content' keys.

        Returns:
            A tuple of (response_text, latency_ms) where:
                - response_text: The raw text response from the agent
                - latency_ms: Execution latency in milliseconds (non-negative)

        Raises:
            TimeoutError: If the agent invocation exceeds the step timeout.
            RuntimeError: If the API call fails or returns an invalid response.

        Note:
            Implementations should:
            - Use temperature=0 for determinism
            - Handle API timeouts gracefully
            - Measure latency from request start to response completion
            - Return meaningful error messages on failure
        """
        ...
