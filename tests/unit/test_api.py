"""Unit tests for the AgentBench API.

Tests cover:
- Health endpoint
- Create benchmark
- Get benchmark (in progress and complete)
- List benchmark runs
- Workflow registration
- Get workflow
- Publish workflow
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agentbench.api.app import app
from agentbench.models import (
    AgentSummary,
    BenchmarkReport,
    RunState,
    ScoringConfig,
    StepDefinition,
    WorkflowDefinition,
)
from agentbench.models.run import EvaluationRun


@pytest.fixture
def mock_mongo_storage():
    """Create a mock MongoStorage."""
    storage = MagicMock()
    storage.setup_indexes = AsyncMock()
    storage.get_workflow = AsyncMock()
    storage.create_workflow = AsyncMock()
    storage.publish_workflow = AsyncMock()
    storage.get_benchmark_report = AsyncMock()
    storage.list_runs = AsyncMock()
    return storage


@pytest.fixture
def mock_redis_storage():
    """Create a mock RedisStorage."""
    storage = MagicMock()
    storage.is_benchmark_complete = AsyncMock(return_value=False)
    storage._client = MagicMock()
    return storage


@pytest.fixture
def mock_event_bus():
    """Create a mock EventBus."""
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def test_client(mock_mongo_storage, mock_redis_storage, mock_event_bus):
    """Create a test client with mocked dependencies."""
    # Patch the lifespan to inject mock dependencies
    with (
        patch("agentbench.api.app.MongoStorage") as mock_mongo_cls,
        patch("agentbench.api.app.RedisStorage") as mock_redis_cls,
        patch("agentbench.api.app.EventBus") as mock_bus_cls,
    ):
        mock_mongo_cls.return_value = mock_mongo_storage
        mock_redis_cls.return_value = mock_redis_storage
        mock_bus_cls.return_value = mock_event_bus

        client = TestClient(app)
        # Manually set the state on app.state
        app.state.mongo = mock_mongo_storage
        app.state.redis = mock_redis_storage
        app.state.event_bus = mock_event_bus
        yield client


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_check(self, test_client):
        """Test that health endpoint returns healthy status."""
        response = test_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestCreateBenchmark:
    """Tests for creating benchmarks."""

    def test_create_benchmark_success(self, test_client, mock_mongo_storage, mock_event_bus):
        """Test successful benchmark creation."""
        # Arrange - Setup workflow to exist
        workflow = WorkflowDefinition(
            workflow_id="wf_pr_review_v1",
            version="1.0.0",
            status="published",
            description="Test workflow",
            steps=[
                StepDefinition(
                    step_id="s1_findings",
                    order=0,
                    input="Test input",
                    timeout_ms=15000,
                    scoring=ScoringConfig(strategy="finding_match"),
                )
            ],
            created_at=datetime.now(UTC).isoformat(),
        )
        mock_mongo_storage.get_workflow.return_value = workflow

        # Act
        response = test_client.post(
            "/benchmarks",
            json={
                "workflow_id": "wf_pr_review_v1",
                "case_set_id": "pr_review_cases_v1",
                "agents": ["gpt-4o-mini", "claude-haiku-4-5"],
            },
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert "benchmark_id" in data
        assert data["status"] == "started"

        # Verify event was published
        mock_event_bus.publish.assert_called_once()
        call_args = mock_event_bus.publish.call_args
        assert call_args[0][0] == "stream:eval-runs"

        event = call_args[0][1]
        assert event.event_type == "evaluation.run.requested"
        assert event.payload["benchmark_id"] == data["benchmark_id"]
        assert event.payload["workflow_id"] == "wf_pr_review_v1"
        assert event.payload["case_set_id"] == "pr_review_cases_v1"
        assert event.payload["agents"] == ["gpt-4o-mini", "claude-haiku-4-5"]

    def test_create_benchmark_workflow_not_found(self, test_client, mock_mongo_storage):
        """Test benchmark creation with non-existent workflow."""
        # Arrange
        mock_mongo_storage.get_workflow.return_value = None

        # Act
        response = test_client.post(
            "/benchmarks",
            json={
                "workflow_id": "wf_nonexistent",
                "case_set_id": "pr_review_cases_v1",
                "agents": ["gpt-4o-mini"],
            },
        )

        # Assert
        assert response.status_code == 404
        assert "Workflow not found" in response.json()["detail"]


class TestGetBenchmark:
    """Tests for getting benchmark reports."""

    def test_get_benchmark_in_progress(self, test_client, mock_redis_storage):
        """Test getting benchmark that is still in progress."""
        # Arrange
        mock_redis_storage.is_benchmark_complete.return_value = False

        # Act
        response = test_client.get("/benchmarks/bench-123")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["benchmark_id"] == "bench-123"
        assert data["status"] == "in_progress"

    def test_get_benchmark_complete(self, test_client, mock_redis_storage, mock_mongo_storage):
        """Test getting complete benchmark report."""
        # Arrange
        mock_redis_storage.is_benchmark_complete.return_value = True

        report = BenchmarkReport(
            benchmark_id="bench-123",
            workflow_id="wf_pr_review_v1",
            case_set_id="pr_review_cases_v1",
            created_at=datetime.now(UTC).isoformat(),
            case_count=2,
            agents=[
                AgentSummary(
                    agent_id="gpt-4o-mini",
                    avg_score=0.85,
                    p50_latency_ms=500,
                    p95_latency_ms=800,
                    failure_rate=0.0,
                    step_breakdown={"s1_findings": 0.9},
                )
            ],
            per_case_scores={"case-1": {"gpt-4o-mini": 0.85}},
            per_case_topics={"case-1": "Auth/Security"},
        )
        mock_mongo_storage.get_benchmark_report.return_value = report

        # Act
        response = test_client.get("/benchmarks/bench-123")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["benchmark_id"] == "bench-123"
        assert data["case_count"] == 2
        assert len(data["agents"]) == 1
        assert data["per_case_topics"] == {"case-1": "Auth/Security"}

    def test_get_benchmark_not_found(self, test_client, mock_redis_storage, mock_mongo_storage):
        """Test getting non-existent benchmark."""
        # Arrange
        mock_redis_storage.is_benchmark_complete.return_value = True
        mock_mongo_storage.get_benchmark_report.return_value = None

        # Act
        response = test_client.get("/benchmarks/nonexistent")

        # Assert
        assert response.status_code == 404
        assert "Benchmark not found" in response.json()["detail"]


class TestListBenchmarkRuns:
    """Tests for listing benchmark runs."""

    def test_list_runs(self, test_client, mock_mongo_storage):
        """Test listing runs for a benchmark."""
        # Arrange
        runs = [
            EvaluationRun(
                run_id="run-1",
                benchmark_id="bench-123",
                workflow_id="wf_pr_review_v1",
                workflow_version="1.0.0",
                case_set_id="pr_review_cases_v1",
                case_id="case-1",
                agent_id="gpt-4o-mini",
                agent_config={},
                state=RunState.COMPLETED,
                current_step=1,
                created_at=datetime.now(UTC).isoformat(),
            ),
            EvaluationRun(
                run_id="run-2",
                benchmark_id="bench-123",
                workflow_id="wf_pr_review_v1",
                workflow_version="1.0.0",
                case_set_id="pr_review_cases_v1",
                case_id="case-2",
                agent_id="claude-haiku-4-5",
                agent_config={},
                state=RunState.STARTED,
                current_step=0,
                created_at=datetime.now(UTC).isoformat(),
            ),
        ]
        mock_mongo_storage.list_runs.return_value = runs

        # Act
        response = test_client.get("/benchmarks/bench-123/runs")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["run_id"] == "run-1"
        assert data[0]["agent_id"] == "gpt-4o-mini"
        assert data[0]["state"] == "COMPLETED"
        assert data[1]["run_id"] == "run-2"
        assert data[1]["state"] == "STARTED"


class TestRegisterWorkflow:
    """Tests for workflow registration."""

    def test_register_workflow_success(self, test_client, mock_mongo_storage):
        """Test successful workflow registration."""
        # Arrange
        mock_mongo_storage.create_workflow.return_value = None

        workflow_data = {
            "workflow_id": "wf_test_v1",
            "version": "1.0.0",
            "status": "draft",
            "description": "Test workflow",
            "steps": [
                {
                    "step_id": "s1_findings",
                    "order": 0,
                    "input": "Test prompt",
                    "timeout_ms": 15000,
                    "scoring": {"strategy": "finding_match", "weight": 2.0},
                }
            ],
            "created_at": datetime.now(UTC).isoformat(),
        }

        # Act
        response = test_client.post("/workflows", json=workflow_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["workflow_id"] == "wf_test_v1"
        assert data["version"] == "1.0.0"

    def test_register_workflow_duplicate(self, test_client, mock_mongo_storage):
        """Test workflow registration with duplicate key."""
        # Arrange
        from pymongo.errors import DuplicateKeyError

        mock_mongo_storage.create_workflow.side_effect = DuplicateKeyError("Duplicate key")

        workflow_data = {
            "workflow_id": "wf_test_v1",
            "version": "1.0.0",
            "status": "draft",
            "description": "Test workflow",
            "steps": [],
            "created_at": datetime.now(UTC).isoformat(),
        }

        # Act
        response = test_client.post("/workflows", json=workflow_data)

        # Assert
        assert response.status_code == 400


class TestGetWorkflow:
    """Tests for getting workflows."""

    def test_get_workflow_success(self, test_client, mock_mongo_storage):
        """Test successful workflow retrieval."""
        # Arrange
        workflow = WorkflowDefinition(
            workflow_id="wf_pr_review_v1",
            version="1.0.0",
            status="published",
            description="PR Review Workflow",
            steps=[
                StepDefinition(
                    step_id="s1_findings",
                    order=0,
                    input="Test input",
                    timeout_ms=15000,
                    scoring=ScoringConfig(strategy="finding_match"),
                )
            ],
            created_at=datetime.now(UTC).isoformat(),
            published_at=datetime.now(UTC).isoformat(),
        )
        mock_mongo_storage.get_workflow.return_value = workflow

        # Act
        response = test_client.get("/workflows/wf_pr_review_v1")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["workflow_id"] == "wf_pr_review_v1"
        assert data["version"] == "1.0.0"
        assert data["status"] == "published"

    def test_get_workflow_not_found(self, test_client, mock_mongo_storage):
        """Test getting non-existent workflow."""
        # Arrange
        mock_mongo_storage.get_workflow.return_value = None

        # Act
        response = test_client.get("/workflows/nonexistent")

        # Assert
        assert response.status_code == 404
        assert "Workflow not found" in response.json()["detail"]


class TestPublishWorkflow:
    """Tests for publishing workflows."""

    def test_publish_workflow_success(self, test_client, mock_mongo_storage):
        """Test successful workflow publishing."""
        # Arrange
        mock_mongo_storage.publish_workflow.return_value = None

        # Act
        response = test_client.post("/workflows/wf_test_v1/publish?version=1.0.0")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["workflow_id"] == "wf_test_v1"
        assert data["version"] == "1.0.0"
        assert data["status"] == "published"

    def test_publish_workflow_not_found(self, test_client, mock_mongo_storage):
        """Test publishing non-existent workflow."""
        # Arrange
        from agentbench.storage.mongo import WorkflowNotFoundError

        mock_mongo_storage.publish_workflow.side_effect = WorkflowNotFoundError("Not found")

        # Act
        response = test_client.post("/workflows/nonexistent/publish?version=1.0.0")

        # Assert
        assert response.status_code == 400
