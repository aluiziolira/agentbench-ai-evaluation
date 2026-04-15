"""Unit tests for the StepDispatcher.

Tests cover:
- Prompt rendering with case placeholders
- Raw I/O persistence
- Timeout handling
- Event emission (agent.response.received, workflow.step.timed_out)
- Error handling (unknown agent, missing run/workflow/step)
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentbench.cases.models import ReviewCaseDefinition
from agentbench.dispatcher.adapters import AgentAdapter
from agentbench.dispatcher.dispatcher import StepDispatcher
from agentbench.events.types import (
    AGENT_RESPONSE_RECEIVED,
    EVALUATION_RUN_FAILED,
    STREAM_EVAL_RUNS,
    STREAM_EVAL_STEPS,
    WORKFLOW_STEP_TIMED_OUT,
)
from agentbench.models import (
    EvaluationRun,
    RunState,
    ScoringConfig,
    StepDefinition,
    WorkflowDefinition,
)
from agentbench.models.events import EventEnvelope


@pytest.fixture
def mock_event_bus():
    """Create a mock EventBus."""
    bus = MagicMock()
    bus.publish = AsyncMock()
    bus.ack = AsyncMock()
    return bus


@pytest.fixture
def mock_mongo_storage():
    """Create a mock MongoStorage."""
    storage = MagicMock()
    storage.get_run = AsyncMock()
    storage.get_workflow = AsyncMock()
    storage.update_run_state = AsyncMock()
    return storage


@pytest.fixture
def mock_redis_storage():
    """Create a mock RedisStorage."""
    storage = MagicMock()
    storage.set_run_state = AsyncMock()
    storage.mark_run_completed = AsyncMock()
    return storage


@pytest.fixture
def temp_raw_io_dir(tmp_path):
    """Create a temporary raw I/O directory."""
    return tmp_path / "raw_io"


@pytest.fixture
def dispatcher(mock_event_bus, mock_mongo_storage, mock_redis_storage, temp_raw_io_dir):
    """Create a StepDispatcher with mock dependencies."""
    return StepDispatcher(
        event_bus=mock_event_bus,
        mongo_storage=mock_mongo_storage,
        redis_storage=mock_redis_storage,
        raw_io_dir=temp_raw_io_dir,
    )


@pytest.fixture
def sample_run():
    """Create a sample EvaluationRun."""
    return EvaluationRun(
        run_id=str(uuid.uuid4()),
        benchmark_id="benchmark-001",
        workflow_id="wf_pr_review_v1",
        workflow_version="1.0.0",
        case_set_id="fixtures/pr_review",
        case_id="pr_001",
        agent_id="gpt-4o-mini",
        agent_config={"temperature": 0.0},
        state=RunState.STARTED,
        current_step=0,
        created_at=datetime.now(UTC).isoformat(),
        completed_at=None,
    )


@pytest.fixture
def sample_step():
    """Create a sample StepDefinition with placeholders."""
    return StepDefinition(
        step_id="s1_findings",
        order=0,
        input="""You are reviewing a pull request.

Ticket:
{ticket_text}

Diff:
{diff_patch}

Case ID: {case_id}

