"""Unit tests for MongoDB storage layer.

Tests cover workflow CRUD, immutability enforcement, run state updates,
and report persistence with mocked MongoDB using mongomock.
"""

import uuid
from datetime import UTC, datetime

import pytest
from pymongo.errors import DuplicateKeyError

from agentbench.models import (
    AgentSummary,
    BenchmarkReport,
    EvaluationRun,
    RunReport,
    RunState,
    ScoringConfig,
    StepDefinition,
    StepScore,
    WorkflowDefinition,
)
from agentbench.storage import (
    ImmutableWorkflowError,
    MongoStorage,
    RunNotFoundError,
    WorkflowNotFoundError,
)

# Import mongomock_motor if available, otherwise skip tests
try:
    from mongomock_motor import AsyncMongoMockClient

    HAVE_MONGOMOCK = True
except ImportError:
    HAVE_MONGOMOCK = False


pytestmark = pytest.mark.asyncio


def generate_uuid() -> str:
    """Generate a UUID4 string."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """Get current UTC time as ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def create_test_workflow(
    workflow_id: str = "wf_test",
    version: str = "1.0.0",
    status: str = "draft",
) -> WorkflowDefinition:
    """Create a test workflow definition."""
    scoring = ScoringConfig(strategy="finding_match", weight=2.0)
    return WorkflowDefinition(
        workflow_id=workflow_id,
        version=version,
        status=status,  # type: ignore[arg-type]
        description="Test workflow",
        steps=[
            StepDefinition(
                step_id="s1_findings",
                order=0,
                input="Find issues in: {diff_patch}",
                scoring=scoring,
            ),
        ],
        created_at=now_iso(),
        published_at=now_iso() if status == "published" else None,
    )


def create_test_run(
    run_id: str | None = None,
    benchmark_id: str | None = None,
    state: RunState = RunState.PENDING,
    current_step: int = 0,
) -> EvaluationRun:
    """Create a test evaluation run."""
    return EvaluationRun(
        run_id=run_id or generate_uuid(),
        benchmark_id=benchmark_id or generate_uuid(),
        workflow_id="wf_pr_review_v1",
        workflow_version="1.0.0",
        case_set_id="pr_review_cases_v1",
        case_id="pr_001",
        agent_id="gpt-4o-mini",
        agent_config={"temperature": 0},
        state=state,
        current_step=current_step,
        created_at=now_iso(),
    )


def create_test_run_report(run_id: str | None = None) -> RunReport:
    """Create a test run report."""
    run_id = run_id or generate_uuid()
    benchmark_id = generate_uuid()

    return RunReport(
        run_id=run_id,
        benchmark_id=benchmark_id,
        case_id="pr_001",
        case_tags=["auth", "api"],
        agent_id="gpt-4o-mini",
        workflow_id="wf_pr_review_v1",
        total_score=0.85,
        step_scores=[
            StepScore(
                run_id=run_id,
                case_id="pr_001",
                step_id="s1_findings",
                strategy="finding_match",
                raw_score=0.9,
                weighted_score=1.8,
                latency_ms=1200,
                passed=True,
            ),
        ],
        total_latency_ms=1200,
        completed_at=now_iso(),
    )


def create_test_benchmark_report() -> BenchmarkReport:
    """Create a test benchmark report."""
    return BenchmarkReport(
        benchmark_id=generate_uuid(),
        workflow_id="wf_pr_review_v1",
        case_set_id="pr_review_cases_v1",
        created_at=now_iso(),
        case_count=2,
        agents=[
            AgentSummary(
                agent_id="gpt-4o-mini",
                avg_score=0.85,
                p50_latency_ms=1500,
                p95_latency_ms=3500,
                failure_rate=0.0,
                step_breakdown={"s1_findings": 0.9},
            ),
        ],
        per_case_scores={"pr_001": {"gpt-4o-mini": 0.9}},
    )


