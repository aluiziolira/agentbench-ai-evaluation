"""Dispatcher package for AgentBench.

The dispatcher handles workflow step execution by loading cases, rendering prompts,
invoking agent adapters, and persisting raw I/O.
"""

from agentbench.dispatcher.adapters import (
    ADAPTER_REGISTRY,
    AgentAdapter,
    AnthropicAdapter,
    OpenAIAdapter,
)
from agentbench.dispatcher.dispatcher import StepDispatcher

__all__ = [
    "AgentAdapter",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "ADAPTER_REGISTRY",
    "StepDispatcher",
]