Return JSON with findings.""",
        timeout_ms=15000,
        scoring=ScoringConfig(strategy="finding_match", weight=2.0),
    )


@pytest.fixture
def sample_case():
    """Create a sample ReviewCaseDefinition."""
    return ReviewCaseDefinition(
        case_id="pr_001",
        case_set_id="pr_review_cases_v1",
        difficulty="medium",
        tags=["auth", "api"],
        ticket_text="Add admin endpoint for user management",
        diff_patch="diff --git a/app/admin.py b/app/admin.py\n+def delete_user():",
        expected_findings=[],
        disallowed_findings=[],
    )


@pytest.fixture
def sample_workflow(sample_step):
    """Create a sample WorkflowDefinition."""
    return WorkflowDefinition(
        workflow_id="wf_pr_review_v1",
        version="1.0.0",
        status="published",
        description="PR review workflow",
        steps=[sample_step],
        scoring_aggregation="weighted_average",
        created_at=datetime.now(UTC).isoformat(),
        published_at=datetime.now(UTC).isoformat(),
    )


class TestRenderPrompt:
    """Test prompt rendering with case placeholders."""

    def test_render_prompt_replaces_ticket_text(self, dispatcher, sample_step, sample_case):
        """Test that {ticket_text} placeholder is replaced."""
        result = dispatcher._render_prompt(sample_step, sample_case)
        assert sample_case.ticket_text in result
        assert "{ticket_text}" not in result

    def test_render_prompt_replaces_diff_patch(self, dispatcher, sample_step, sample_case):
        """Test that {diff_patch} placeholder is replaced."""
        result = dispatcher._render_prompt(sample_step, sample_case)
        assert sample_case.diff_patch in result
        assert "{diff_patch}" not in result

    def test_render_prompt_replaces_case_id(self, dispatcher, sample_step, sample_case):
        """Test that {case_id} placeholder is replaced."""
        result = dispatcher._render_prompt(sample_step, sample_case)
        assert sample_case.case_id in result
        assert "{case_id}" not in result

    def test_render_prompt_preserves_json_braces(self, dispatcher, sample_case):
        """Test that curly braces in JSON examples are preserved."""
        # Create a step with JSON examples containing curly braces
        step_with_json = StepDefinition(
            step_id="test_step",
            order=0,
            input='Ticket: {ticket_text}\nExample JSON: {"findings": [{"severity": "high"}]}',
            timeout_ms=1000,
            scoring=ScoringConfig(strategy="finding_match"),
        )
        result = dispatcher._render_prompt(step_with_json, sample_case)
        # JSON braces should be preserved
        assert '{"findings":' in result
        assert '[{"severity": "high"}]}' in result
        # Placeholder should be replaced
        assert "{ticket_text}" not in result
        assert sample_case.ticket_text in result

    def test_render_prompt_preserves_other_text(self, dispatcher, sample_step, sample_case):
        """Test that non-placeholder text is preserved."""
        result = dispatcher._render_prompt(sample_step, sample_case)
        assert "You are reviewing a pull request." in result
        assert "Return JSON with findings." in result


class TestPersistRawIO:
    """Test raw I/O persistence to filesystem."""

    async def test_persist_raw_io_creates_directory(self, dispatcher, sample_run, sample_step):
        """Test that the run directory is created if it doesn't exist."""
        request = {"prompt": "test prompt", "agent_id": "gpt-4o-mini"}
        response = '{"findings": []}'
        latency_ms = 1500

        io_file = await dispatcher._persist_raw_io(
            sample_run, sample_step, request, response, latency_ms
        )

        assert io_file.parent.exists()
        assert io_file.parent.name == sample_run.run_id

    async def test_persist_raw_io_creates_json_file(self, dispatcher, sample_run, sample_step):
        """Test that a JSON file is created with the correct name."""
        request = {"prompt": "test prompt", "agent_id": "gpt-4o-mini"}
        response = '{"findings": []}'
        latency_ms = 1500

        io_file = await dispatcher._persist_raw_io(
            sample_run, sample_step, request, response, latency_ms
        )

        assert io_file.exists()
        assert io_file.suffix == ".json"
        assert io_file.stem == sample_step.step_id

    async def test_persist_raw_io_contains_required_fields(
        self, dispatcher, sample_run, sample_step
    ):
        """Test that the JSON contains all required fields."""
        request = {"prompt": "test prompt", "agent_id": "gpt-4o-mini"}
        response = '{"findings": []}'
        latency_ms = 1500

        io_file = await dispatcher._persist_raw_io(
            sample_run, sample_step, request, response, latency_ms
        )

        data = json.loads(io_file.read_text())
        assert data["run_id"] == sample_run.run_id
        assert data["case_set_id"] == sample_run.case_set_id
        assert data["case_id"] == sample_run.case_id
        assert data["step_id"] == sample_step.step_id
        assert data["agent_id"] == sample_run.agent_id
        assert data["request"] == request
        assert data["response"] == response
        assert data["latency_ms"] == latency_ms
        assert "timestamp" in data