@pytest.fixture
async def storage():
    """Create a MongoStorage instance with mocked MongoDB."""
    if not HAVE_MONGOMOCK:
        pytest.skip("mongomock-motor not installed")

    client = AsyncMongoMockClient()
    storage = MongoStorage.__new__(MongoStorage)
    storage.client = client
    storage.db = client["agentbench_test"]

    # Setup indexes
    await storage.setup_indexes()

    yield storage

    # Cleanup
    await client.drop_database("agentbench_test")
    client.close()


class TestWorkflowCRUD:
    """Tests for workflow CRUD operations."""

    async def test_create_workflow(self, storage: MongoStorage) -> None:
        """Test creating a workflow."""
        workflow = create_test_workflow()
        await storage.create_workflow(workflow)

        # Verify it was created
        retrieved = await storage.get_workflow("wf_test", "1.0.0")
        assert retrieved is not None
        assert retrieved.workflow_id == "wf_test"
        assert retrieved.version == "1.0.0"
        assert retrieved.status == "draft"

    async def test_get_workflow_by_id_and_version(self, storage: MongoStorage) -> None:
        """Test retrieving a specific workflow version."""
        workflow1 = create_test_workflow("wf_test", "1.0.0")
        workflow2 = create_test_workflow("wf_test", "2.0.0")

        await storage.create_workflow(workflow1)
        await storage.create_workflow(workflow2)

        retrieved = await storage.get_workflow("wf_test", "1.0.0")
        assert retrieved is not None
        assert retrieved.version == "1.0.0"

    async def test_get_workflow_latest_published(self, storage: MongoStorage) -> None:
        """Test retrieving latest published workflow."""
        draft = create_test_workflow("wf_test", "1.0.0", "draft")
        published = create_test_workflow("wf_test", "2.0.0", "published")

        await storage.create_workflow(draft)
        await storage.create_workflow(published)

        # Without version, should return latest published
        retrieved = await storage.get_workflow("wf_test")
        assert retrieved is not None
        assert retrieved.version == "2.0.0"
        assert retrieved.status == "published"

    async def test_get_workflow_not_found(self, storage: MongoStorage) -> None:
        """Test retrieving non-existent workflow returns None."""
        result = await storage.get_workflow("nonexistent", "1.0.0")
        assert result is None

    async def test_list_workflows(self, storage: MongoStorage) -> None:
        """Test listing all workflows."""
        workflow1 = create_test_workflow("wf_test1", "1.0.0")
        workflow2 = create_test_workflow("wf_test2", "1.0.0")

        await storage.create_workflow(workflow1)
        await storage.create_workflow(workflow2)

        workflows = await storage.list_workflows()
        assert len(workflows) == 2
        ids = {w.workflow_id for w in workflows}
        assert "wf_test1" in ids
        assert "wf_test2" in ids

    async def test_create_duplicate_workflow_raises(self, storage: MongoStorage) -> None:
        """Test creating duplicate workflow raises DuplicateKeyError."""
        workflow = create_test_workflow("wf_test", "1.0.0")
        await storage.create_workflow(workflow)

        with pytest.raises(DuplicateKeyError):
            await storage.create_workflow(workflow)


class TestWorkflowImmutability:
    """Tests for published workflow immutability."""

    async def test_check_workflow_mutable_draft(self, storage: MongoStorage) -> None:
        """Test that draft workflows are mutable."""
        workflow = create_test_workflow("wf_test", "1.0.0", "draft")
        await storage.create_workflow(workflow)

        is_mutable = await storage._check_workflow_mutable("wf_test", "1.0.0")
        assert is_mutable is True

    async def test_check_workflow_mutable_published(self, storage: MongoStorage) -> None:
        """Test that published workflows are not mutable."""
        workflow = create_test_workflow("wf_test", "1.0.0", "published")
        await storage.create_workflow(workflow)

        is_mutable = await storage._check_workflow_mutable("wf_test", "1.0.0")
        assert is_mutable is False

    async def test_enforce_immutability_raises_for_published(self, storage: MongoStorage) -> None:
        """Test enforcing immutability raises for published workflows."""
        workflow = create_test_workflow("wf_test", "1.0.0", "published")
        await storage.create_workflow(workflow)

        with pytest.raises(ImmutableWorkflowError):
            await storage._enforce_immutability("wf_test", "1.0.0")

    async def test_publish_workflow(self, storage: MongoStorage) -> None:
        """Test publishing a workflow."""
        workflow = create_test_workflow("wf_test", "1.0.0", "draft")
        await storage.create_workflow(workflow)

        await storage.publish_workflow("wf_test", "1.0.0")

        # Verify it's now published
        retrieved = await storage.get_workflow("wf_test", "1.0.0")
        assert retrieved is not None
        assert retrieved.status == "published"
        assert retrieved.published_at is not None

    async def test_publish_already_published_workflow(self, storage: MongoStorage) -> None:
        """Test publishing an already published workflow is idempotent."""
        workflow = create_test_workflow("wf_test", "1.0.0", "published")
        await storage.create_workflow(workflow)

        # Should not raise
        await storage.publish_workflow("wf_test", "1.0.0")

    async def test_publish_nonexistent_workflow_raises(self, storage: MongoStorage) -> None:
        """Test publishing non-existent workflow raises error."""
        with pytest.raises(WorkflowNotFoundError):
            await storage.publish_workflow("nonexistent", "1.0.0")


