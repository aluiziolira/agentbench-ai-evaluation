"""Unit tests for AgentBench events package.

Tests cover:
- Event envelope creation with correlation_id
- Payload validation (allowed vs disallowed fields)
- Stream mapping
- EventBus helpers
"""

import uuid
from datetime import UTC, datetime

import pytest

from agentbench.events import (
    AGENT_RESPONSE_RECEIVED,
    ALLOWED_PAYLOAD_FIELDS,
    BENCHMARK_REPORT_GENERATED,
    EVALUATION_RUN_COMPLETED,
    EVALUATION_RUN_FAILED,
    EVALUATION_RUN_REQUESTED,
    EVALUATION_RUN_STARTED,
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
    EventEnvelope,
    get_event_types_for_stream,
    get_stream_for_event,
    is_eval_run_event,
    is_workflow_step_event,
    validate_event_envelope,
    validate_payload,
)


def generate_uuid() -> str:
    """Generate a UUID4 string."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """Get current UTC time as ISO-8601 string."""
    return datetime.now(UTC).isoformat()


class TestStreamKeys:
    """Tests for stream key constants."""

    def test_all_streams_defined(self) -> None:
        """Test that all required streams are defined."""
        assert STREAM_EVAL_RUNS == "stream:eval-runs"
        assert STREAM_EVAL_STEPS == "stream:eval-steps"
        assert STREAM_SCORES == "stream:scores"
        assert STREAM_REPORTS == "stream:reports"

    def test_stream_keys_set(self) -> None:
        """Test STREAM_KEYS contains all streams."""
        assert len(STREAM_KEYS) == 4
        assert STREAM_EVAL_RUNS in STREAM_KEYS
        assert STREAM_EVAL_STEPS in STREAM_KEYS
        assert STREAM_SCORES in STREAM_KEYS
        assert STREAM_REPORTS in STREAM_KEYS


class TestEventConstants:
    """Tests for event type constants."""

    def test_all_event_types_exported(self) -> None:
        """Test all event types are available."""
        assert EVALUATION_RUN_REQUESTED == "evaluation.run.requested"
        assert EVALUATION_RUN_STARTED == "evaluation.run.started"
        assert EVALUATION_RUN_COMPLETED == "evaluation.run.completed"
        assert EVALUATION_RUN_FAILED == "evaluation.run.failed"
        assert WORKFLOW_STEP_DISPATCHED == "workflow.step.dispatched"
        assert WORKFLOW_STEP_TIMED_OUT == "workflow.step.timed_out"
        assert WORKFLOW_COMPLETED == "workflow.completed"
        assert AGENT_RESPONSE_RECEIVED == "agent.response.received"
        assert STEP_SCORED == "step.scored"
        assert BENCHMARK_REPORT_GENERATED == "benchmark.report.generated"

    def test_valid_event_types_set(self) -> None:
        """Test VALID_EVENT_TYPES contains all events."""
        assert len(VALID_EVENT_TYPES) == 10
        assert EVALUATION_RUN_REQUESTED in VALID_EVENT_TYPES
        assert BENCHMARK_REPORT_GENERATED in VALID_EVENT_TYPES


class TestStreamMapping:
    """Tests for stream-to-event mapping."""

    def test_eval_runs_stream(self) -> None:
        """Test evaluation.run.* events map to stream:eval-runs."""
        assert get_stream_for_event(EVALUATION_RUN_REQUESTED) == STREAM_EVAL_RUNS
        assert get_stream_for_event(EVALUATION_RUN_STARTED) == STREAM_EVAL_RUNS
        assert get_stream_for_event(EVALUATION_RUN_COMPLETED) == STREAM_EVAL_RUNS
        assert get_stream_for_event(EVALUATION_RUN_FAILED) == STREAM_EVAL_RUNS

    def test_eval_steps_stream(self) -> None:
        """Test workflow.step.* and agent.response.received map to stream:eval-steps."""
        assert get_stream_for_event(WORKFLOW_STEP_DISPATCHED) == STREAM_EVAL_STEPS
        assert get_stream_for_event(WORKFLOW_STEP_TIMED_OUT) == STREAM_EVAL_STEPS
        assert get_stream_for_event(AGENT_RESPONSE_RECEIVED) == STREAM_EVAL_STEPS

    def test_scores_stream(self) -> None:
        """Test step.scored and workflow.completed map to stream:scores."""
        assert get_stream_for_event(STEP_SCORED) == STREAM_SCORES
        assert get_stream_for_event(WORKFLOW_COMPLETED) == STREAM_SCORES

    def test_reports_stream(self) -> None:
        """Test benchmark.report.generated maps to stream:reports."""
        assert get_stream_for_event(BENCHMARK_REPORT_GENERATED) == STREAM_REPORTS

    def test_unknown_event_type_raises(self) -> None:
        """Test that unknown event types raise ValueError."""
        with pytest.raises(ValueError, match="Unknown event type"):
            get_stream_for_event("unknown.event")

    def test_get_event_types_for_stream(self) -> None:
        """Test reverse mapping from stream to event types."""
        eval_run_events = get_event_types_for_stream(STREAM_EVAL_RUNS)
        assert EVALUATION_RUN_REQUESTED in eval_run_events
        assert EVALUATION_RUN_STARTED in eval_run_events
        assert EVALUATION_RUN_COMPLETED in eval_run_events
        assert EVALUATION_RUN_FAILED in eval_run_events
        assert len(eval_run_events) == 4

        eval_step_events = get_event_types_for_stream(STREAM_EVAL_STEPS)
        assert WORKFLOW_STEP_DISPATCHED in eval_step_events
        assert WORKFLOW_STEP_TIMED_OUT in eval_step_events
        assert AGENT_RESPONSE_RECEIVED in eval_step_events
        assert len(eval_step_events) == 3

        score_events = get_event_types_for_stream(STREAM_SCORES)
        assert STEP_SCORED in score_events
        assert WORKFLOW_COMPLETED in score_events
        assert len(score_events) == 2

        report_events = get_event_types_for_stream(STREAM_REPORTS)
        assert BENCHMARK_REPORT_GENERATED in report_events
        assert len(report_events) == 1

    def test_get_event_types_for_unknown_stream_raises(self) -> None:
        """Test that unknown streams raise ValueError."""
        with pytest.raises(ValueError, match="Unknown stream"):
            get_event_types_for_stream("stream:unknown")


class TestEventTypeHelpers:
    """Tests for event type classification helpers."""

    def test_is_eval_run_event(self) -> None:
        """Test is_eval_run_event for evaluation.run.* events."""
        assert is_eval_run_event(EVALUATION_RUN_REQUESTED) is True
        assert is_eval_run_event(EVALUATION_RUN_STARTED) is True
        assert is_eval_run_event(EVALUATION_RUN_COMPLETED) is True
        assert is_eval_run_event(EVALUATION_RUN_FAILED) is True
        assert is_eval_run_event(WORKFLOW_STEP_DISPATCHED) is False
        assert is_eval_run_event(AGENT_RESPONSE_RECEIVED) is False

    def test_is_workflow_step_event(self) -> None:
        """Test is_workflow_step_event for workflow.step.* events."""
        assert is_workflow_step_event(WORKFLOW_STEP_DISPATCHED) is True
        assert is_workflow_step_event(WORKFLOW_STEP_TIMED_OUT) is True
        assert is_workflow_step_event(WORKFLOW_COMPLETED) is False
        assert is_workflow_step_event(EVALUATION_RUN_REQUESTED) is False


class TestPayloadValidation:
    """Tests for payload validation."""

    def test_allowed_payload_passes(self) -> None:
        """Test that allowed payload fields are accepted."""
        payload = {
            "benchmark_id": generate_uuid(),
            "run_id": generate_uuid(),
            "workflow_id": "wf_pr_review_v1",
            "agent_id": "gpt-4o-mini",
            "case_set_id": "pr_review_cases_v1",
            "case_id": "pr_001",
            "step_id": "s1_findings",
        }
        assert validate_payload(payload) is True

    def test_empty_payload_passes(self) -> None:
        """Test that empty payload is valid."""
        assert validate_payload({}) is True

    def test_payload_with_metadata_passes(self) -> None:
        """Test that metadata fields are allowed."""
        payload = {
            "run_id": generate_uuid(),
            "status": "completed",
            "latency_ms": 1500,
            "score": 0.85,
            "details": {"matches": 3, "false_positives": 1},
        }
        assert validate_payload(payload) is True

    def test_diff_content_forbidden(self) -> None:
        """Test that diff_content field is rejected."""
        payload = {
            "run_id": generate_uuid(),
            "diff_content": "--- a/file.py\n+++ b/file.py\n...",
        }
        with pytest.raises(ValueError, match="forbidden fields"):
            validate_payload(payload)

    def test_diff_patch_forbidden(self) -> None:
        """Test that diff_patch field is rejected."""
        payload = {
            "run_id": generate_uuid(),
            "diff_patch": "large patch content here",
        }
        with pytest.raises(ValueError, match="forbidden fields"):
            validate_payload(payload)

    def test_full_diff_forbidden(self) -> None:
        """Test that full_diff field is rejected."""
        payload = {
            "run_id": generate_uuid(),
            "full_diff": "large diff content",
        }
        with pytest.raises(ValueError, match="forbidden fields"):
            validate_payload(payload)

    def test_ticket_content_forbidden(self) -> None:
        """Test that ticket_content field is rejected."""
        payload = {
            "run_id": generate_uuid(),
            "ticket_content": "Full ticket description...",
        }
        with pytest.raises(ValueError, match="forbidden fields"):
            validate_payload(payload)

    def test_ticket_text_forbidden(self) -> None:
        """Test that ticket_text field is rejected."""
        payload = {
            "run_id": generate_uuid(),
            "ticket_text": "Full ticket text...",
        }
        with pytest.raises(ValueError, match="forbidden fields"):
            validate_payload(payload)

    def test_workflow_definition_forbidden(self) -> None:
        """Test that workflow_definition field is rejected."""
        payload = {
            "run_id": generate_uuid(),
            "workflow_definition": {"steps": []},
        }
        with pytest.raises(ValueError, match="forbidden fields"):
            validate_payload(payload)

    def test_ground_truth_forbidden(self) -> None:
        """Test that ground_truth field is rejected."""
        payload = {
            "run_id": generate_uuid(),
            "ground_truth": {"findings": []},
        }
        with pytest.raises(ValueError, match="forbidden fields"):
            validate_payload(payload)

    def test_expected_findings_forbidden(self) -> None:
        """Test that expected_findings field is rejected."""
        payload = {
            "run_id": generate_uuid(),
            "expected_findings": [{"id": "F1"}],
        }
        with pytest.raises(ValueError, match="forbidden fields"):
            validate_payload(payload)

    def test_raw_response_forbidden(self) -> None:
        """Test that raw_response field is rejected."""
        payload = {
            "run_id": generate_uuid(),
            "raw_response": "Large agent response...",
        }
        with pytest.raises(ValueError, match="forbidden fields"):
            validate_payload(payload)

    def test_agent_output_forbidden(self) -> None:
        """Test that agent_output field is rejected."""
        payload = {
            "run_id": generate_uuid(),
            "agent_output": "Large agent output...",
        }
        with pytest.raises(ValueError, match="forbidden fields"):
            validate_payload(payload)

    def test_nested_forbidden_field(self) -> None:
        """Test that nested forbidden fields are detected."""
        payload = {
            "run_id": generate_uuid(),
            "details": {
                "diff_content": "nested forbidden content",
            },
        }
        with pytest.raises(ValueError, match="forbidden fields"):
            validate_payload(payload)

    def test_list_forbidden_field(self) -> None:
        """Test that forbidden fields in lists are detected."""
        payload = {
            "run_id": generate_uuid(),
            "items": [
                {"diff_patch": "forbidden in list item"},
            ],
        }
        with pytest.raises(ValueError, match="forbidden fields"):
            validate_payload(payload)

    def test_non_dict_payload_raises(self) -> None:
        """Test that non-dict payload raises ValueError."""
        with pytest.raises(ValueError, match="must be a dictionary"):
            validate_payload("not a dict")  # type: ignore

    def test_large_payload_size_forbidden(self) -> None:
        """Test that payloads exceeding MAX_PAYLOAD_SIZE are rejected."""
        # Create a payload that exceeds the limit
        large_content = "x" * (MAX_PAYLOAD_SIZE + 1000)
        payload = {
            "run_id": generate_uuid(),
            "details": large_content,
        }
        with pytest.raises(ValueError, match="exceeds maximum size"):
            validate_payload(payload)

    def test_validation_constants_defined(self) -> None:
        """Test that validation constants are exported."""
        assert len(ALLOWED_PAYLOAD_FIELDS) > 0
        assert len(FORBIDDEN_PAYLOAD_PATTERNS) > 0
        assert MAX_PAYLOAD_SIZE > 0


class TestEventEnvelopeValidation:
    """Tests for event envelope validation."""

    def test_valid_envelope_passes(self) -> None:
        """Test that a valid envelope passes validation."""
        run_id = generate_uuid()
        event = EventEnvelope(
            event_id=generate_uuid(),
            event_type=EVALUATION_RUN_REQUESTED,
            timestamp=now_iso(),
            correlation_id=run_id,
            payload={
                "benchmark_id": generate_uuid(),
                "run_id": run_id,
                "workflow_id": "wf_pr_review_v1",
            },
        )
        assert validate_event_envelope(event) is True

    def test_correlation_id_equals_run_id(self) -> None:
        """Test that correlation_id must equal run_id for run-scoped events."""
        run_id = generate_uuid()
        different_id = generate_uuid()
        event = EventEnvelope(
            event_id=generate_uuid(),
            event_type=EVALUATION_RUN_STARTED,
            timestamp=now_iso(),
            correlation_id=different_id,  # Different from run_id
            payload={
                "run_id": run_id,
            },
        )
        with pytest.raises(ValueError, match="correlation_id.*must equal.*run_id"):
            validate_event_envelope(event)

    def test_invalid_event_type_raises(self) -> None:
        """Test that invalid event types raise ValueError."""
        event = EventEnvelope(
            event_id=generate_uuid(),
            event_type="invalid.event.type",
            timestamp=now_iso(),
            correlation_id=generate_uuid(),
            payload={},
        )
        with pytest.raises(ValueError, match="Invalid event type"):
            validate_event_envelope(event)

    def test_forbidden_payload_in_envelope_raises(self) -> None:
        """Test that forbidden payload fields raise ValueError."""
        event = EventEnvelope(
            event_id=generate_uuid(),
            event_type=EVALUATION_RUN_REQUESTED,
            timestamp=now_iso(),
            correlation_id=generate_uuid(),
            payload={
                "diff_content": "forbidden content",
            },
        )
        with pytest.raises(ValueError, match="forbidden fields"):
            validate_event_envelope(event)

    def test_report_event_no_run_id_check(self) -> None:
        """Test that report events don't require run_id in payload."""
        # Report events don't have run_id, so correlation check should be skipped
        event = EventEnvelope(
            event_id=generate_uuid(),
            event_type=BENCHMARK_REPORT_GENERATED,
            timestamp=now_iso(),
            correlation_id=generate_uuid(),
            payload={
                "benchmark_id": generate_uuid(),
            },
        )
        # Should pass without requiring run_id
        assert validate_event_envelope(event) is True


