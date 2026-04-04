"""Workflow models."""

from pydantic import BaseModel
from typing import Literal


class ScoringConfig(BaseModel):
    strategy: Literal["finding_match", "llm_judge"]
    rubric: str | None = None
    weight: float = 1.0


class StepDefinition(BaseModel):
    step_id: str
    order: int
    input: str
    timeout_ms: int = 15000
    scoring: ScoringConfig


class WorkflowDefinition(BaseModel):
    workflow_id: str
    version: str
    status: Literal["draft", "published"]
    description: str
    steps: list[StepDefinition]
    scoring_aggregation: Literal["weighted_average"] = "weighted_average"
    created_at: str
    published_at: str | None = None