class TestRunCRUD:
    """Tests for run CRUD operations."""

    async def test_create_run(self, storage: MongoStorage) -> None:
        """Test creating a run."""
        run = create_test_run()
        await storage.create_run(run)

        # Verify it was created
        retrieved = await storage.get_run(run.run_id)
        assert retrieved is not None
        assert retrieved.run_id == run.run_id
        assert retrieved.state == RunState.PENDING

    async def test_get_run_not_found(self, storage: MongoStorage) -> None:
        """Test retrieving non-existent run returns None."""
        result = await storage.get_run("nonexistent")
        assert result is None

    async def test_create_duplicate_run_raises(self, storage: MongoStorage) -> None:
        """Test creating duplicate run raises DuplicateKeyError."""
        run = create_test_run()
        await storage.create_run(run)

        with pytest.raises(DuplicateKeyError):
            await storage.create_run(run)

    async def test_update_run_state(self, storage: MongoStorage) -> None:
        """Test updating run state."""
        run = create_test_run(state=RunState.PENDING)
        await storage.create_run(run)

        await storage.update_run_state(run.run_id, RunState.STARTED, current_step=0)

        retrieved = await storage.get_run(run.run_id)
        assert retrieved is not None
        assert retrieved.state == RunState.STARTED
        assert retrieved.current_step == 0

    async def test_update_run_state_with_completion(self, storage: MongoStorage) -> None:
        """Test updating run state to completed sets completed_at."""
        run = create_test_run(state=RunState.STARTED)
        await storage.create_run(run)

        await storage.update_run_state(run.run_id, RunState.COMPLETED, current_step=1)

        retrieved = await storage.get_run(run.run_id)
        assert retrieved is not None
        assert retrieved.state == RunState.COMPLETED
        assert retrieved.completed_at is not None

    async def test_update_nonexistent_run_raises(self, storage: MongoStorage) -> None:
        """Test updating non-existent run raises error."""
        with pytest.raises(RunNotFoundError):
            await storage.update_run_state("nonexistent", RunState.STARTED)

    async def test_list_runs(self, storage: MongoStorage) -> None:
        """Test listing all runs."""
        run1 = create_test_run()
        run2 = create_test_run()

        await storage.create_run(run1)
        await storage.create_run(run2)

        runs = await storage.list_runs()
        assert len(runs) == 2

    async def test_list_runs_by_benchmark(self, storage: MongoStorage) -> None:
        """Test filtering runs by benchmark_id."""
        benchmark_id = generate_uuid()
        run1 = create_test_run(benchmark_id=benchmark_id)
        run2 = create_test_run(benchmark_id=generate_uuid())

        await storage.create_run(run1)
        await storage.create_run(run2)

        runs = await storage.list_runs(benchmark_id=benchmark_id)
        assert len(runs) == 1
        assert runs[0].benchmark_id == benchmark_id

    async def test_list_runs_by_case_set(self, storage: MongoStorage) -> None:
        """Test filtering runs by case_set_id."""
        # Create runs with different case_set_id
        run1 = create_test_run()
        run2 = create_test_run()
        run2.case_set_id = "other_case_set"

        await storage.create_run(run1)
        await storage.create_run(run2)

        runs = await storage.list_runs(case_set_id="pr_review_cases_v1")
        assert len(runs) == 1


