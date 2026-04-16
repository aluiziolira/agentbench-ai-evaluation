"""Base scoring strategy protocol for AgentBench.

This module defines the ScoringStrategy protocol that all scoring strategies
must implement, ensuring a consistent interface for scoring agent responses.
"""

from typing import Protocol, runtime_checkable

from agentbench.cases.models import ReviewCaseDefinition
from agentbench.models.results import StepScore
from agentbench.models.workflow import StepDefinition


@runtime_checkable
class ScoringStrategy(Protocol):
    """Protocol for scoring strategies.

    All scoring strategies must implement this interface to be usable
    by the scoring engine. The protocol ensures consistent scoring behavior
    across different strategies (e.g., finding_match, llm_judge).

    Attributes:
        strategy_id: Unique identifier for this scoring strategy.

    Example:
        >>> class MyStrategy:
        ...     strategy_id = "my_strategy"
        ...
        ...     async def score(self, step, response_text, run_id, latency_ms, case):
        ...         # Scoring logic here
        ...         return StepScore(...)
    """

    strategy_id: str

    async def score(
        self,
        step: StepDefinition,
        response_text: str,
        run_id: str,
        latency_ms: int,
        case: ReviewCaseDefinition,
    ) -> StepScore:
        """Score an agent response. Handle parse failures gracefully (typically 0.0 with explanatory details)."""
        ...
