"""Unit tests for the Aggregator service.

Tests cover:
- Score accumulation
- Run report generation
- Benchmark report generation
- Percentile calculation
- Event handling
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentbench.aggregator import Aggregator
from agentbench.models import (
    STEP_SCORED,
    WORKFLOW_COMPLETED,
    BenchmarkReport,
    EventEnvelope,
    RunReport,
    RunState,
    StepScore,
)
from agentbench.models.run import EvaluationRun


@pytest.fixture
def mock_event_bus():
    """Create a mock EventBus."""
    bus = MagicMock()
    bus.consume = AsyncMock()
    bus.ack = AsyncMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def mock_mongo_storage():
    """Create a mock MongoStorage."""
    storage = MagicMock()
    storage.get_run = AsyncMock()
    storage.create_run_report = AsyncMock()
    storage.get_run_report = AsyncMock()
    storage.create_benchmark_report = AsyncMock()
    return storage


@pytest.fixture
def mock_redis_storage():
    """Create a mock RedisStorage."""
    storage = MagicMock()
    storage.is_benchmark_complete = AsyncMock(return_value=False)
    storage.mark_run_completed = AsyncMock()
    storage.get_benchmark_completed_runs = AsyncMock(return_value=set())
    return storage


@pytest.fixture
def aggregator(mock_event_bus, mock_mongo_storage, mock_redis_storage):
    """Create an Aggregator instance with mocked dependencies."""
    return Aggregator(
        event_bus=mock_event_bus,
        mongo_storage=mock_mongo_storage,
        redis_storage=mock_redis_storage,
    )


class TestScoreAccumulation:
    """Tests for step score accumulation."""

    async def test_accumulate_single_score(self, aggregator):
        """Test accumulating a single step score."""
        # Arrange
        envelope = EventEnvelope(
            event_id="evt-1",
            event_type=STEP_SCORED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id="run-1",
            payload={
                "run_id": "run-1",
                "case_id": "case-1",
                "step_id": "s1_findings",
                "strategy": "finding_match",
                "raw_score": 0.85,
                "weighted_score": 1.7,
                "latency_ms": 500,
                "passed": True,
                "details": {"matches": 2},
            },
        )

        # Act
        aggregator._handle_step_scored(envelope)

        # Assert
        scores = aggregator.get_accumulated_scores("run-1")
        assert len(scores) == 1
        assert scores[0].run_id == "run-1"
        assert scores[0].step_id == "s1_findings"
        assert scores[0].weighted_score == 1.7
        assert scores[0].latency_ms == 500

    async def test_accumulate_multiple_scores_same_run(self, aggregator):
        """Test accumulating multiple scores for the same run."""
        # Arrange
        for i in range(3):
            envelope = EventEnvelope(
                event_id=f"evt-{i}",
                event_type=STEP_SCORED,
                timestamp=datetime.now(UTC).isoformat(),
                correlation_id="run-1",
                payload={
                    "run_id": "run-1",
                    "case_id": "case-1",
                    "step_id": f"step-{i}",
                    "strategy": "finding_match",
                    "raw_score": 0.8,
                    "weighted_score": 1.6,
                    "latency_ms": 400 + i * 100,
                    "passed": True,
                    "details": {},
                },
            )
            aggregator._handle_step_scored(envelope)

        # Assert
        scores = aggregator.get_accumulated_scores("run-1")
        assert len(scores) == 3
        total_latency = sum(s.latency_ms for s in scores)
        assert total_latency == 400 + 500 + 600

    async def test_accumulate_scores_different_runs(self, aggregator):
        """Test accumulating scores for different runs."""
        # Arrange
        for run_id in ["run-1", "run-2"]:
            envelope = EventEnvelope(
                event_id=f"evt-{run_id}",
                event_type=STEP_SCORED,
                timestamp=datetime.now(UTC).isoformat(),
                correlation_id=run_id,
                payload={
                    "run_id": run_id,
                    "case_id": "case-1",
                    "step_id": "s1_findings",
                    "strategy": "finding_match",
                    "raw_score": 0.75,
                    "weighted_score": 1.5,
                    "latency_ms": 300,
                    "passed": True,
                    "details": {},
                },
            )
            aggregator._handle_step_scored(envelope)

        # Assert
        assert len(aggregator.get_accumulated_scores("run-1")) == 1
        assert len(aggregator.get_accumulated_scores("run-2")) == 1


class TestRunReportGeneration:
    """Tests for RunReport generation."""

    async def test_compute_run_report(self, aggregator):
        """Test computing a run report from scores."""
        # Arrange
        scores = [
            StepScore(
                run_id="run-1",
                case_id="case-1",
                step_id="s1_findings",
                strategy="finding_match",
                raw_score=0.85,
                weight=2.0,
                weighted_score=1.7,
                latency_ms=500,
                passed=True,
            ),
            StepScore(
                run_id="run-1",
                case_id="case-1",
                step_id="s2_summary",
                strategy="llm_judge",
                raw_score=0.7,
                weight=1.0,
                weighted_score=0.7,
                latency_ms=300,
                passed=True,
            ),
        ]

        # Act
        report = aggregator._compute_run_report(
            run_id="run-1",
            benchmark_id="bench-1",
            case_id="case-1",
            case_tags=["auth", "api"],
            agent_id="gpt-4o-mini",
            workflow_id="wf_pr_review_v1",
            scores=scores,
        )

        # Assert
        assert isinstance(report, RunReport)
        assert report.run_id == "run-1"
        assert report.benchmark_id == "bench-1"
        assert report.case_id == "case-1"
        assert report.case_tags == ["auth", "api"]
        assert report.agent_id == "gpt-4o-mini"
        assert report.total_score == pytest.approx(0.8)  # (1.7 + 0.7) / (2.0 + 1.0)
        assert report.total_latency_ms == 800  # 500 + 300
        assert len(report.step_scores) == 2
        assert report.workflow_id == "wf_pr_review_v1"

    async def test_handle_workflow_completed(self, aggregator, mock_mongo_storage):
        """Test handling workflow.completed event."""
        # Arrange - First accumulate some scores
        score_envelope = EventEnvelope(
            event_id="evt-1",
            event_type=STEP_SCORED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id="run-1",
            payload={
                "run_id": "run-1",
                "case_id": "case-1",
                "step_id": "s1_findings",
                "strategy": "finding_match",
                "raw_score": 0.85,
                "weight": 2.0,
                "weighted_score": 1.7,
                "latency_ms": 500,
                "passed": True,
                "details": {},
            },
        )
        aggregator._handle_step_scored(score_envelope)

        # Mock run retrieval
        mock_run = EvaluationRun(
            run_id="run-1",
            benchmark_id="bench-1",
            workflow_id="wf_pr_review_v1",
            workflow_version="1.0.0",
            case_set_id="pr_review_cases_v1",
            case_id="case-1",
            agent_id="gpt-4o-mini",
            agent_config={"model": "gpt-4o-mini"},
            state=RunState.COMPLETED,
            current_step=1,
            created_at=datetime.now(UTC).isoformat(),
        )
        mock_mongo_storage.get_run.return_value = mock_run

        # Mock load_case to return a case with tags
        with patch("agentbench.aggregator.aggregator.load_case") as mock_load_case:
            mock_case = MagicMock()
            mock_case.tags = ["testing", "coverage"]
            mock_load_case.return_value = mock_case

            # Act - Send workflow completed event
            workflow_envelope = EventEnvelope(
                event_id="evt-2",
                event_type=WORKFLOW_COMPLETED,
                timestamp=datetime.now(UTC).isoformat(),
                correlation_id="run-1",
                payload={
                    "run_id": "run-1",
                    "benchmark_id": "bench-1",
                    "workflow_id": "wf_pr_review_v1",
                },
            )
            await aggregator._handle_workflow_completed(workflow_envelope)

            # Assert
            mock_mongo_storage.create_run_report.assert_called_once()
            report = mock_mongo_storage.create_run_report.call_args[0][0]
            assert isinstance(report, RunReport)
            assert report.run_id == "run-1"
            assert report.total_score == 0.85  # 1.7 / 2.0
            # Verify case_tags were loaded from case
            assert report.case_tags == ["testing", "coverage"]

    async def test_handle_workflow_completed_no_scores(
        self, aggregator, mock_mongo_storage, caplog
    ):
        """Test handling workflow.completed when no scores were accumulated."""
        # Arrange
        workflow_envelope = EventEnvelope(
            event_id="evt-1",
            event_type=WORKFLOW_COMPLETED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id="run-1",
            payload={
                "run_id": "run-1",
                "benchmark_id": "bench-1",
                "workflow_id": "wf_pr_review_v1",
            },
        )

        # Act
        with caplog.at_level("WARNING"):
            await aggregator._handle_workflow_completed(workflow_envelope)

        # Assert
        mock_mongo_storage.create_run_report.assert_not_called()
        assert "No scores accumulated for run run-1" in caplog.text

    async def test_handle_workflow_completed_run_not_found(
        self, aggregator, mock_mongo_storage, caplog
    ):
        """Test handling workflow.completed when run is not found."""
        # Arrange - First accumulate some scores
        score_envelope = EventEnvelope(
            event_id="evt-1",
            event_type=STEP_SCORED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id="run-1",
            payload={
                "run_id": "run-1",
                "case_id": "case-1",
                "step_id": "s1_findings",
                "strategy": "finding_match",
                "raw_score": 0.85,
                "weight": 2.0,
                "weighted_score": 1.7,
                "latency_ms": 500,
                "passed": True,
                "details": {},
            },
        )
        aggregator._handle_step_scored(score_envelope)

        # Mock run retrieval to return None
        mock_mongo_storage.get_run.return_value = None

        # Act
        workflow_envelope = EventEnvelope(
            event_id="evt-2",
            event_type=WORKFLOW_COMPLETED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id="run-1",
            payload={
                "run_id": "run-1",
                "benchmark_id": "bench-1",
                "workflow_id": "wf_pr_review_v1",
            },
        )
        with caplog.at_level("ERROR"):
            await aggregator._handle_workflow_completed(workflow_envelope)

        # Assert
        mock_mongo_storage.create_run_report.assert_not_called()
        assert "Run not found: run-1" in caplog.text


class TestBenchmarkReportGeneration:
    """Tests for BenchmarkReport generation."""

    async def test_compute_benchmark_report(self, aggregator):
        """Test computing a benchmark report from run reports."""
        # Arrange
        run_reports = [
            RunReport(
                run_id="run-1",
                benchmark_id="bench-1",
                case_id="case-1",
                case_tags=["auth"],
                agent_id="gpt-4o-mini",
                workflow_id="wf_pr_review_v1",
                total_score=2.5,
                step_scores=[
                    StepScore(
                        run_id="run-1",
                        case_id="case-1",
                        step_id="s1_findings",
                        strategy="finding_match",
                        raw_score=0.8,
                        weighted_score=1.6,
                        latency_ms=400,
                        passed=True,
                    ),
                    StepScore(
                        run_id="run-1",
                        case_id="case-1",
                        step_id="s2_summary",
                        strategy="llm_judge",
                        raw_score=0.9,
                        weighted_score=0.9,
                        latency_ms=200,
                        passed=True,
                    ),
                ],
                total_latency_ms=600,
                completed_at=datetime.now(UTC).isoformat(),
            ),
            RunReport(
                run_id="run-2",
                benchmark_id="bench-1",
                case_id="case-1",
                case_tags=["auth"],
                agent_id="claude-haiku-4-5",
                workflow_id="wf_pr_review_v1",
                total_score=2.2,
                step_scores=[
                    StepScore(
                        run_id="run-2",
                        case_id="case-1",
                        step_id="s1_findings",
                        strategy="finding_match",
                        raw_score=0.7,
                        weighted_score=1.4,
                        latency_ms=500,
                        passed=True,
                    ),
                    StepScore(
                        run_id="run-2",
                        case_id="case-1",
                        step_id="s2_summary",
                        strategy="llm_judge",
                        raw_score=0.8,
                        weighted_score=0.8,
                        latency_ms=250,
                        passed=True,
                    ),
                ],
                total_latency_ms=750,
                completed_at=datetime.now(UTC).isoformat(),
            ),
        ]

        # Act
        report = aggregator._compute_benchmark_report(
            benchmark_id="bench-1",
            workflow_id="wf_pr_review_v1",
            case_set_id="pr_review_cases_v1",
            run_reports=run_reports,
        )

        # Assert
        assert isinstance(report, BenchmarkReport)
        assert report.benchmark_id == "bench-1"
        assert report.workflow_id == "wf_pr_review_v1"
        assert report.case_set_id == "pr_review_cases_v1"
        assert report.case_count == 1  # Only case-1
        assert len(report.agents) == 2

        # Check per-case scores
        assert "case-1" in report.per_case_scores
        assert report.per_case_scores["case-1"]["gpt-4o-mini"] == 2.5
        assert report.per_case_scores["case-1"]["claude-haiku-4-5"] == 2.2

        # Check per-case topics
        assert report.per_case_topics["case-1"] == "Auth/Security"  # tag ["auth"]

    async def test_compute_benchmark_report_multiple_cases(self, aggregator):
        """Test computing a benchmark report with multiple cases."""
        # Arrange
        run_reports = [
            # Agent 1, Case 1
            RunReport(
                run_id="run-1",
                benchmark_id="bench-1",
                case_id="case-1",
                case_tags=["auth"],
                agent_id="gpt-4o-mini",
                workflow_id="wf_pr_review_v1",
                total_score=2.0,
                step_scores=[],
                total_latency_ms=500,
                completed_at=datetime.now(UTC).isoformat(),
            ),
            # Agent 1, Case 2
            RunReport(
                run_id="run-2",
                benchmark_id="bench-1",
                case_id="case-2",
                case_tags=["api"],
                agent_id="gpt-4o-mini",
                workflow_id="wf_pr_review_v1",
                total_score=1.8,
                step_scores=[],
                total_latency_ms=450,
                completed_at=datetime.now(UTC).isoformat(),
            ),
            # Agent 2, Case 1
            RunReport(
                run_id="run-3",
                benchmark_id="bench-1",
                case_id="case-1",
                case_tags=["auth"],
                agent_id="claude-haiku-4-5",
                workflow_id="wf_pr_review_v1",
                total_score=1.9,
                step_scores=[],
                total_latency_ms=550,
                completed_at=datetime.now(UTC).isoformat(),
            ),
            # Agent 2, Case 2
            RunReport(
                run_id="run-4",
                benchmark_id="bench-1",
                case_id="case-2",
                case_tags=["api"],
                agent_id="claude-haiku-4-5",
                workflow_id="wf_pr_review_v1",
                total_score=2.1,
                step_scores=[],
                total_latency_ms=600,
                completed_at=datetime.now(UTC).isoformat(),
            ),
        ]

        # Act
        report = aggregator._compute_benchmark_report(
            benchmark_id="bench-1",
            workflow_id="wf_pr_review_v1",
            case_set_id="pr_review_cases_v1",
            run_reports=run_reports,
        )

        # Assert
        assert report.case_count == 2

        # Check agent summaries
        gpt_summary = next(a for a in report.agents if a.agent_id == "gpt-4o-mini")
        assert gpt_summary.avg_score == 1.9  # (2.0 + 1.8) / 2

        claude_summary = next(a for a in report.agents if a.agent_id == "claude-haiku-4-5")
        assert claude_summary.avg_score == 2.0  # (1.9 + 2.1) / 2

        # Check per-case topics
        assert report.per_case_topics["case-1"] == "Auth/Security"  # tag ["auth"]
        assert report.per_case_topics["case-2"] == "Other"  # tag ["api"] -> no match
        assert claude_summary.avg_score == 2.0  # (1.9 + 2.1) / 2

    async def test_generate_benchmark_report_when_complete(
        self, aggregator, mock_mongo_storage, mock_redis_storage, mock_event_bus
    ):
        """Test generating benchmark report when all runs complete."""
        # Arrange - Setup completed runs
        mock_redis_storage.is_benchmark_complete.return_value = True
        mock_redis_storage.get_benchmark_completed_runs.return_value = {"run-1", "run-2"}

        # Setup run reports
        run_reports = [
            RunReport(
                run_id="run-1",
                benchmark_id="bench-1",
                case_id="case-1",
                case_tags=["auth"],
                agent_id="gpt-4o-mini",
                workflow_id="wf_pr_review_v1",
                total_score=2.0,
                step_scores=[],
                total_latency_ms=500,
                completed_at=datetime.now(UTC).isoformat(),
            ),
            RunReport(
                run_id="run-2",
                benchmark_id="bench-1",
                case_id="case-1",
                case_tags=["auth"],
                agent_id="claude-haiku-4-5",
                workflow_id="wf_pr_review_v1",
                total_score=1.8,
                step_scores=[],
                total_latency_ms=550,
                completed_at=datetime.now(UTC).isoformat(),
            ),
        ]
        mock_mongo_storage.get_run_report.side_effect = lambda run_id: next(
            (r for r in run_reports if r.run_id == run_id), None
        )

        # Setup run retrieval for case_set_id
        mock_run = EvaluationRun(
            run_id="run-1",
            benchmark_id="bench-1",
            workflow_id="wf_pr_review_v1",
            workflow_version="1.0.0",
            case_set_id="pr_review_cases_v1",
            case_id="case-1",
            agent_id="gpt-4o-mini",
            agent_config={},
            state=RunState.COMPLETED,
            current_step=1,
            created_at=datetime.now(UTC).isoformat(),
        )
        mock_mongo_storage.get_run.return_value = mock_run

        # Act
        await aggregator._generate_benchmark_report("bench-1")

        # Assert
        mock_mongo_storage.create_benchmark_report.assert_called_once()
        mock_event_bus.publish.assert_called_once()

        # Verify the event published
        call_args = mock_event_bus.publish.call_args
        assert call_args[0][0] == "stream:reports"
        event = call_args[0][1]
        assert event.event_type == "benchmark.report.generated"
        assert event.payload["benchmark_id"] == "bench-1"

    async def test_generate_benchmark_report_no_reports(
        self, aggregator, mock_mongo_storage, mock_redis_storage, caplog
    ):
        """Test generating benchmark report when no run reports exist."""
        # Arrange
        mock_redis_storage.get_benchmark_completed_runs.return_value = set()

        # Act
        with caplog.at_level("WARNING"):
            await aggregator._generate_benchmark_report("bench-1")

        # Assert
        mock_mongo_storage.create_benchmark_report.assert_not_called()
        assert "No run reports found for benchmark bench-1" in caplog.text


class TestPercentileCalculation:
    """Tests for percentile calculation."""

    def test_calculate_percentile_empty_list(self, aggregator):
        """Test percentile calculation with empty list."""
        result = aggregator._calculate_percentile([], 50)
        assert result == 0

    def test_calculate_percentile_single_value(self, aggregator):
        """Test percentile calculation with single value."""
        result = aggregator._calculate_percentile([100], 50)
        assert result == 100

    def test_calculate_percentile_median(self, aggregator):
        """Test percentile calculation for median (p50)."""
        values = [100, 200, 300, 400, 500]
        result = aggregator._calculate_percentile(values, 50)
        # Nearest rank: index = 5 * 50 / 100 = 2.5 -> int -> 2
        assert result == values[2]  # 300

    def test_calculate_percentile_p95(self, aggregator):
        """Test percentile calculation for p95."""
        values = list(range(100))  # 0 to 99
        result = aggregator._calculate_percentile(values, 95)
        # index = 100 * 95 / 100 = 95
        assert result == 95


class TestAggregatorLifecycle:
    """Tests for aggregator start/stop lifecycle."""

    async def test_stop_sets_running_false(self, aggregator):
        """Test that stop() sets _running to False."""
        aggregator._running = True
        await aggregator.stop()
        assert aggregator._running is False

    async def test_run_loop_processes_events(self, aggregator, mock_event_bus, mock_mongo_storage):
        """Test that run() processes events from the stream."""
        # Arrange
        score_event = EventEnvelope(
            event_id="evt-1",
            event_type=STEP_SCORED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id="run-1",
            payload={
                "run_id": "run-1",
                "case_id": "case-1",
                "step_id": "s1_findings",
                "strategy": "finding_match",
                "raw_score": 0.85,
                "weighted_score": 1.7,
                "latency_ms": 500,
                "passed": True,
                "details": {},
            },
        )
        score_event.delivery_message_id = "msg-1"

        # Mock the consume method to yield one event then stop
        async def mock_consume(*args, **kwargs):
            yield score_event
            aggregator._running = False  # Stop after one event

        mock_event_bus.consume = mock_consume
        mock_event_bus.ack = AsyncMock()

        # Act
        await aggregator.run()

        # Assert
        assert len(aggregator.get_accumulated_scores("run-1")) == 1

    async def test_run_loop_retries_known_validation_failures(self, aggregator, mock_event_bus):
        """Known validation failures should be logged and retried without crashing the loop."""
        invalid_event = EventEnvelope(
            event_id="evt-invalid",
            event_type=STEP_SCORED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id="run-1",
            payload={
                "run_id": "run-1",
                "case_id": "case-1",
                "step_id": "s1_findings",
                "strategy": "finding_match",
                "raw_score": "bad-score",
                "weighted_score": 1.7,
                "latency_ms": 500,
                "passed": True,
                "details": {},
            },
        )

        consume_calls = 0

        async def mock_consume(*args, **kwargs):
            nonlocal consume_calls
            consume_calls += 1
            if consume_calls == 1:
                yield invalid_event
            else:
                aggregator._running = False
                return

        mock_event_bus.consume = mock_consume

        await aggregator.run()

        assert aggregator.get_accumulated_scores("run-1") == []

    async def test_run_loop_re_raises_unexpected_errors(self, aggregator, mock_event_bus):
        """Unexpected errors should escape instead of being swallowed forever."""
        score_event = EventEnvelope(
            event_id="evt-1",
            event_type=STEP_SCORED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id="run-1",
            payload={
                "run_id": "run-1",
                "case_id": "case-1",
                "step_id": "s1_findings",
                "strategy": "finding_match",
                "raw_score": 0.85,
                "weighted_score": 1.7,
                "latency_ms": 500,
                "passed": True,
                "details": {},
            },
        )

        consume_calls = 0

        async def mock_consume(*args, **kwargs):
            nonlocal consume_calls
            consume_calls += 1
            if consume_calls == 1:
                yield score_event
            else:
                aggregator._running = False
                return

        mock_event_bus.consume = mock_consume

        with (
            patch.object(aggregator, "_handle_step_scored", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            await aggregator.run()


class TestUtilityMethods:
    """Tests for utility methods."""

    def test_clear_accumulated_scores_single_run(self, aggregator):
        """Test clearing scores for a specific run."""
        # Arrange
        aggregator._run_scores["run-1"] = [MagicMock()]
        aggregator._run_scores["run-2"] = [MagicMock()]

        # Act
        aggregator.clear_accumulated_scores("run-1")

        # Assert
        assert "run-1" not in aggregator._run_scores
        assert "run-2" in aggregator._run_scores

    def test_clear_accumulated_scores_all(self, aggregator):
        """Test clearing all accumulated scores."""
        # Arrange
        aggregator._run_scores["run-1"] = [MagicMock()]
        aggregator._run_scores["run-2"] = [MagicMock()]

        # Act
        aggregator.clear_accumulated_scores()

        # Assert
        assert len(aggregator._run_scores) == 0

    def test_get_accumulated_scores_existing_run(self, aggregator):
        """Test getting scores for an existing run."""
        # Arrange
        score = MagicMock()
        aggregator._run_scores["run-1"] = [score]

        # Act
        result = aggregator.get_accumulated_scores("run-1")

        # Assert
        assert result == [score]

    def test_get_accumulated_scores_missing_run(self, aggregator):
        """Test getting scores for a non-existent run."""
        # Act
        result = aggregator.get_accumulated_scores("non-existent")

        # Assert
        assert result == []


class TestStepBreakdown:
    """Tests for step breakdown in agent summaries."""

    async def test_step_breakdown_computation(self, aggregator):
        """Test that step breakdown is correctly computed per agent."""
        # Arrange
        run_reports = [
            RunReport(
                run_id="run-1",
                benchmark_id="bench-1",
                case_id="case-1",
                case_tags=[],
                agent_id="gpt-4o-mini",
                workflow_id="wf_pr_review_v1",
                total_score=2.5,
                step_scores=[
                    StepScore(
                        run_id="run-1",
                        case_id="case-1",
                        step_id="s1_findings",
                        strategy="finding_match",
                        raw_score=0.8,
                        weighted_score=1.6,
                        latency_ms=400,
                        passed=True,
                    ),
                    StepScore(
                        run_id="run-1",
                        case_id="case-1",
                        step_id="s2_summary",
                        strategy="llm_judge",
                        raw_score=0.9,
                        weighted_score=0.9,
                        latency_ms=200,
                        passed=True,
                    ),
                ],
                total_latency_ms=600,
                completed_at=datetime.now(UTC).isoformat(),
            ),
            # Another run for same agent, same case (different case)
            RunReport(
                run_id="run-2",
                benchmark_id="bench-1",
                case_id="case-2",
                case_tags=[],
                agent_id="gpt-4o-mini",
                workflow_id="wf_pr_review_v1",
                total_score=2.0,
                step_scores=[
                    StepScore(
                        run_id="run-2",
                        case_id="case-2",
                        step_id="s1_findings",
                        strategy="finding_match",
                        raw_score=0.7,
                        weighted_score=1.4,
                        latency_ms=450,
                        passed=True,
                    ),
                    StepScore(
                        run_id="run-2",
                        case_id="case-2",
                        step_id="s2_summary",
                        strategy="llm_judge",
                        raw_score=0.6,
                        weighted_score=0.6,
                        latency_ms=220,
                        passed=True,
                    ),
                ],
                total_latency_ms=670,
                completed_at=datetime.now(UTC).isoformat(),
            ),
        ]

        # Act
        report = aggregator._compute_benchmark_report(
            benchmark_id="bench-1",
            workflow_id="wf_pr_review_v1",
            case_set_id="pr_review_cases_v1",
            run_reports=run_reports,
        )

        # Assert
        gpt_summary = next(a for a in report.agents if a.agent_id == "gpt-4o-mini")

        # Step breakdown should have averages
        assert "s1_findings" in gpt_summary.step_breakdown
        assert "s2_summary" in gpt_summary.step_breakdown

        # s1_findings raw average: (0.8 + 0.7) / 2 = 0.75
        assert gpt_summary.step_breakdown["s1_findings"] == 0.75

        # s2_summary raw average: (0.9 + 0.6) / 2 = 0.75
        assert gpt_summary.step_breakdown["s2_summary"] == 0.75


class TestPerCaseTopics:
    """Tests for per-case topic resolution in benchmark reports."""

    async def test_empty_tags_fall_back_to_other(self, aggregator):
        """Test that cases with no matching tags get 'Other' topic."""
        run_reports = [
            RunReport(
                run_id="run-1",
                benchmark_id="bench-1",
                case_id="case-x",
                case_tags=[],
                agent_id="gpt-4o-mini",
                workflow_id="wf_pr_review_v1",
                total_score=1.0,
                step_scores=[],
                total_latency_ms=100,
                completed_at=datetime.now(UTC).isoformat(),
            ),
        ]
        report = aggregator._compute_benchmark_report(
            benchmark_id="bench-1",
            workflow_id="wf_pr_review_v1",
            case_set_id="pr_review_cases_v1",
            run_reports=run_reports,
        )
        assert report.per_case_topics["case-x"] == "Other"

    async def test_topic_from_first_report_tags(self, aggregator):
        """Test that topic is resolved from first RunReport's tags per case."""
        run_reports = [
            RunReport(
                run_id="run-1",
                benchmark_id="bench-1",
                case_id="case-t",
                case_tags=["testing", "coverage"],
                agent_id="gpt-4o-mini",
                workflow_id="wf_pr_review_v1",
                total_score=1.0,
                step_scores=[],
                total_latency_ms=100,
                completed_at=datetime.now(UTC).isoformat(),
            ),
            RunReport(
                run_id="run-2",
                benchmark_id="bench-1",
                case_id="case-t",
                case_tags=["auth"],
                agent_id="claude-haiku-4-5",
                workflow_id="wf_pr_review_v1",
                total_score=1.0,
                step_scores=[],
                total_latency_ms=100,
                completed_at=datetime.now(UTC).isoformat(),
            ),
        ]
        report = aggregator._compute_benchmark_report(
            benchmark_id="bench-1",
            workflow_id="wf_pr_review_v1",
            case_set_id="pr_review_cases_v1",
            run_reports=run_reports,
        )
        # First report's tags ["testing", "coverage"] -> "Testing"
        assert report.per_case_topics["case-t"] == "Testing"