class TestDispatchStep:
    """Test step dispatching with agent invocation."""

    @pytest.mark.asyncio
    async def test_dispatch_step_emits_response_received(
        self, dispatcher, mock_event_bus, sample_run, sample_step, sample_case
    ):
        """Test that successful invocation emits agent.response.received."""
        # Mock the adapter
        mock_adapter = MagicMock(spec=AgentAdapter)
        mock_adapter.agent_id = "gpt-4o-mini"
        mock_adapter.invoke = AsyncMock(return_value=('{"findings": []}', 1500))

        with (
            patch.object(dispatcher, "_persist_raw_io", new_callable=AsyncMock),
            patch(
                "agentbench.dispatcher.dispatcher.ADAPTER_REGISTRY.get",
                return_value=mock_adapter,
            ),
            patch("agentbench.dispatcher.dispatcher.load_case", return_value=sample_case),
        ):
            await dispatcher._dispatch_step(sample_run, sample_step)
        mock_event_bus.publish.assert_called_once()
        call_args = mock_event_bus.publish.call_args
        stream, envelope = call_args[0]

        assert stream == STREAM_EVAL_STEPS
        assert isinstance(envelope, EventEnvelope)
        assert envelope.event_type == AGENT_RESPONSE_RECEIVED
        assert envelope.payload["run_id"] == sample_run.run_id
        assert envelope.payload["step_id"] == sample_step.step_id
        assert envelope.payload["latency_ms"] == 1500
        assert envelope.correlation_id == sample_run.run_id

    @pytest.mark.asyncio
    async def test_dispatch_step_persists_raw_io(
        self, dispatcher, mock_event_bus, sample_run, sample_step, sample_case
    ):
        """Test that raw I/O is persisted after successful invocation."""
        mock_adapter = MagicMock(spec=AgentAdapter)
        mock_adapter.agent_id = "gpt-4o-mini"
        mock_adapter.invoke = AsyncMock(return_value=('{"findings": []}', 1500))

        with (
            patch(
                "agentbench.dispatcher.dispatcher.ADAPTER_REGISTRY.get",
                return_value=mock_adapter,
            ),
            patch("agentbench.dispatcher.dispatcher.load_case", return_value=sample_case),
            patch.object(dispatcher, "_persist_raw_io", new_callable=AsyncMock) as mock_persist,
        ):
            await dispatcher._dispatch_step(sample_run, sample_step)

        # Verify persistence was called with correct args
        mock_persist.assert_called_once()
        call_args = mock_persist.call_args[0]
        assert call_args[0] == sample_run
        assert call_args[1] == sample_step
        assert call_args[2]["agent_id"] == sample_run.agent_id
        assert call_args[2]["prompt"] == dispatcher._render_prompt(sample_step, sample_case)
        assert call_args[3] == '{"findings": []}'
        assert call_args[4] == 1500

    @pytest.mark.asyncio
    async def test_dispatch_step_unknown_agent_raises_error(
        self, dispatcher, sample_run, sample_step, sample_case
    ):
        """Test that unknown agent_id raises ValueError."""
        sample_run.agent_id = "unknown-agent"

        with (
            pytest.raises(ValueError, match="Unknown agent_id: unknown-agent"),
            patch("agentbench.dispatcher.dispatcher.ADAPTER_REGISTRY.get", return_value=None),
            patch("agentbench.dispatcher.dispatcher.load_case", return_value=sample_case),
        ):
            await dispatcher._dispatch_step(sample_run, sample_step)

    """Test timeout handling during agent invocation."""

    @pytest.mark.asyncio
    async def test_dispatch_step_timeout_emits_timed_out(
        self,
        dispatcher,
        mock_event_bus,
        mock_mongo_storage,
        mock_redis_storage,
        sample_run,
        sample_step,
        sample_case,
    ):
        """Test that timeout emits workflow.step.timed_out event."""
        # Create an adapter that never returns (simulates timeout)
        mock_adapter = MagicMock(spec=AgentAdapter)
        mock_adapter.agent_id = "gpt-4o-mini"

        async def slow_invoke(*args, **kwargs):
            await asyncio.sleep(10)  # Sleep longer than timeout
            return ('{"findings": []}', 100)

        mock_adapter.invoke = slow_invoke

        # Set a short timeout
        sample_step.timeout_ms = 100  # 100ms timeout

        with (
            patch(
                "agentbench.dispatcher.dispatcher.ADAPTER_REGISTRY.get",
                return_value=mock_adapter,
            ),
            patch("agentbench.dispatcher.dispatcher.load_case", return_value=sample_case),
        ):
            await dispatcher._dispatch_step(sample_run, sample_step)

        # Verify timeout and run-failed events were published
        assert mock_event_bus.publish.call_count == 2
        first_call_args = mock_event_bus.publish.call_args_list[0][0]
        second_call_args = mock_event_bus.publish.call_args_list[1][0]
        stream, envelope = first_call_args
        failed_stream, failed_envelope = second_call_args

        assert stream == STREAM_EVAL_STEPS
        assert isinstance(envelope, EventEnvelope)
        assert envelope.event_type == WORKFLOW_STEP_TIMED_OUT
        assert envelope.payload["run_id"] == sample_run.run_id
        assert envelope.payload["step_id"] == sample_step.step_id
        assert envelope.correlation_id == sample_run.run_id

        assert failed_stream == STREAM_EVAL_RUNS
        assert isinstance(failed_envelope, EventEnvelope)
        assert failed_envelope.event_type == EVALUATION_RUN_FAILED
        assert failed_envelope.payload["run_id"] == sample_run.run_id
        assert "timed out" in failed_envelope.payload["error"]

        mock_redis_storage.set_run_state.assert_called_once_with(sample_run.run_id, RunState.FAILED)
        mock_mongo_storage.update_run_state.assert_called_once_with(
            sample_run.run_id, RunState.FAILED
        )
        mock_redis_storage.mark_run_completed.assert_called_once_with(
            sample_run.benchmark_id, sample_run.run_id
        )

    @pytest.mark.asyncio
    async def test_dispatch_step_adapter_error_fails_run(
        self,
        dispatcher,
        mock_event_bus,
        mock_mongo_storage,
        mock_redis_storage,
        sample_run,
        sample_step,
        sample_case,
    ):
        """Test that adapter RuntimeError marks run as failed."""
        mock_adapter = MagicMock(spec=AgentAdapter)
        mock_adapter.agent_id = "gpt-4o-mini"
        mock_adapter.invoke = AsyncMock(side_effect=RuntimeError("API authentication failed"))

        with (
            patch(
                "agentbench.dispatcher.dispatcher.ADAPTER_REGISTRY.get", return_value=mock_adapter
            ),
            patch("agentbench.dispatcher.dispatcher.load_case", return_value=sample_case),
        ):
            await dispatcher._dispatch_step(sample_run, sample_step)

        mock_redis_storage.set_run_state.assert_called_once_with(sample_run.run_id, RunState.FAILED)
        mock_mongo_storage.update_run_state.assert_called_once_with(
            sample_run.run_id, RunState.FAILED
        )
        mock_redis_storage.mark_run_completed.assert_called_once_with(
            sample_run.benchmark_id, sample_run.run_id
        )
        mock_event_bus.publish.assert_called_once()
        stream, envelope = mock_event_bus.publish.call_args[0]
        assert stream == STREAM_EVAL_RUNS
        assert envelope.event_type == EVALUATION_RUN_FAILED
        assert envelope.payload["run_id"] == sample_run.run_id
        assert envelope.payload["error"] == "Step dispatch failed: API authentication failed"

    @pytest.mark.asyncio
    async def test_dispatch_step_timeout_no_persistence(
        self, dispatcher, mock_event_bus, sample_run, sample_step, sample_case
    ):
        """Test that no I/O is persisted when timeout occurs."""
        mock_adapter = MagicMock(spec=AgentAdapter)
        mock_adapter.agent_id = "gpt-4o-mini"

        async def slow_invoke(*args, **kwargs):
            await asyncio.sleep(10)
            return ('{"findings": []}', 100)

        mock_adapter.invoke = slow_invoke
        sample_step.timeout_ms = 100

        with (
            patch.object(dispatcher, "_persist_raw_io", new_callable=AsyncMock),
            patch(
                "agentbench.dispatcher.dispatcher.ADAPTER_REGISTRY.get",
                return_value=mock_adapter,
            ),
            patch("agentbench.dispatcher.dispatcher.load_case", return_value=sample_case),
        ):
            await dispatcher._dispatch_step(sample_run, sample_step)


