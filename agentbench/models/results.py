"""Results models."""

from pydantic import BaseModel


class StepScore(BaseModel):
    run_id: str
    case_id: str
    step_id: str
    strategy: str
    raw_score: float
    weighted_score: float
    latency_ms: int
    passed: bool
    details: dict = {}


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


class AgentSummary(BaseModel):
    agent_id: str
    avg_score: float
    p50_latency_ms: int
    p95_latency_ms: int
    failure_rate: float
    step_breakdown: dict[str, float]


class BenchmarkReport(BaseModel):
    benchmark_id: str
    workflow_id: str
    case_set_id: str
    created_at: str
    case_count: int
    agents: list[AgentSummary]
    per_case_scores: dict[str, dict[str, float]]
