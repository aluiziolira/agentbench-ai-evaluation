"""Event models."""

from pydantic import BaseModel

EVALUATION_RUN_REQUESTED = "evaluation.run.requested"
EVALUATION_RUN_STARTED = "evaluation.run.started"
EVALUATION_RUN_COMPLETED = "evaluation.run.completed"
EVALUATION_RUN_FAILED = "evaluation.run.failed"
WORKFLOW_STEP_DISPATCHED = "workflow.step.dispatched"
WORKFLOW_STEP_TIMED_OUT = "workflow.step.timed_out"
WORKFLOW_COMPLETED = "workflow.completed"
AGENT_RESPONSE_RECEIVED = "agent.response.received"
STEP_SCORED = "step.scored"
BENCHMARK_REPORT_GENERATED = "benchmark.report.generated"

VALID_EVENT_TYPES = {
    EVALUATION_RUN_REQUESTED,
    EVALUATION_RUN_STARTED,
    EVALUATION_RUN_COMPLETED,
    EVALUATION_RUN_FAILED,
    WORKFLOW_STEP_DISPATCHED,
    WORKFLOW_STEP_TIMED_OUT,
    WORKFLOW_COMPLETED,
    AGENT_RESPONSE_RECEIVED,
    STEP_SCORED,
    BENCHMARK_REPORT_GENERATED,
}


class EventEnvelope(BaseModel):
    event_id: str
    event_type: str
    schema_version: str = "1.0"
    timestamp: str
    correlation_id: str
    payload: dict
