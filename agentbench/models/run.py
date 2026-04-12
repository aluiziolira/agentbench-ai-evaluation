"""Run models."""

from enum import StrEnum

from pydantic import BaseModel


class RunState(StrEnum):
    PENDING = "PENDING"
    STARTED = "STARTED"
    STEP_IN_PROGRESS = "STEP_IN_PROGRESS"
    STEP_SCORED = "STEP_SCORED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class EvaluationRun(BaseModel):
    run_id: str
    benchmark_id: str
    workflow_id: str
    workflow_version: str
    case_set_id: str
    case_id: str
    agent_id: str
    agent_config: dict
    state: RunState = RunState.PENDING
    current_step: int = 0
    created_at: str
    completed_at: str | None = None
