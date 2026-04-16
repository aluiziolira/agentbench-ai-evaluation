"""Scoring package for AgentBench.

This package provides scoring functionality for evaluating agent responses
against ground truth data using configurable strategies.
"""

from agentbench.scoring.engine import (
    RawIONotFoundError,
    ScoringEngine,
    UnknownStrategyError,
)
from agentbench.scoring.strategies.base import ScoringStrategy
from agentbench.scoring.strategies.finding_match import FindingMatchStrategy
from agentbench.scoring.strategies.llm_judge import LLMJudgeStrategy

__all__ = [
    # Engine
    "ScoringEngine",
    "UnknownStrategyError",
    "RawIONotFoundError",
    # Strategies
    "ScoringStrategy",
    "FindingMatchStrategy",
    "LLMJudgeStrategy",
]