class TestRunReportCRUD:
    """Tests for run report CRUD operations."""

    async def test_create_run_report(self, storage: MongoStorage) -> None:
        """Test creating a run report."""
        report = create_test_run_report()
        await storage.create_run_report(report)

        # Verify it was created
        retrieved = await storage.get_run_report(report.run_id)
        assert retrieved is not None
        assert retrieved.run_id == report.run_id
        assert retrieved.total_score == 0.85

    async def test_get_run_report_not_found(self, storage: MongoStorage) -> None:
        """Test retrieving non-existent run report returns None."""
        result = await storage.get_run_report("nonexistent")
        assert result is None

    async def test_create_duplicate_run_report_raises(self, storage: MongoStorage) -> None:
        """Test creating duplicate run report raises DuplicateKeyError."""
        report = create_test_run_report()
        await storage.create_run_report(report)

        with pytest.raises(DuplicateKeyError):
            await storage.create_run_report(report)


class TestBenchmarkReportCRUD:
    """Tests for benchmark report CRUD operations."""

    async def test_create_benchmark_report(self, storage: MongoStorage) -> None:
        """Test creating a benchmark report."""
        report = create_test_benchmark_report()
        await storage.create_benchmark_report(report)

        # Verify it was created
        retrieved = await storage.get_benchmark_report(report.benchmark_id)
        assert retrieved is not None
        assert retrieved.benchmark_id == report.benchmark_id
        assert retrieved.case_count == 2
        assert len(retrieved.agents) == 1

    async def test_get_benchmark_report_not_found(self, storage: MongoStorage) -> None:
        """Test retrieving non-existent benchmark report returns None."""
        result = await storage.get_benchmark_report("nonexistent")
        assert result is None

    async def test_create_duplicate_benchmark_report_raises(self, storage: MongoStorage) -> None:
        """Test creating duplicate benchmark report raises DuplicateKeyError."""
        report = create_test_benchmark_report()
        await storage.create_benchmark_report(report)

        with pytest.raises(DuplicateKeyError):
            await storage.create_benchmark_report(report)


class TestStorageIndexes:
    """Tests for index creation and constraints."""

    async def test_workflow_unique_index(self, storage: MongoStorage) -> None:
        """Test that workflows have unique index on (workflow_id, version)."""
        workflow1 = create_test_workflow("wf_test", "1.0.0")
        workflow2 = create_test_workflow("wf_test", "1.0.0")  # Same ID and version

        await storage.create_workflow(workflow1)

        with pytest.raises(DuplicateKeyError):
            await storage.create_workflow(workflow2)

    async def test_run_unique_index(self, storage: MongoStorage) -> None:
        """Test that runs have unique index on run_id."""
        run_id = generate_uuid()
        run1 = create_test_run(run_id=run_id)
        run2 = create_test_run(run_id=run_id)  # Same run_id

        await storage.create_run(run1)

        with pytest.raises(DuplicateKeyError):
            await storage.create_run(run2)

    async def test_run_report_unique_index(self, storage: MongoStorage) -> None:
        """Test that run reports have unique index on run_id."""
        run_id = generate_uuid()
        report1 = create_test_run_report(run_id=run_id)
        report2 = create_test_run_report(run_id=run_id)  # Same run_id

        await storage.create_run_report(report1)

        with pytest.raises(DuplicateKeyError):
            await storage.create_run_report(report2)

    async def test_benchmark_report_unique_index(self, storage: MongoStorage) -> None:
        """Test that benchmark reports have unique index on benchmark_id."""
        benchmark_id = generate_uuid()
        report1 = create_test_benchmark_report()
        report1.benchmark_id = benchmark_id
        report2 = create_test_benchmark_report()
        report2.benchmark_id = benchmark_id  # Same benchmark_id

        await storage.create_benchmark_report(report1)

        with pytest.raises(DuplicateKeyError):
            await storage.create_benchmark_report(report2)
