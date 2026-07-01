"""Event types and stream mapping for AgentBench.

This module provides:
- Re-export of event constants from models.events
- Stream-to-event mapping
- Helper functions for event type classification
- Payload validation for lean event payloads
"""

from typing import Any

# Re-export event constants from models.events
from agentbench.models.events import (
    AGENT_RESPONSE_RECEIVED,
    BENCHMARK_REPORT_GENERATED,
    EVALUATION_RUN_COMPLETED,
    EVALUATION_RUN_FAILED,
    EVALUATION_RUN_REQUESTED,
    EVALUATION_RUN_STARTED,
    STEP_SCORED,
    VALID_EVENT_TYPES,
    WORKFLOW_COMPLETED,
    WORKFLOW_STEP_DISPATCHED,
    WORKFLOW_STEP_TIMED_OUT,
    EventEnvelope,
)

# Stream keys
STREAM_EVAL_RUNS = "stream:eval-runs"
STREAM_EVAL_STEPS = "stream:eval-steps"
STREAM_SCORES = "stream:scores"
STREAM_REPORTS = "stream:reports"

# All stream keys
STREAM_KEYS = {
    STREAM_EVAL_RUNS,
    STREAM_EVAL_STEPS,
    STREAM_SCORES,
    STREAM_REPORTS,
}

# Allowed payload fields
ALLOWED_PAYLOAD_FIELDS = {
    "benchmark_id",
    "run_id",
    "workflow_id",
    "agent_id",
    "case_set_id",
    "case_id",
    "step_id",
    # Additional allowed metadata fields
    "event_id",
    "timestamp",
    "schema_version",
    "correlation_id",
    "status",
    "error",
    "latency_ms",
    "score",
    "strategy",
    "raw_score",
    "weight",
    "weighted_score",
    "passed",
    "details",
}

# Forbidden payload content patterns (field names or content patterns)
FORBIDDEN_PAYLOAD_PATTERNS = {
    "diff_content",
    "diff_patch",
    "full_diff",
    "ticket_content",
    "ticket_text",
    "full_ticket",
    "workflow_definition",
    "full_workflow",
    "ground_truth",
    "expected_findings",
    "raw_response",
    "agent_output",
    "response_text",
}

# Maximum payload size in bytes (1MB to prevent large artifacts)
MAX_PAYLOAD_SIZE = 1024 * 1024


def get_stream_for_event(event_type: str) -> str:
    """Get the appropriate stream for an event type.

    Mapping:
    - stream:eval-runs: evaluation.run.*
    - stream:eval-steps: workflow.step.*, agent.response.received
    - stream:scores: step.scored, workflow.completed
    - stream:reports: benchmark.report.generated

    Args:
        event_type: The event type string.

    Returns:
        The stream key for this event type.

    Raises:
        ValueError: If the event type is unknown.
    """
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Unknown event type: {event_type}")

    # stream:eval-runs -> evaluation.run.*
    if event_type.startswith("evaluation.run."):
        return STREAM_EVAL_RUNS

    # stream:eval-steps -> workflow.step.*, agent.response.received
    if event_type.startswith("workflow.step.") or event_type == AGENT_RESPONSE_RECEIVED:
        return STREAM_EVAL_STEPS

    # stream:scores -> step.scored, workflow.completed
    if event_type in (STEP_SCORED, WORKFLOW_COMPLETED):
        return STREAM_SCORES

    # stream:reports -> benchmark.report.generated
    if event_type == BENCHMARK_REPORT_GENERATED:
        return STREAM_REPORTS

    # Should never reach here if VALID_EVENT_TYPES is complete
    raise ValueError(f"Event type '{event_type}' has no stream mapping")


def is_eval_run_event(event_type: str) -> bool:
    """Check if event type is an evaluation.run.* event.

    Args:
        event_type: The event type string.

    Returns:
        True if this is an eval run event.
    """
    return event_type.startswith("evaluation.run.")


def is_workflow_step_event(event_type: str) -> bool:
    """Check if event type is a workflow.step.* event.

    Args:
        event_type: The event type string.

    Returns:
        True if this is a workflow step event.
    """
    return event_type.startswith("workflow.step.")


