"""Agent adapters package for AgentBench.

This package provides provider-specific adapters for invoking AI agents.
Each adapter implements the AgentAdapter protocol and handles the specifics
of communicating with a particular AI provider (OpenAI, Anthropic, etc.).

Example:
    >>> from agentbench.dispatcher.adapters import ADAPTER_REGISTRY
    >>> adapter = ADAPTER_REGISTRY["gpt-4o-mini"]
    >>> text, latency = await adapter.invoke(step, run, [])
"""

from collections.abc import Callable, Iterator, MutableMapping

from agentbench.dispatcher.adapters.anthropic_adapter import AnthropicAdapter
from agentbench.dispatcher.adapters.base import AgentAdapter
from agentbench.dispatcher.adapters.openai_adapter import OpenAIAdapter


class _AdapterRegistry(MutableMapping[str, AgentAdapter]):
    """Lazy-initializing adapter registry.

    Adapters are created on first access to avoid requiring
    API keys at module import time.
    """

    _factories: dict[str, Callable[[], AgentAdapter]] = {
        "gpt-4o-mini": lambda: OpenAIAdapter(model="gpt-4o-mini"),
        "claude-haiku-4-5": lambda: AnthropicAdapter(model="claude-haiku-4-5-20251001"),
    }

    def __init__(self) -> None:
        self._instances: dict[str, AgentAdapter] = {}

    def __getitem__(self, key: str) -> AgentAdapter:
        """Get adapter, creating it if needed."""
        if key not in self._instances and key in self._factories:
            # Create adapter on first access
            self._instances[key] = self._factories[key]()
        return self._instances[key]

    def __setitem__(self, key: str, value: AgentAdapter) -> None:
        """Store an adapter instance."""
        self._instances[key] = value

    def __delitem__(self, key: str) -> None:
        """Delete a cached adapter instance."""
        del self._instances[key]

    def __contains__(self, key: object) -> bool:
        """Check if key is a supported adapter."""
        return key in self._factories or key in self._instances

    def __iter__(self) -> Iterator[str]:
        """Iterate over all supported adapter IDs."""
        return iter(self._factories.keys())

    def __len__(self) -> int:
        """Return the number of supported adapters."""
        return len(self._factories)


# Registry of all available agent adapters
# Maps agent_id to adapter instance (lazily initialized)
ADAPTER_REGISTRY: MutableMapping[str, AgentAdapter] = _AdapterRegistry()

__all__ = [
    "AgentAdapter",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "ADAPTER_REGISTRY",
]
