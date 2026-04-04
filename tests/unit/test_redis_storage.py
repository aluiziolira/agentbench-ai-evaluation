"""Tests for Redis storage layer."""

import pytest
import fakeredis.aioredis as aioredis

from agentbench.models.run import RunState
from agentbench.storage.redis_client import RedisStorage


@pytest.fixture
async def fake_redis_client():
    """Create a fake Redis client for testing."""
    client = aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.flushall()
    await client.aclose()


@pytest.fixture
async def storage(fake_redis_client):
    """Create a RedisStorage instance with fake Redis."""
    return RedisStorage(redis_client=fake_redis_client)


class TestRunStateTracking:
    """Test run FSM state transitions."""

    @pytest.mark.asyncio
    async def test_set_and_get_run_state(self, storage):
        """Test setting and retrieving run state."""
        run_id = "test-run-001"

        # Initially no state
        state = await storage.get_run_state(run_id)
        assert state is None

        # Set state
        await storage.set_run_state(run_id, RunState.STARTED)

        # Get state
        state = await storage.get_run_state(run_id)
        assert state == RunState.STARTED

    @pytest.mark.asyncio
    async def test_run_state_transitions(self, storage):
        """Test state transitions through workflow lifecycle."""
        run_id = "test-run-002"

        # PENDING -> STARTED
        await storage.set_run_state(run_id, RunState.PENDING)
        assert await storage.get_run_state(run_id) == RunState.PENDING

        # STARTED -> STEP_IN_PROGRESS
        await storage.set_run_state(run_id, RunState.STARTED)
        assert await storage.get_run_state(run_id) == RunState.STARTED

        # STEP_IN_PROGRESS -> STEP_SCORED
        await storage.set_run_state(run_id, RunState.STEP_IN_PROGRESS)
        assert await storage.get_run_state(run_id) == RunState.STEP_IN_PROGRESS

        # STEP_SCORED -> COMPLETED
        await storage.set_run_state(run_id, RunState.COMPLETED)
        assert await storage.get_run_state(run_id) == RunState.COMPLETED

    @pytest.mark.asyncio
    async def test_all_run_states(self, storage):
        """Test all defined RunState values can be stored and retrieved."""
        for state in RunState:
            run_id = f"test-run-{state.value}"
            await storage.set_run_state(run_id, state)
            retrieved = await storage.get_run_state(run_id)
            assert retrieved == state


class TestStepTracking:
    """Test step tracking methods."""

    @pytest.mark.asyncio
    async def test_set_and_get_current_step(self, storage):
        """Test setting and retrieving current step."""
        run_id = "test-run-steps"

        # Initially no step
        step = await storage.get_current_step(run_id)
        assert step is None

        # Set step
        await storage.set_current_step(run_id, 5)

        # Get step
        step = await storage.get_current_step(run_id)
        assert step == 5

    @pytest.mark.asyncio
    async def test_step_progression(self, storage):
        """Test step index progression."""
        run_id = "test-run-progress"

        # Step 0
        await storage.set_current_step(run_id, 0)
        assert await storage.get_current_step(run_id) == 0

        # Step 1
        await storage.set_current_step(run_id, 1)
        assert await storage.get_current_step(run_id) == 1

        # Step 5
        await storage.set_current_step(run_id, 5)
        assert await storage.get_current_step(run_id) == 5


class TestBenchmarkTracking:
    """Test benchmark run tracking methods."""

    @pytest.mark.asyncio
    async def test_add_run_to_benchmark(self, storage):
        """Test adding runs to benchmark."""
        benchmark_id = "bench-001"
        run_id = "run-001"

        await storage.add_run_to_benchmark(benchmark_id, run_id)

        runs = await storage.get_benchmark_runs(benchmark_id)
        assert run_id in runs

    @pytest.mark.asyncio
    async def test_get_benchmark_runs_multiple(self, storage):
        """Test retrieving multiple runs from benchmark."""
        benchmark_id = "bench-002"
        run_ids = ["run-001", "run-002", "run-003"]

        for run_id in run_ids:
            await storage.add_run_to_benchmark(benchmark_id, run_id)

        runs = await storage.get_benchmark_runs(benchmark_id)
        assert len(runs) == 3
        assert all(r in runs for r in run_ids)

    @pytest.mark.asyncio
    async def test_mark_run_completed(self, storage):
        """Test marking runs as completed."""
        benchmark_id = "bench-003"
        run_id = "run-001"

        await storage.add_run_to_benchmark(benchmark_id, run_id)
        await storage.mark_run_completed(benchmark_id, run_id)

        completed = await storage.get_benchmark_completed_runs(benchmark_id)
        assert run_id in completed

    @pytest.mark.asyncio
    async def test_get_benchmark_completed_runs(self, storage):
        """Test retrieving completed runs."""
        benchmark_id = "bench-004"
        run_ids = ["run-001", "run-002", "run-003"]

        for run_id in run_ids:
            await storage.add_run_to_benchmark(benchmark_id, run_id)

        # Complete only 2 of them
        await storage.mark_run_completed(benchmark_id, "run-001")
        await storage.mark_run_completed(benchmark_id, "run-002")

        completed = await storage.get_benchmark_completed_runs(benchmark_id)
        assert len(completed) == 2
        assert "run-001" in completed
        assert "run-002" in completed
        assert "run-003" not in completed

    @pytest.mark.asyncio
    async def test_is_benchmark_complete_true(self, storage):
        """Test benchmark complete when all runs finished."""
        benchmark_id = "bench-005"
        run_ids = ["run-001", "run-002", "run-003"]

        for run_id in run_ids:
            await storage.add_run_to_benchmark(benchmark_id, run_id)

        # Not complete yet
        assert await storage.is_benchmark_complete(benchmark_id) is False

        # Complete all
        for run_id in run_ids:
            await storage.mark_run_completed(benchmark_id, run_id)

        # Now complete
        assert await storage.is_benchmark_complete(benchmark_id) is True

    @pytest.mark.asyncio
    async def test_is_benchmark_complete_no_runs(self, storage):
        """Test benchmark not complete when no runs."""
        benchmark_id = "bench-empty"

        # No runs added
        assert await storage.is_benchmark_complete(benchmark_id) is False


