"""AgentBench events package.

This package provides event bus functionality for the event-driven architecture,
including stream mapping, payload validation, and Redis Streams integration.
"""

from agentbench.events.bus import EventBus
from agentbench.events.types import (
    AGENT_RESPONSE_RECEIVED,
    ALLOWED_PAYLOAD_FIELDS,
    BENCHMARK_REPORT_GENERATED,
    EVALUATION_RUN_COMPLETED,
    EVALUATION_RUN_FAILED,
    EVALUATION_RUN_REQUESTED,
    EVALUATION_RUN_STARTED,
    EventEnvelope,
    FORBIDDEN_PAYLOAD_PATTERNS,
    MAX_PAYLOAD_SIZE,
    STEP_SCORED,
    STREAM_EVAL_RUNS,
    STREAM_EVAL_STEPS,
    STREAM_KEYS,
    STREAM_REPORTS,
    STREAM_SCORES,
    VALID_EVENT_TYPES,
    WORKFLOW_COMPLETED,
    WORKFLOW_STEP_DISPATCHED,
    WORKFLOW_STEP_TIMED_OUT,
    get_event_types_for_stream,
    get_stream_for_event,
    is_eval_run_event,
    is_workflow_step_event,
    validate_event_envelope,
    validate_payload,
)

__version__ = "0.1.0"

__all__ = [
    # EventBus
    "EventBus",
    # Stream keys
    "STREAM_EVAL_RUNS",
    "STREAM_EVAL_STEPS",
    "STREAM_SCORES",
    "STREAM_REPORTS",
    "STREAM_KEYS",
    # Event type constants
    "EVALUATION_RUN_REQUESTED",
    "EVALUATION_RUN_STARTED",
    "EVALUATION_RUN_COMPLETED",
    "EVALUATION_RUN_FAILED",
    "WORKFLOW_STEP_DISPATCHED",
    "WORKFLOW_STEP_TIMED_OUT",
    "WORKFLOW_COMPLETED",
    "AGENT_RESPONSE_RECEIVED",
    "STEP_SCORED",
    "BENCHMARK_REPORT_GENERATED",
    "VALID_EVENT_TYPES",
    # Event envelope
    "EventEnvelope",
    # Helper functions
    "get_stream_for_event",
    "get_event_types_for_stream",
    "is_eval_run_event",
    "is_workflow_step_event",
    "validate_payload",
    "validate_event_envelope",
    # Validation constants
    "ALLOWED_PAYLOAD_FIELDS",
    "FORBIDDEN_PAYLOAD_PATTERNS",
    "MAX_PAYLOAD_SIZE",
]
