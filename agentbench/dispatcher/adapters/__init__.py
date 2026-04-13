"""Agent adapters package for AgentBench.

This package provides provider-specific adapters for invoking AI agents.
Each adapter implements the AgentAdapter protocol and handles the specifics
of communicating with a particular AI provider (OpenAI, Anthropic, etc.).

Example:
    >>> from agentbench.dispatcher.adapters import ADAPTER_REGISTRY
    >>> adapter = ADAPTER_REGISTRY["gpt-4o-mini"]
    >>> text, latency = await adapter.invoke(step, run, [])
"""

from collections.abc import Callable, Iterator

from agentbench.dispatcher.adapters.anthropic_adapter import AnthropicAdapter
from agentbench.dispatcher.adapters.base import AgentAdapter
from agentbench.dispatcher.adapters.openai_adapter import OpenAIAdapter


class _AdapterRegistry(dict[str, AgentAdapter]):
    """Lazy-initializing adapter registry.

    Adapters are created on first access to avoid requiring
    API keys at module import time.
    """

    _factories: dict[str, Callable[[], AgentAdapter]] = {
        "gpt-4o-mini": lambda: OpenAIAdapter(model="gpt-4o-mini"),
        "claude-haiku-4-5": lambda: AnthropicAdapter(model="claude-haiku-4-5-20251001"),
    }

    def __getitem__(self, key: str) -> AgentAdapter:
        """Get adapter, creating it if needed."""
        # Use dict.__contains__ to check underlying dict, not our __contains__ override
        if not super().__contains__(key) and key in self._factories:
            # Create adapter on first access
            self[key] = self._factories[key]()
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        """Check if key is a supported adapter."""
        return key in self._factories or super().__contains__(key)

    def __iter__(self) -> Iterator[str]:
        """Iterate over all supported adapter IDs."""
        return iter(self._factories.keys())

    def items(self):
        """Return all adapter ID -> adapter pairs (creates all adapters)."""
        for key in self._factories:
            if not super().__contains__(key):
                self[key] = self._factories[key]()
        return super().items()

    def values(self):
        """Return all adapters (creates all adapters)."""
        for key in self._factories:
            if not super().__contains__(key):
                self[key] = self._factories[key]()
        return super().values()

    def get(self, key: str, default=None):
        """Get adapter with optional default."""
        try:
            return self[key]
        except KeyError:
            return default


# Registry of all available agent adapters
# Maps agent_id to adapter instance (lazily initialized)
ADAPTER_REGISTRY: dict[str, AgentAdapter] = _AdapterRegistry()

__all__ = [
    "AgentAdapter",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "ADAPTER_REGISTRY",
]