class TestWorkflowCaching:
    """Test workflow caching methods."""

    @pytest.mark.asyncio
    async def test_cache_and_get_workflow(self, storage):
        """Test caching and retrieving workflow data."""
        workflow_id = "wf-001"
        version = "1.0.0"
        workflow_data = {"name": "Test Workflow", "steps": "[step1, step2]", "timeout": "300"}

        await storage.cache_workflow(workflow_id, version, workflow_data)

        cached = await storage.get_cached_workflow(workflow_id, version)
        assert cached is not None
        assert cached["name"] == "Test Workflow"
        assert cached["steps"] == "[step1, step2]"
        assert cached["timeout"] == "300"

    @pytest.mark.asyncio
    async def test_get_cached_workflow_missing(self, storage):
        """Test retrieving non-existent workflow returns None."""
        cached = await storage.get_cached_workflow("nonexistent", "1.0")
        assert cached is None


class TestTTLConfiguration:
    """Test TTL configuration for different key types."""

    @pytest.mark.asyncio
    async def test_run_state_default_ttl(self, storage, fake_redis_client):
        """Test default 1 hour TTL for run state."""
        run_id = "test-ttl-run"

        await storage.set_run_state(run_id, RunState.STARTED)

        ttl = await fake_redis_client.ttl(f"run:{run_id}:state")
        # TTL should be close to 3600 (1 hour)
        assert 3500 < ttl <= 3600

    @pytest.mark.asyncio
    async def test_run_state_custom_ttl(self, storage, fake_redis_client):
        """Test custom TTL for run state."""
        run_id = "test-ttl-custom"

        await storage.set_run_state(run_id, RunState.STARTED, ttl=1800)

        ttl = await fake_redis_client.ttl(f"run:{run_id}:state")
        # TTL should be close to 1800 (30 min)
        assert 1700 < ttl <= 1800

    @pytest.mark.asyncio
    async def test_benchmark_runs_default_ttl(self, storage, fake_redis_client):
        """Test default 2 hour TTL for benchmark runs."""
        benchmark_id = "test-ttl-bench"

        await storage.add_run_to_benchmark(benchmark_id, "run-001")

        ttl = await fake_redis_client.ttl(f"benchmark:{benchmark_id}:runs")
        # TTL should be close to 7200 (2 hours)
        assert 7100 < ttl <= 7200

    @pytest.mark.asyncio
    async def test_workflow_default_ttl(self, storage, fake_redis_client):
        """Test default 24 hour TTL for workflow cache."""
        workflow_id = "test-ttl-wf"
        version = "1.0"

        await storage.cache_workflow(workflow_id, version, {"data": "value"})

        ttl = await fake_redis_client.ttl(f"workflow:{workflow_id}:{version}")
        # TTL should be close to 86400 (24 hours)
        assert 86300 < ttl <= 86400


class TestRedisStorageInitialization:
    """Test RedisStorage initialization."""

    @pytest.mark.asyncio
    async def test_init_with_provided_client(self, fake_redis_client):
        """Test initialization with provided client."""
        storage = RedisStorage(redis_client=fake_redis_client)
        client = await storage._get_client()
        assert client is fake_redis_client

    def test_init_without_client(self):
        """Test initialization without client stores URL."""
        storage = RedisStorage(redis_url="redis://custom:6380")
        assert storage._client is None
        assert storage._redis_url == "redis://custom:6380"