class TestMainLoop:
    """Test the main event consumption loop."""

    @pytest.mark.asyncio
    async def test_run_processes_dispatched_event(
        self, dispatcher, mock_event_bus, mock_mongo_storage, sample_run, sample_workflow
    ):
        """Test that workflow.step.dispatched events are processed."""
        # Create a dispatched event
        event = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type="workflow.step.dispatched",
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id=sample_run.run_id,
            payload={
                "run_id": sample_run.run_id,
                "step_id": "s1_findings",
            },
        )
        # Attach internal attributes expected by dispatcher
        event._message_id = b"123-0"
        event._stream = STREAM_EVAL_STEPS
        event._consumer_group = "dispatcher"

        # Setup mocks for storage
        mock_mongo_storage.get_run.return_value = sample_run
        mock_mongo_storage.get_workflow.return_value = sample_workflow

        # Setup mock adapter
        mock_adapter = MagicMock(spec=AgentAdapter)
        mock_adapter.agent_id = "gpt-4o-mini"
        mock_adapter.invoke = AsyncMock(return_value=('{"findings": []}', 1500))

        # Consume should return one event then stop
        async def mock_consume(*args, **kwargs):
            yield event
            dispatcher._running = False  # Stop after one iteration

        mock_event_bus.consume = mock_consume

        with (
            patch(
                "agentbench.dispatcher.dispatcher.ADAPTER_REGISTRY.get",
                return_value=mock_adapter,
            ),
            patch("agentbench.dispatcher.dispatcher.load_case") as mock_load_case,
        ):
            mock_load_case.return_value = MagicMock(
                case_id="pr_001",
                case_set_id="pr_review_cases_v1",
                ticket_text="Test ticket",
                diff_patch="Test diff",
            )
            await dispatcher.run()

        # Verify run and workflow were loaded
        mock_mongo_storage.get_run.assert_called_once_with(sample_run.run_id)
        mock_mongo_storage.get_workflow.assert_called_once_with(
            sample_run.workflow_id, sample_run.workflow_version
        )

    @pytest.mark.asyncio
    async def test_run_skips_non_dispatched_events(
        self, dispatcher, mock_event_bus, mock_mongo_storage
    ):
        """Test that non-dispatched events are acknowledged but not processed."""
        event = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type="agent.response.received",  # Not a dispatched event
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id="test-run-id",
            payload={"run_id": "test-run-id", "step_id": "s1"},
        )
        event._message_id = b"123-0"

        async def mock_consume(*args, **kwargs):
            yield event
            dispatcher._running = False

        mock_event_bus.consume = mock_consume

        await dispatcher.run()

        # Should acknowledge but not process
        mock_event_bus.ack.assert_called_once()
        mock_mongo_storage.get_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_handles_missing_run(self, dispatcher, mock_event_bus, mock_mongo_storage):
        """Test that missing run logs error and acknowledges."""
        event = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type="workflow.step.dispatched",
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id="missing-run-id",
            payload={"run_id": "missing-run-id", "step_id": "s1"},
        )
        event._message_id = b"123-0"

        async def mock_consume(*args, **kwargs):
            yield event
            dispatcher._running = False

        mock_event_bus.consume = mock_consume
        mock_mongo_storage.get_run.return_value = None

        await dispatcher.run()

        # Should acknowledge even on error
        mock_event_bus.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_handles_missing_workflow(
        self, dispatcher, mock_event_bus, mock_mongo_storage, sample_run
    ):
        """Test that missing workflow logs error and acknowledges."""
        event = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type="workflow.step.dispatched",
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id=sample_run.run_id,
            payload={"run_id": sample_run.run_id, "step_id": "s1"},
        )
        event._message_id = b"123-0"

        async def mock_consume(*args, **kwargs):
            yield event
            dispatcher._running = False

        mock_event_bus.consume = mock_consume
        mock_mongo_storage.get_run.return_value = sample_run
        mock_mongo_storage.get_workflow.return_value = None

        await dispatcher.run()

        # Should acknowledge even on error
        mock_event_bus.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_handles_missing_step(
        self, dispatcher, mock_event_bus, mock_mongo_storage, sample_run
    ):
        """Test that missing step in workflow logs error and acknowledges."""
        event = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type="workflow.step.dispatched",
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id=sample_run.run_id,
            payload={"run_id": sample_run.run_id, "step_id": "nonexistent-step"},
        )
        event._message_id = b"123-0"

        # Workflow with different step
        workflow = WorkflowDefinition(
            workflow_id="wf_pr_review_v1",
            version="1.0.0",
            status="published",
            description="PR review workflow",
            steps=[
                StepDefinition(
                    step_id="other-step",
                    order=0,
                    input="test",
                    timeout_ms=1000,
                    scoring=ScoringConfig(strategy="finding_match"),
                )
            ],
            scoring_aggregation="weighted_average",
            created_at=datetime.now(UTC).isoformat(),
            published_at=datetime.now(UTC).isoformat(),
        )

        async def mock_consume(*args, **kwargs):
            yield event
            dispatcher._running = False

        mock_event_bus.consume = mock_consume
        mock_mongo_storage.get_run.return_value = sample_run
        mock_mongo_storage.get_workflow.return_value = workflow

        await dispatcher.run()

        # Should acknowledge even on error
        mock_event_bus.ack.assert_called_once()


class TestStop:
    """Test the stop method."""

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, dispatcher):
        """Test that stop() sets _running to False."""
        dispatcher._running = True
        await dispatcher.stop()
        assert dispatcher._running is False
