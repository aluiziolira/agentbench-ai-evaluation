"""Unit tests for the scoring engine.

Tests cover:
- Strategy resolution
- Score computation
- Event emission
- Error handling (unknown strategy, missing raw I/O, etc.)
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from agentbench.cases.models import (
    DisallowedFinding,
    ReviewCaseDefinition,
    ReviewFindingTruth,
)
from agentbench.events.types import (
    AGENT_RESPONSE_RECEIVED,
    STEP_SCORED,
    STREAM_EVAL_STEPS,
    STREAM_SCORES,
)
from agentbench.models import (
    EvaluationRun,
    EventEnvelope,
    RunState,
    ScoringConfig,
    StepDefinition,
    StepScore,
)
from agentbench.scoring import (
    FindingMatchStrategy,
    LLMJudgeStrategy,
    RawIONotFoundError,
    ScoringEngine,
    UnknownStrategyError,
)


@pytest.fixture
def mock_event_bus():
    """Create a mock EventBus."""
    bus = MagicMock()
    bus.consume = AsyncMock()
    bus.publish = AsyncMock()
    bus.ack = AsyncMock()
    return bus


@pytest.fixture
def mock_mongo_storage():
    """Create a mock MongoStorage."""
    storage = MagicMock()
    storage.get_run = AsyncMock()
    storage.get_workflow = AsyncMock()
    return storage


@pytest.fixture
def scoring_engine(mock_event_bus, mock_mongo_storage, tmp_path):
    """Create a ScoringEngine with mocked dependencies."""
    return ScoringEngine(
        event_bus=mock_event_bus,
        mongo_storage=mock_mongo_storage,
        raw_io_dir=tmp_path,
    )


@pytest.fixture
def sample_run():
    """Create a sample EvaluationRun."""
    return EvaluationRun(
        run_id=str(uuid.uuid4()),
        benchmark_id="bench-001",
        workflow_id="wf_pr_review_v1",
        workflow_version="1.0.0",
        case_set_id="pr_review_cases_v1",
        case_id="pr_001_missing_auth_check",
        agent_id="gpt-4o-mini",
        agent_config={"temperature": 0},
        state=RunState.STARTED,
        current_step=0,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


@pytest.fixture
def sample_step():
    """Create a sample StepDefinition."""
    return StepDefinition(
        step_id="s1_findings",
        order=0,
        input="Review this PR: {ticket_text}\n\nDiff:\n{diff_patch}",
        timeout_ms=15000,
        scoring=ScoringConfig(
            strategy="finding_match",
            weight=2.0,
        ),
    )


@pytest.fixture
def sample_workflow(sample_step):
    """Create a sample WorkflowDefinition."""
    from agentbench.models import WorkflowDefinition

    return WorkflowDefinition(
        workflow_id="wf_pr_review_v1",
        version="1.0.0",
        status="published",
        description="PR review workflow",
        steps=[sample_step],
        created_at=datetime.now(timezone.utc).isoformat(),
    )


@pytest.fixture
def sample_case():
    """Create a sample ReviewCaseDefinition."""
    return ReviewCaseDefinition(
        case_id="pr_001_missing_auth_check",
        case_set_id="pr_review_cases_v1",
        difficulty="medium",
        tags=["auth", "api"],
        ticket_text="Add admin endpoint",
        diff_patch="diff content",
        expected_findings=[
            ReviewFindingTruth(
                finding_id="F1",
                canonical_label="missing_permission_check",
                severity="high",
                file_path="app/api/admin.py",
                line_span=(42, 57),
                must_detect=True,
                summary="Missing auth check",
            )
        ],
        disallowed_findings=[DisallowedFinding(canonical_label="style_only_nit")],
    )


@pytest.fixture
def sample_agent_response():
    """Create a sample valid agent response for finding_match strategy."""
    return json.dumps(
        {
            "findings": [
                {
                    "canonical_label": "missing_permission_check",
                    "severity": "high",
                    "file_path": "app/api/admin.py",
                    "start_line": 42,
                    "end_line": 57,
                    "title": "Missing auth check",
                    "why_it_matters": "Security issue",
                    "suggested_test": "Add auth test",
                }
            ]
        }
    )


class TestScoringEngineInit:
    """Test ScoringEngine initialization."""

    def test_init(self, mock_event_bus, mock_mongo_storage, tmp_path):
        """Test basic initialization."""
        engine = ScoringEngine(
            event_bus=mock_event_bus,
            mongo_storage=mock_mongo_storage,
            raw_io_dir=tmp_path,
        )

        assert engine.event_bus == mock_event_bus
        assert engine.mongo_storage == mock_mongo_storage
        assert engine.raw_io_dir == tmp_path
        assert engine._running is False


class TestStrategyResolution:
    """Test strategy resolution."""

    def test_resolve_finding_match_strategy(self, scoring_engine):
        """Test resolving finding_match strategy."""
        strategy = scoring_engine._resolve_strategy("finding_match")

        assert isinstance(strategy, FindingMatchStrategy)
        assert strategy.strategy_id == "finding_match"

    def test_resolve_llm_judge_strategy(self, scoring_engine):
        """Test resolving llm_judge strategy."""
        strategy = scoring_engine._resolve_strategy("llm_judge")

        assert isinstance(strategy, LLMJudgeStrategy)
        assert strategy.strategy_id == "llm_judge"

    def test_resolve_unknown_strategy(self, scoring_engine):
        """Test resolving unknown strategy raises error."""
        with pytest.raises(
            UnknownStrategyError, match="Unknown scoring strategy: unknown_strategy"
        ):
            scoring_engine._resolve_strategy("unknown_strategy")


class TestRawIOLoading:
    """Test raw I/O file loading."""

    def test_load_raw_io_success(self, scoring_engine, tmp_path):
        """Test loading existing raw I/O file."""
        run_id = "run-001"
        step_id = "s1_findings"

        # Create raw I/O file
        run_dir = tmp_path / run_id
        run_dir.mkdir()
        io_file = run_dir / f"{step_id}.json"

        io_data = {
            "run_id": run_id,
            "case_set_id": "pr_review_cases_v1",
            "case_id": "pr_001",
            "step_id": step_id,
            "agent_id": "gpt-4o-mini",
            "request": {"prompt": "test"},
            "response": "test response",
            "latency_ms": 1000,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        io_file.write_text(json.dumps(io_data))

        result = scoring_engine._load_raw_io(run_id, step_id)

        assert result["run_id"] == run_id
        assert result["step_id"] == step_id
        assert result["response"] == "test response"

    def test_load_raw_io_not_found(self, scoring_engine):
        """Test loading non-existent raw I/O file raises error."""
        with pytest.raises(RawIONotFoundError, match="Raw I/O file not found"):
            scoring_engine._load_raw_io("nonexistent", "step-001")

    def test_load_raw_io_malformed_json(self, scoring_engine, tmp_path):
        """Test loading malformed JSON raises error."""
        run_id = "run-001"
        step_id = "s1_findings"

        run_dir = tmp_path / run_id
        run_dir.mkdir()
        io_file = run_dir / f"{step_id}.json"
        io_file.write_text("not valid json")

        with pytest.raises(ValueError, match="Malformed JSON"):
            scoring_engine._load_raw_io(run_id, step_id)


class TestScoreStep:
    """Test individual step scoring."""

    @patch("agentbench.scoring.engine.load_case")
    def test_score_step_finding_match(
        self, mock_load_case, scoring_engine, sample_step, sample_case, sample_agent_response
    ):
        """Test scoring a step with finding_match strategy."""
        mock_load_case.return_value = sample_case

        score = scoring_engine._score_step(
            step=sample_step,
            response_text=sample_agent_response,
            run_id="run-001",
            case_id="pr_001_missing_auth_check",
            latency_ms=1000,
            case=sample_case,
        )

        assert isinstance(score, StepScore)
        assert score.run_id == "run-001"
        assert score.case_id == "pr_001_missing_auth_check"
        assert score.step_id == "s1_findings"
        assert score.strategy == "finding_match"
        assert score.latency_ms == 1000
        # Should get a good score for matching the expected finding
        assert score.raw_score >= 0.5
        assert score.weighted_score == score.raw_score * 2.0  # weight is 2.0

    @patch("agentbench.scoring.engine.load_case")
    def test_score_step_with_invalid_response(
        self, mock_load_case, scoring_engine, sample_step, sample_case
    ):
        """Test scoring with invalid JSON response."""
        mock_load_case.return_value = sample_case

        score = scoring_engine._score_step(
            step=sample_step,
            response_text="not valid json",
            run_id="run-001",
            case_id="pr_001",
            latency_ms=1000,
            case=sample_case,
        )

        assert score.raw_score == 0.0
        assert score.weighted_score == 0.0
        assert score.passed is False
        assert "parse_failure" in score.details["error"]


class TestProcessResponse:
    """Test processing agent response events."""

    @pytest.mark.asyncio
    async def test_process_response_success(
        self, scoring_engine, sample_run, sample_workflow, sample_case, sample_agent_response
    ):
        """Test successful processing of agent response."""
        # Setup mocks
        scoring_engine.mongo_storage.get_run.return_value = sample_run
        scoring_engine.mongo_storage.get_workflow.return_value = sample_workflow

        # Create raw I/O file
        run_dir = scoring_engine.raw_io_dir / sample_run.run_id
        run_dir.mkdir()
        io_file = run_dir / "s1_findings.json"
        io_data = {
            "run_id": sample_run.run_id,
            "case_set_id": sample_run.case_set_id,
            "case_id": sample_run.case_id,
            "step_id": "s1_findings",
            "agent_id": sample_run.agent_id,
            "request": {"prompt": "test"},
            "response": sample_agent_response,
            "latency_ms": 1000,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        io_file.write_text(json.dumps(io_data))

        # Create fixtures directory and case
        fixtures_dir = (
            scoring_engine.raw_io_dir.parent / sample_run.case_set_id / "cases" / sample_run.case_id
        )
        fixtures_dir.mkdir(parents=True)
        (fixtures_dir / "ticket.md").write_text("Test ticket")
        (fixtures_dir / "diff.patch").write_text("Test diff")
        (fixtures_dir / "ground_truth.json").write_text(
            json.dumps(
                {
                    "case_id": sample_run.case_id,
                    "expected_findings": [
                        {
                            "finding_id": "F1",
                            "canonical_label": "missing_permission_check",
                            "severity": "high",
                            "file_path": "app/api/admin.py",
                            "line_span": [42, 57],
                            "must_detect": True,
                            "summary": "Missing auth check",
                        }
                    ],
                    "disallowed_findings": [{"canonical_label": "style_only_nit"}],
                }
            )
        )
        (fixtures_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "case_set_id": sample_run.case_set_id,
                    "difficulty": "medium",
                    "tags": ["auth"],
                }
            )
        )

        # Create event envelope
        envelope = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=AGENT_RESPONSE_RECEIVED,
            timestamp=datetime.now(timezone.utc).isoformat(),
            correlation_id=sample_run.run_id,
            payload={
                "run_id": sample_run.run_id,
                "step_id": "s1_findings",
                "latency_ms": 1000,
            },
        )

        with patch("agentbench.scoring.engine.load_case") as mock_load_case:
            mock_load_case.return_value = sample_case

            score = await scoring_engine._process_response(envelope)

        assert score is not None
        assert score.run_id == sample_run.run_id
        assert score.step_id == "s1_findings"
        assert score.strategy == "finding_match"

    @pytest.mark.asyncio
    async def test_process_response_missing_run(self, scoring_engine):
        """Test processing when run is not found."""
        scoring_engine.mongo_storage.get_run.return_value = None

        envelope = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=AGENT_RESPONSE_RECEIVED,
            timestamp=datetime.now(timezone.utc).isoformat(),
            correlation_id="run-001",
            payload={
                "run_id": "run-001",
                "step_id": "s1_findings",
                "latency_ms": 1000,
            },
        )

        score = await scoring_engine._process_response(envelope)

        assert score is None

    @pytest.mark.asyncio
    async def test_process_response_missing_workflow(self, scoring_engine, sample_run):
        """Test processing when workflow is not found."""
        scoring_engine.mongo_storage.get_run.return_value = sample_run
        scoring_engine.mongo_storage.get_workflow.return_value = None

        envelope = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=AGENT_RESPONSE_RECEIVED,
            timestamp=datetime.now(timezone.utc).isoformat(),
            correlation_id=sample_run.run_id,
            payload={
                "run_id": sample_run.run_id,
                "step_id": "s1_findings",
                "latency_ms": 1000,
            },
        )

        score = await scoring_engine._process_response(envelope)

        assert score is None

    @pytest.mark.asyncio
    async def test_process_response_missing_step(self, scoring_engine, sample_run, sample_workflow):
        """Test processing when step is not found in workflow."""
        # Create workflow with different step
        from agentbench.models import WorkflowDefinition, StepDefinition, ScoringConfig

        workflow = WorkflowDefinition(
            workflow_id="wf_pr_review_v1",
            version="1.0.0",
            status="published",
            description="PR review workflow",
            steps=[
                StepDefinition(
                    step_id="different_step",
                    order=0,
                    input="Test",
                    scoring=ScoringConfig(strategy="finding_match"),
                )
            ],
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        scoring_engine.mongo_storage.get_run.return_value = sample_run
        scoring_engine.mongo_storage.get_workflow.return_value = workflow

        envelope = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=AGENT_RESPONSE_RECEIVED,
            timestamp=datetime.now(timezone.utc).isoformat(),
            correlation_id=sample_run.run_id,
            payload={
                "run_id": sample_run.run_id,
                "step_id": "s1_findings",  # This step doesn't exist in workflow
                "latency_ms": 1000,
            },
        )

        score = await scoring_engine._process_response(envelope)

        assert score is None

    @pytest.mark.asyncio
    async def test_process_response_missing_raw_io(
        self, scoring_engine, sample_run, sample_workflow
    ):
        """Test processing when raw I/O file is missing."""
        scoring_engine.mongo_storage.get_run.return_value = sample_run
        scoring_engine.mongo_storage.get_workflow.return_value = sample_workflow

        envelope = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=AGENT_RESPONSE_RECEIVED,
            timestamp=datetime.now(timezone.utc).isoformat(),
            correlation_id=sample_run.run_id,
            payload={
                "run_id": sample_run.run_id,
                "step_id": "s1_findings",
                "latency_ms": 1000,
            },
        )

        score = await scoring_engine._process_response(envelope)

        assert score is None


class TestEventConsumption:
    """Test the main event consumption loop."""

    @pytest.mark.asyncio
    async def test_run_consumes_events(self, scoring_engine, mock_event_bus):
        """Test that run() consumes events from the bus."""
        # Replace the event_bus with a fresh mock
        scoring_engine.event_bus = mock_event_bus

        # Create a mock envelope
        envelope = MagicMock()
        envelope.event_type = AGENT_RESPONSE_RECEIVED
        envelope.payload = {"run_id": "run-001", "step_id": "s1", "latency_ms": 100}
        envelope.correlation_id = "run-001"
        envelope._message_id = b"123-0"

        # Track calls to consume
        call_count = 0

        # Mock the consume method to yield one envelope then stop
        async def mock_consume(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield envelope
                # Set running to False to break the loop
                scoring_engine._running = False

        mock_event_bus.consume = mock_consume
        scoring_engine.mongo_storage.get_run.return_value = None  # Will fail early

        await scoring_engine.run()

        # Verify consume was called (we can't use assert_called_once_with because
        # it's now a function, but we can verify it was invoked by checking call_count)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_run_skips_non_response_events(self, scoring_engine):
        """Test that non agent.response.received events are acknowledged but not processed."""
        # Create a mock envelope for a different event type
        envelope = MagicMock()
        envelope.event_type = "workflow.step.dispatched"
        envelope.payload = {"run_id": "run-001", "step_id": "s1"}
        envelope.correlation_id = "run-001"
        envelope._message_id = b"123-0"

        call_count = 0

        async def mock_consume(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield envelope
                scoring_engine._running = False

        scoring_engine.event_bus.consume = mock_consume

        await scoring_engine.run()

        # Verify the message was acknowledged
        scoring_engine.event_bus.ack.assert_called_with(
            STREAM_EVAL_STEPS,
            "scoring",
            b"123-0",
        )


class TestEventEmission:
    """Test event emission."""

    @pytest.mark.asyncio
    async def test_run_emits_step_scored(
        self, scoring_engine, sample_run, sample_workflow, sample_case, sample_agent_response
    ):
        """Test that successful scoring emits step.scored event."""
        # Setup mocks
        scoring_engine.mongo_storage.get_run.return_value = sample_run
        scoring_engine.mongo_storage.get_workflow.return_value = sample_workflow

        # Create raw I/O file
        run_dir = scoring_engine.raw_io_dir / sample_run.run_id
        run_dir.mkdir()
        io_file = run_dir / "s1_findings.json"
        io_data = {
            "run_id": sample_run.run_id,
            "case_set_id": sample_run.case_set_id,
            "case_id": sample_run.case_id,
            "step_id": "s1_findings",
            "agent_id": sample_run.agent_id,
            "request": {"prompt": "test"},
            "response": sample_agent_response,
            "latency_ms": 1000,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        io_file.write_text(json.dumps(io_data))

        # Create event envelope
        envelope = MagicMock()
        envelope.event_type = AGENT_RESPONSE_RECEIVED
        envelope.payload = {
            "run_id": sample_run.run_id,
            "step_id": "s1_findings",
            "latency_ms": 1000,
        }
        envelope.correlation_id = sample_run.run_id
        envelope._message_id = b"123-0"

        call_count = 0

        async def mock_consume(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield envelope
                scoring_engine._running = False

        scoring_engine.event_bus.consume = mock_consume

        with patch("agentbench.scoring.engine.load_case") as mock_load_case:
            mock_load_case.return_value = sample_case
            await scoring_engine.run()

        # Verify step.scored event was published
        scoring_engine.event_bus.publish.assert_called_once()
        call_args = scoring_engine.event_bus.publish.call_args
        assert call_args[0][0] == STREAM_SCORES
        event = call_args[0][1]
        assert event.event_type == STEP_SCORED
        assert event.payload["run_id"] == sample_run.run_id
        assert event.payload["case_id"] == sample_run.case_id
        assert event.payload["step_id"] == "s1_findings"
        assert "score" in event.payload
        assert "weighted_score" in event.payload


class TestStop:
    """Test the stop functionality."""

    def test_stop_sets_running_false(self, scoring_engine):
        """Test that stop() sets _running to False."""
        scoring_engine._running = True

        # stop is async, so we need to run it
        import asyncio

        asyncio.run(scoring_engine.stop())

        assert scoring_engine._running is False


class TestDirectScoreResponse:
    """Test the direct score_response method."""

    @pytest.mark.asyncio
    async def test_score_response_direct(
        self, scoring_engine, sample_run, sample_step, sample_case, sample_agent_response
    ):
        """Test scoring a response directly without event bus."""
        with patch("agentbench.scoring.engine.load_case") as mock_load_case:
            mock_load_case.return_value = sample_case

            score = await scoring_engine.score_response(
                run=sample_run,
                step=sample_step,
                response_text=sample_agent_response,
                latency_ms=1000,
            )

        assert isinstance(score, StepScore)
        assert score.run_id == sample_run.run_id
        assert score.case_id == sample_run.case_id
        assert score.step_id == sample_step.step_id

    @pytest.mark.asyncio
    async def test_score_response_unknown_strategy(
        self, scoring_engine, sample_run, sample_case, sample_agent_response
    ):
        """Test that unknown strategy raises error."""
        # Create a step with valid config, then patch the strategy_id
        step = StepDefinition(
            step_id="test",
            order=0,
            input="Test",
            scoring=ScoringConfig(strategy="finding_match"),  # Valid strategy first
        )

        # Manually set an invalid strategy to trigger UnknownStrategyError
        step.scoring.strategy = "unknown_strategy"  # type: ignore

        with patch("agentbench.scoring.engine.load_case") as mock_load_case:
            mock_load_case.return_value = sample_case

            with pytest.raises(UnknownStrategyError):
                await scoring_engine.score_response(
                    run=sample_run,
                    step=step,
                    response_text=sample_agent_response,
                    latency_ms=1000,
                )


class TestStrategyRegistry:
    """Test the strategy registry."""

    def test_strategy_registry_contents(self):
        """Test that the registry contains expected strategies."""
        registry = ScoringEngine.STRATEGY_REGISTRY

        assert "finding_match" in registry
        assert "llm_judge" in registry
        assert registry["finding_match"] == FindingMatchStrategy
        assert registry["llm_judge"] == LLMJudgeStrategy

    def test_strategy_registry_immutability(self):
        """Test that the registry can be extended (but not accidentally)."""
        # The registry is a class attribute, so modifications affect all instances
        # But we can add new strategies if needed
        registry = ScoringEngine.STRATEGY_REGISTRY

        # Check it's a dict
        assert isinstance(registry, dict)
        # Check it has the expected keys
        assert len(registry) >= 2