def get_event_types_for_stream(stream: str) -> set[str]:
    """Get all event types that belong to a stream.

    Args:
        stream: The stream key.

    Returns:
        Set of event types for this stream.

    Raises:
        ValueError: If the stream key is unknown.
    """
    if stream not in STREAM_KEYS:
        raise ValueError(f"Unknown stream: {stream}")

    mapping: dict[str, set[str]] = {
        STREAM_EVAL_RUNS: {
            EVALUATION_RUN_REQUESTED,
            EVALUATION_RUN_STARTED,
            EVALUATION_RUN_COMPLETED,
            EVALUATION_RUN_FAILED,
        },
        STREAM_EVAL_STEPS: {
            WORKFLOW_STEP_DISPATCHED,
            WORKFLOW_STEP_TIMED_OUT,
            AGENT_RESPONSE_RECEIVED,
        },
        STREAM_SCORES: {
            STEP_SCORED,
            WORKFLOW_COMPLETED,
        },
        STREAM_REPORTS: {
            BENCHMARK_REPORT_GENERATED,
        },
    }

    return mapping[stream]


def _check_forbidden_fields(payload: dict[str, Any], path: str = "") -> list[str]:
    """Recursively check for forbidden field names in payload.

    Args:
        payload: The payload dictionary to check.
        path: Current path for nested error reporting.

    Returns:
        List of forbidden field paths found.
    """
    violations: list[str] = []

    for key, value in payload.items():
        current_path = f"{path}.{key}" if path else key

        # Check if key matches any forbidden pattern
        key_lower = key.lower()
        for pattern in FORBIDDEN_PAYLOAD_PATTERNS:
            if pattern in key_lower:
                violations.append(current_path)
                break

        # Recursively check nested dicts
        if isinstance(value, dict):
            violations.extend(_check_forbidden_fields(value, current_path))

        # Check list items
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    violations.extend(_check_forbidden_fields(item, f"{current_path}[{i}]"))

    return violations


def _check_content_size(payload: dict[str, Any]) -> bool:
    """Check if payload content size is within limits.

    Args:
        payload: The payload dictionary to check.

    Returns:
        True if payload is within size limits.
    """
    import json

    try:
        payload_json = json.dumps(payload)
        return len(payload_json.encode("utf-8")) <= MAX_PAYLOAD_SIZE
    except (TypeError, ValueError):
        # If we can't serialize, assume it's too large
        return False


def validate_payload(payload: dict[str, Any]) -> bool:
    """Validate that a payload follows lean payload rules.

    Disallowed payload contents:
    - full diff contents
    - full ticket contents
    - full workflow definitions
    - full ground-truth documents
    - raw agent responses larger than metadata requirement

    Allowed fields:
    - benchmark_id, run_id, workflow_id, agent_id, case_set_id, case_id, step_id

    Args:
        payload: The payload dictionary to validate.

    Returns:
        True if payload is valid (lean), False otherwise.

    Raises:
        ValueError: If payload is invalid, with details about violations.
    """
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a dictionary")

    # Check for forbidden fields
    forbidden = _check_forbidden_fields(payload)
    if forbidden:
        raise ValueError(
            f"Payload contains forbidden fields: {', '.join(forbidden)}. "
            "Large artifacts must stay in storage, not events."
        )

    # Check payload size
    if not _check_content_size(payload):
        raise ValueError(
            f"Payload exceeds maximum size of {MAX_PAYLOAD_SIZE} bytes. "
            "Large artifacts must stay in storage, not events."
        )

    return True


def validate_event_envelope(envelope: EventEnvelope) -> bool:
    """Validate an event envelope including payload.

    Args:
        envelope: The EventEnvelope to validate.

    Returns:
        True if envelope is valid.

    Raises:
        ValueError: If envelope or payload is invalid.
    """
    # Validate event type
    if envelope.event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Invalid event type: {envelope.event_type}")

    # Validate correlation_id matches run_id for run-scoped events
    if is_eval_run_event(envelope.event_type) or envelope.event_type in (
        WORKFLOW_STEP_DISPATCHED,
        WORKFLOW_STEP_TIMED_OUT,
        AGENT_RESPONSE_RECEIVED,
        STEP_SCORED,
        WORKFLOW_COMPLETED,
    ):
        payload_run_id = envelope.payload.get("run_id")
        if payload_run_id and envelope.correlation_id != payload_run_id:
            raise ValueError(
                f"correlation_id ({envelope.correlation_id}) must equal "
                f"run_id ({payload_run_id}) for run-scoped events"
            )

    # Validate payload content
    validate_payload(envelope.payload)

    return True


__all__ = [
    # Stream keys
    "STREAM_EVAL_RUNS",
    "STREAM_EVAL_STEPS",
    "STREAM_SCORES",
    "STREAM_REPORTS",
    "STREAM_KEYS",
    # Event constants (re-exported)
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
