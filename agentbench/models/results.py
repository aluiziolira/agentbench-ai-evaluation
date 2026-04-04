from typing import Any

from pydantic import BaseModel


class StepScore(BaseModel):
    run_id: str
    case_id: str
    step_id: str
    strategy: str
    raw_score: float
    weight: float = 1.0
    weighted_score: float
    latency_ms: int
    passed: bool
    scoring_failed: bool = False
    error_type: str | None = None  # None | "api_error" | "parse_error"
    details: dict[str, Any] = {}


class RunReport(BaseModel):
    run_id: str
    benchmark_id: str
    case_id: str
    case_tags: list[str]
    agent_id: str
    workflow_id: str
    total_score: float
    step_scores: list[StepScore]
    total_latency_ms: int
    completed_at: str
    scoring_failures: int = 0


class AgentSummary(BaseModel):
    agent_id: str
    avg_score: float
    p50_latency_ms: int
    p95_latency_ms: int
    failure_rate: float
    step_breakdown: dict[str, float]
    scoring_failure_rate: float = 0.0


class BenchmarkReport(BaseModel):
    benchmark_id: str
    workflow_id: str
    case_set_id: str
    created_at: str
    case_count: int
    agents: list[AgentSummary]
    per_case_scores: dict[str, dict[str, float | None]]
    per_case_topics: dict[str, str] = {}