class TestEventEnvelopeCreation:
    """Tests for event envelope creation."""

    def test_event_with_correlation_id(self) -> None:
        """Test creating event envelope with correlation_id."""
        run_id = generate_uuid()
        event = EventEnvelope(
            event_id=generate_uuid(),
            event_type=EVALUATION_RUN_STARTED,
            timestamp=now_iso(),
            correlation_id=run_id,
            payload={"run_id": run_id, "benchmark_id": generate_uuid()},
        )
        assert event.correlation_id == run_id
        assert event.payload["run_id"] == run_id

    def test_event_serialization_roundtrip(self) -> None:
        """Test event envelope serializes and deserializes."""
        original = EventEnvelope(
            event_id=generate_uuid(),
            event_type=WORKFLOW_STEP_DISPATCHED,
            schema_version="1.0",
            timestamp=now_iso(),
            correlation_id=generate_uuid(),
            payload={
                "run_id": generate_uuid(),
                "step_id": "s1_findings",
                "agent_id": "gpt-4o-mini",
            },
        )

        data = original.model_dump()
        restored = EventEnvelope.model_validate(data)

        assert restored.event_id == original.event_id
        assert restored.event_type == original.event_type
        assert restored.correlation_id == original.correlation_id
        assert restored.payload == original.payload
