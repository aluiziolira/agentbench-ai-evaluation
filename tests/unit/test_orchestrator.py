"""Unit tests for the Orchestrator.

Tests cover:
- Run creation
- Step dispatch
- Step progression
- Workflow completion
- Benchmark expansion (agent x case matrix)
- Error handling and failure scenarios
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentbench.events.types import (
    EVALUATION_RUN_FAILED,
    EVALUATION_RUN_REQUESTED,
    EVALUATION_RUN_STARTED,
    STEP_SCORED,
    STREAM_EVAL_RUNS,
    STREAM_EVAL_STEPS,
    STREAM_SCORES,
    WORKFLOW_COMPLETED,
    WORKFLOW_STEP_DISPATCHED,
)
from agentbench.models import (
    EvaluationRun,
    RunState,
    ScoringConfig,
    StepDefinition,
    WorkflowDefinition,
)
from agentbench.models.events import EventEnvelope
from agentbench.orchestrator.orchestrator import Orchestrator


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
    storage.create_run = AsyncMock()
    storage.get_run = AsyncMock()
    storage.get_workflow = AsyncMock()
    storage.update_run_state = AsyncMock()
    return storage


@pytest.fixture
def mock_redis_storage():
    """Create a mock RedisStorage."""
    storage = MagicMock()
    storage.set_run_state = AsyncMock()
    storage.get_run_state = AsyncMock()
    storage.set_current_step = AsyncMock()
    storage.get_current_step = AsyncMock()
    storage.add_run_to_benchmark = AsyncMock()
    storage.get_benchmark_runs = AsyncMock(return_value=set())
    storage.mark_run_completed = AsyncMock()
    storage.get_benchmark_completed_runs = AsyncMock(return_value=set())
    storage.is_benchmark_complete = AsyncMock(return_value=False)
    return storage


@pytest.fixture
def temp_fixtures_dir(tmp_path):
    """Create a temporary fixtures directory with test cases."""
    fixtures_dir = tmp_path / "fixtures" / "pr_review"
    cases_dir = fixtures_dir / "cases"

    # Create case 1
    case1_dir = cases_dir / "pr_001"
    case1_dir.mkdir(parents=True)
    (case1_dir / "ticket.md").write_text("Test ticket 1")
    (case1_dir / "diff.patch").write_text("Test diff 1")
    (case1_dir / "ground_truth.json").write_text(
        '{"expected_findings": [], "disallowed_findings": []}'
    )
    (case1_dir / "metadata.json").write_text(
        '{"case_set_id": "pr_review_cases_v1", "difficulty": "medium", "tags": ["auth"]}'
    )

    # Create case 2
    case2_dir = cases_dir / "pr_002"
    case2_dir.mkdir(parents=True)
    (case2_dir / "ticket.md").write_text("Test ticket 2")
    (case2_dir / "diff.patch").write_text("Test diff 2")
    (case2_dir / "ground_truth.json").write_text(
        '{"expected_findings": [], "disallowed_findings": []}'
    )
    (case2_dir / "metadata.json").write_text(
        '{"case_set_id": "pr_review_cases_v1", "difficulty": "hard", "tags": ["api"]}'
    )

    # Create manifest
    (fixtures_dir / "manifest.json").write_text(
        '{"case_set_id": "pr_review_cases_v1", "version": "1.0.0", '
        '"cases": ['
        '{"case_id": "pr_001", "difficulty": "medium", "enabled": true, "tags": ["auth"]},'
        '{"case_id": "pr_002", "difficulty": "hard", "enabled": true, "tags": ["api"]}'
        "]}"
    )

    return fixtures_dir


@pytest.fixture
def orchestrator(mock_event_bus, mock_mongo_storage, mock_redis_storage, temp_fixtures_dir):
    """Create an Orchestrator with mock dependencies."""
    return Orchestrator(
        event_bus=mock_event_bus,
        mongo_storage=mock_mongo_storage,
        redis_storage=mock_redis_storage,
        fixtures_dir=temp_fixtures_dir,
    )


@pytest.fixture
def sample_workflow():
    """Create a sample WorkflowDefinition with 2 steps."""
    return WorkflowDefinition(
        workflow_id="wf_pr_review_v1",
        version="1.0.0",
        status="published",
        description="PR review workflow",
        steps=[
            StepDefinition(
                step_id="s1_findings",
                order=0,
                input="Find issues in the PR",
                timeout_ms=15000,
                scoring=ScoringConfig(strategy="finding_match", weight=2.0),
            ),
            StepDefinition(
                step_id="s2_review_summary",
                order=1,
                input="Write review summary",
                timeout_ms=10000,
                scoring=ScoringConfig(strategy="llm_judge", weight=1.0),
            ),
        ],
        scoring_aggregation="weighted_average",
        created_at=datetime.now(UTC).isoformat(),
        published_at=datetime.now(UTC).isoformat(),
    )


@pytest.fixture
def sample_run():
    """Create a sample EvaluationRun."""
    return EvaluationRun(
        run_id=str(uuid.uuid4()),
        benchmark_id="benchmark-001",
        workflow_id="wf_pr_review_v1",
        workflow_version="1.0.0",
        case_set_id="pr_review_cases_v1",
        case_id="pr_001",
        agent_id="gpt-4o-mini",
        agent_config={"temperature": 0.0},
        state=RunState.STARTED,
        current_step=0,
        created_at=datetime.now(UTC).isoformat(),
        completed_at=None,
    )


# ============================================================================
# Run Creation Tests
# ============================================================================


class TestCreateRun:
    """Test run creation."""

    @pytest.mark.asyncio
    async def test_create_run_stores_in_mongo(
        self, orchestrator, mock_mongo_storage, sample_workflow
    ):
        """Test that run is stored in MongoDB."""
        run = await orchestrator._create_run(
            benchmark_id="benchmark-001",
            workflow=sample_workflow,
            case_set_id="pr_review_cases_v1",
            case_id="pr_001",
            agent_id="gpt-4o-mini",
        )

        mock_mongo_storage.create_run.assert_called_once()
        assert run.benchmark_id == "benchmark-001"
        assert run.workflow_id == "wf_pr_review_v1"
        assert run.case_id == "pr_001"
        assert run.agent_id == "gpt-4o-mini"
        assert run.state == RunState.PENDING

    @pytest.mark.asyncio
    async def test_create_run_registers_in_redis(
        self, orchestrator, mock_redis_storage, sample_workflow
    ):
        """Test that run is registered in benchmark set in Redis."""
        run = await orchestrator._create_run(
            benchmark_id="benchmark-001",
            workflow=sample_workflow,
            case_set_id="pr_review_cases_v1",
            case_id="pr_001",
            agent_id="gpt-4o-mini",
        )

        mock_redis_storage.add_run_to_benchmark.assert_called_once_with("benchmark-001", run.run_id)


# ============================================================================
# Step Dispatch Tests
# ============================================================================


class TestDispatchStep:
    """Test step dispatching."""

    @pytest.mark.asyncio
    async def test_dispatch_step_updates_redis_state(
        self, orchestrator, mock_redis_storage, sample_workflow, sample_run, mock_mongo_storage
    ):
        """Test that step dispatch updates FSM state in Redis."""
        mock_mongo_storage.get_workflow.return_value = sample_workflow

        await orchestrator._dispatch_step(sample_run, 0)

        mock_redis_storage.set_current_step.assert_called_once_with(sample_run.run_id, 0)
        mock_redis_storage.set_run_state.assert_called_once_with(
            sample_run.run_id, RunState.STEP_IN_PROGRESS
        )

    @pytest.mark.asyncio
    async def test_dispatch_step_updates_mongo_state(
        self, orchestrator, mock_mongo_storage, sample_workflow, sample_run
    ):
        """Test that step dispatch updates run state in MongoDB."""
        mock_mongo_storage.get_workflow.return_value = sample_workflow

        await orchestrator._dispatch_step(sample_run, 0)

        mock_mongo_storage.update_run_state.assert_called_once_with(
            sample_run.run_id, RunState.STEP_IN_PROGRESS, 0
        )

    @pytest.mark.asyncio
    async def test_dispatch_step_emits_event(
        self, orchestrator, mock_event_bus, mock_mongo_storage, sample_workflow, sample_run
    ):
        """Test that step dispatch emits workflow.step.dispatched event."""
        mock_mongo_storage.get_workflow.return_value = sample_workflow

        await orchestrator._dispatch_step(sample_run, 0)

        mock_event_bus.publish.assert_called_once()
        call_args = mock_event_bus.publish.call_args[0]
        stream, envelope = call_args

        assert stream == STREAM_EVAL_STEPS
        assert isinstance(envelope, EventEnvelope)
        assert envelope.event_type == WORKFLOW_STEP_DISPATCHED
        assert envelope.payload["run_id"] == sample_run.run_id
        assert envelope.payload["step_id"] == "s1_findings"
        assert envelope.payload["step_index"] == 0
        assert envelope.correlation_id == sample_run.run_id

    @pytest.mark.asyncio
    async def test_dispatch_step_invalid_index_raises(
        self, orchestrator, mock_mongo_storage, sample_workflow, sample_run
    ):
        """Test that invalid step index raises ValueError."""
        mock_mongo_storage.get_workflow.return_value = sample_workflow

        with pytest.raises(ValueError, match="Invalid step index"):
            await orchestrator._dispatch_step(sample_run, 5)  # Workflow only has 2 steps

    @pytest.mark.asyncio
    async def test_dispatch_step_missing_workflow_raises(
        self, orchestrator, mock_mongo_storage, sample_run
    ):
        """Test that missing workflow raises ValueError."""
        mock_mongo_storage.get_workflow.return_value = None

        with pytest.raises(ValueError, match="Workflow not found"):
            await orchestrator._dispatch_step(sample_run, 0)


# ============================================================================
# Step Progression Tests
# ============================================================================


class TestStepProgression:
    """Test step progression after scoring."""

    @pytest.mark.asyncio
    async def test_step_scored_dispatches_next_step(
        self, orchestrator, mock_mongo_storage, mock_redis_storage, sample_workflow, sample_run
    ):
        """Test that step.scored dispatches the next step."""
        mock_mongo_storage.get_run.return_value = sample_run
        mock_mongo_storage.get_workflow.return_value = sample_workflow
        mock_redis_storage.get_current_step.return_value = 0

        event = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=STEP_SCORED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id=sample_run.run_id,
            payload={"run_id": sample_run.run_id, "step_id": "s1_findings"},
        )

        await orchestrator._handle_step_scored(event)

        # Should dispatch step 1 (next step)
        mock_mongo_storage.update_run_state.assert_any_call(
            sample_run.run_id, RunState.STEP_SCORED, 0
        )

    @pytest.mark.asyncio
    async def test_step_scored_missing_run_logs_error(
        self, orchestrator, mock_mongo_storage, mock_redis_storage
    ):
        """Test that missing run is logged as error."""
        mock_mongo_storage.get_run.return_value = None

        event = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=STEP_SCORED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id="missing-run-id",
            payload={"run_id": "missing-run-id", "step_id": "s1"},
        )

        await orchestrator._handle_step_scored(event)

        # Should not crash, just log error
        mock_redis_storage.set_current_step.assert_not_called()

    @pytest.mark.asyncio
    async def test_step_scored_missing_workflow_fails_run(
        self, orchestrator, mock_mongo_storage, sample_run
    ):
        """Test that missing workflow marks run as failed."""
        mock_mongo_storage.get_run.return_value = sample_run
        mock_mongo_storage.get_workflow.return_value = None

        event = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=STEP_SCORED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id=sample_run.run_id,
            payload={"run_id": sample_run.run_id, "step_id": "s1_findings"},
        )

        await orchestrator._handle_step_scored(event)

        # Run should be marked as failed
        mock_mongo_storage.update_run_state.assert_called_once_with(
            sample_run.run_id, RunState.FAILED
        )


# ============================================================================
# Workflow Completion Tests
# ============================================================================


class TestWorkflowCompletion:
    """Test workflow completion handling."""

    @pytest.mark.asyncio
    async def test_complete_run_updates_state(
        self, orchestrator, mock_mongo_storage, mock_redis_storage, sample_workflow, sample_run
    ):
        """Test that run completion updates FSM and MongoDB state."""
        await orchestrator._complete_run(sample_run, sample_workflow)

        mock_redis_storage.set_run_state.assert_called_once_with(
            sample_run.run_id, RunState.COMPLETED
        )
        mock_redis_storage.mark_run_completed.assert_called_once_with(
            sample_run.benchmark_id, sample_run.run_id
        )
        mock_mongo_storage.update_run_state.assert_called_once_with(
            sample_run.run_id, RunState.COMPLETED
        )

    @pytest.mark.asyncio
    async def test_complete_run_emits_workflow_completed(
        self, orchestrator, mock_event_bus, sample_workflow, sample_run
    ):
        """Test that run completion emits workflow.completed event."""
        await orchestrator._complete_run(sample_run, sample_workflow)

        # Check that workflow.completed event was emitted
        publish_calls = mock_event_bus.publish.call_args_list
        workflow_completed_calls = [
            c for c in publish_calls if c[0][1].event_type == WORKFLOW_COMPLETED
        ]
        assert len(workflow_completed_calls) == 1

        stream, envelope = workflow_completed_calls[0][0]
        assert stream == STREAM_SCORES  # Per spec, workflow.completed goes to stream:scores
        assert envelope.payload["run_id"] == sample_run.run_id
        assert envelope.payload["benchmark_id"] == sample_run.benchmark_id

    @pytest.mark.asyncio
    async def test_complete_run_emits_benchmark_completed_when_all_done(
        self, orchestrator, mock_event_bus, mock_redis_storage, sample_workflow, sample_run
    ):
        """Test that benchmark completion event is benchmark-scoped (no run_id)."""
        mock_redis_storage.is_benchmark_complete.return_value = True

        await orchestrator._complete_run(sample_run, sample_workflow)

        # Find the EVALUATION_RUN_COMPLETED event
        publish_calls = mock_event_bus.publish.call_args_list
        completed_calls = [
            c for c in publish_calls if c[0][1].event_type == "evaluation.run.completed"
        ]
        assert len(completed_calls) == 1

        stream, envelope = completed_calls[0][0]
        assert stream == "stream:eval-runs"
        assert envelope.correlation_id == sample_run.benchmark_id
        # Benchmark-level event should NOT contain run_id (would fail bus validation)
        assert "run_id" not in envelope.payload
        assert envelope.payload["benchmark_id"] == sample_run.benchmark_id


# ============================================================================
# Benchmark Expansion Tests
# ============================================================================


class TestBenchmarkExpansion:
    """Test benchmark expansion into runs."""

    @pytest.mark.asyncio
    async def test_run_requested_creates_runs_for_all_agents_and_cases(
        self, orchestrator, mock_mongo_storage, mock_redis_storage, sample_workflow
    ):
        """Test that evaluation.run.requested creates runs for agent x case matrix."""
        mock_mongo_storage.get_workflow.return_value = sample_workflow

        event = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=EVALUATION_RUN_REQUESTED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id="benchmark-001",
            payload={
                "benchmark_id": "benchmark-001",
                "workflow_id": "wf_pr_review_v1",
                "case_set_id": "pr_review_cases_v1",
                "agents": ["gpt-4o-mini", "claude-haiku-4-5"],
            },
        )

        await orchestrator._handle_run_requested(event)

        # Should create 4 runs (2 agents x 2 cases)
        assert mock_mongo_storage.create_run.call_count == 4
        assert mock_redis_storage.add_run_to_benchmark.call_count == 4

    @pytest.mark.asyncio
    async def test_run_requested_emits_started_event(
        self, orchestrator, mock_event_bus, mock_mongo_storage, mock_redis_storage, sample_workflow
    ):
        """Test that evaluation.run.requested emits evaluation.run.started."""
        mock_mongo_storage.get_workflow.return_value = sample_workflow

        event = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=EVALUATION_RUN_REQUESTED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id="benchmark-001",
            payload={
                "benchmark_id": "benchmark-001",
                "workflow_id": "wf_pr_review_v1",
                "case_set_id": "pr_review_cases_v1",
                "agents": ["gpt-4o-mini"],
            },
        )

        await orchestrator._handle_run_requested(event)

        # Check that evaluation.run.started was emitted
        publish_calls = mock_event_bus.publish.call_args_list
        started_calls = [c for c in publish_calls if c[0][1].event_type == EVALUATION_RUN_STARTED]
        assert len(started_calls) >= 1  # At least one started event

    @pytest.mark.asyncio
    async def test_run_requested_missing_workflow_raises(self, orchestrator, mock_mongo_storage):
        """Test that missing workflow raises ValueError."""
        mock_mongo_storage.get_workflow.return_value = None

        event = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=EVALUATION_RUN_REQUESTED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id="benchmark-001",
            payload={
                "benchmark_id": "benchmark-001",
                "workflow_id": "wf_nonexistent",
                "case_set_id": "pr_review_cases_v1",
                "agents": ["gpt-4o-mini"],
            },
        )

        with pytest.raises(ValueError, match="Workflow not found"):
            await orchestrator._handle_run_requested(event)


# ============================================================================
# Failure Handling Tests
# ============================================================================


class TestFailureHandling:
    """Test failure handling."""

    @pytest.mark.asyncio
    async def test_fail_run_updates_state(
        self, orchestrator, mock_mongo_storage, mock_redis_storage, sample_run
    ):
        """Test that _fail_run updates FSM and MongoDB state."""
        mock_mongo_storage.get_run.return_value = sample_run

        await orchestrator._fail_run(sample_run.run_id, "Test error")

        mock_redis_storage.set_run_state.assert_called_once_with(sample_run.run_id, RunState.FAILED)
        mock_mongo_storage.update_run_state.assert_called_once_with(
            sample_run.run_id, RunState.FAILED
        )

    @pytest.mark.asyncio
    async def test_fail_run_emits_failed_event(
        self, orchestrator, mock_mongo_storage, mock_event_bus, sample_run
    ):
        """Test that _fail_run emits evaluation.run.failed event."""
        mock_mongo_storage.get_run.return_value = sample_run

        await orchestrator._fail_run(sample_run.run_id, "Test error")

        mock_event_bus.publish.assert_called_once()
        call_args = mock_event_bus.publish.call_args[0]
        stream, envelope = call_args

        assert stream == STREAM_EVAL_RUNS
        assert envelope.event_type == EVALUATION_RUN_FAILED
        assert envelope.payload["run_id"] == sample_run.run_id
        assert envelope.payload["error"] == "Test error"


# ============================================================================
# Main Loop Tests
# ============================================================================


class TestMainLoop:
    """Test the main event consumption loop."""

    @pytest.mark.asyncio
    async def test_run_processes_requested_event(
        self, orchestrator, mock_event_bus, mock_mongo_storage, mock_redis_storage, sample_workflow
    ):
        """Test that evaluation.run.requested events are processed."""
        mock_mongo_storage.get_workflow.return_value = sample_workflow

        event = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=EVALUATION_RUN_REQUESTED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id="benchmark-001",
            payload={
                "benchmark_id": "benchmark-001",
                "workflow_id": "wf_pr_review_v1",
                "case_set_id": "pr_review_cases_v1",
                "agents": ["gpt-4o-mini"],
            },
        )
        event._message_id = b"123-0"

        async def mock_consume(*args, **kwargs):
            yield event
            orchestrator._running = False

        mock_event_bus.consume = mock_consume

        await orchestrator.run()

        # Should have created runs
        assert mock_mongo_storage.create_run.call_count == 2  # 1 agent x 2 cases

    @pytest.mark.asyncio
    async def test_run_processes_scored_event(
        self,
        orchestrator,
        mock_event_bus,
        mock_mongo_storage,
        mock_redis_storage,
        sample_workflow,
        sample_run,
    ):
        """Test that step.scored events are processed."""
        mock_mongo_storage.get_run.return_value = sample_run
        mock_mongo_storage.get_workflow.return_value = sample_workflow
        mock_redis_storage.get_current_step.return_value = 0

        event = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=STEP_SCORED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id=sample_run.run_id,
            payload={"run_id": sample_run.run_id, "step_id": "s1_findings"},
        )
        event._message_id = b"123-0"

        async def mock_consume(*args, **kwargs):
            yield event
            orchestrator._running = False

        mock_event_bus.consume = mock_consume

        await orchestrator.run()

        # Should acknowledge the message
        mock_event_bus.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_handles_errors_and_continues(
        self, orchestrator, mock_event_bus, mock_mongo_storage
    ):
        """Test that errors in event processing don't crash the loop."""
        event = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=EVALUATION_RUN_REQUESTED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id="benchmark-001",
            payload={
                "benchmark_id": "benchmark-001",
                "workflow_id": "wf_pr_review_v1",
                "case_set_id": "pr_review_cases_v1",
                "agents": ["gpt-4o-mini"],
            },
        )
        event._message_id = b"123-0"

        # Make workflow lookup fail
        mock_mongo_storage.get_workflow.side_effect = ValueError("Test error")

        async def mock_consume(*args, **kwargs):
            yield event
            orchestrator._running = False

        mock_event_bus.consume = mock_consume

        # Should not crash
        await orchestrator.run()

        # Should acknowledge even on error
        mock_event_bus.ack.assert_called_once()


# ============================================================================
# Stop Tests
# ============================================================================


class TestStop:
    """Test the stop method."""

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, orchestrator):
        """Test that stop() sets _running to False."""
        orchestrator._running = True
        await orchestrator.stop()
        assert orchestrator._running is False
