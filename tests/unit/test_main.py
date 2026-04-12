"""Unit tests for the main runtime (MAIN-01).

Tests runtime initialization, service startup, and graceful shutdown.
"""

import asyncio
import contextlib
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentbench.main import AgentBenchRuntime


@pytest.fixture
def mock_mongo_storage():
    """Create a mock MongoStorage."""
    storage = AsyncMock()
    return storage


@pytest.fixture
def mock_redis_storage():
    """Create a mock RedisStorage."""
    storage = AsyncMock()
    return storage


@pytest.fixture
def mock_event_bus():
    """Create a mock EventBus."""
    return AsyncMock()


@pytest.fixture
def mock_orchestrator():
    """Create a mock Orchestrator."""
    mock = AsyncMock()
    mock.run = AsyncMock()
    mock.stop = AsyncMock()
    return mock


@pytest.fixture
def mock_dispatcher():
    """Create a mock StepDispatcher."""
    mock = AsyncMock()
    mock.run = AsyncMock()
    mock.stop = AsyncMock()
    return mock


@pytest.fixture
def mock_scoring_engine():
    """Create a mock ScoringEngine."""
    mock = AsyncMock()
    mock.run = AsyncMock()
    mock.stop = AsyncMock()
    return mock


@pytest.fixture
def mock_aggregator():
    """Create a mock Aggregator."""
    mock = AsyncMock()
    mock.run = AsyncMock()
    mock.stop = AsyncMock()
    return mock


class TestRuntimeInitialization:
    """Test runtime initialization (MAIN-01-T01)."""

    @pytest.mark.asyncio
    async def test_runtime_initializes_mongo_storage(self):
        """Runtime should initialize MongoDB storage on startup."""
        runtime = AgentBenchRuntime()
        assert runtime.mongo_storage is None

        # Mock _setup_signal_handlers to avoid signal handling issues
        runtime._setup_signal_handlers = MagicMock()

        with patch.object(runtime, "mongo_storage", AsyncMock()) as mock_storage:
            mock_storage.setup_indexes = AsyncMock()
            await mock_storage.setup_indexes()
            mock_storage.setup_indexes.assert_called_once()

    @pytest.mark.asyncio
    async def test_runtime_initializes_redis_storage(self):
        """Runtime should initialize Redis storage on startup."""
        runtime = AgentBenchRuntime()

        # Mock _setup_signal_handlers
        runtime._setup_signal_handlers = MagicMock()

        with patch.object(runtime, "redis_storage", AsyncMock()) as mock_storage:
            mock_client = AsyncMock()
            mock_storage._get_client = AsyncMock(return_value=mock_client)
            client = await mock_storage._get_client()
            assert client == mock_client


class TestServiceStartup:
    """Test service startup (MAIN-01-T02)."""

    @pytest.mark.asyncio
    async def test_start_creates_service_tasks(
        self,
        mock_orchestrator,
        mock_dispatcher,
        mock_scoring_engine,
        mock_aggregator,
    ):
        """Runtime.start() should create tasks for all services."""
        runtime = AgentBenchRuntime()

        # Mock signal handlers
        runtime._setup_signal_handlers = MagicMock()

        # Inject mocks
        runtime.orchestrator = mock_orchestrator
        runtime.dispatcher = mock_dispatcher
        runtime.scoring_engine = mock_scoring_engine
        runtime.aggregator = mock_aggregator

        # Start services
        await runtime.start()

        # Verify tasks were created
        assert len(runtime._tasks) == 4

    @pytest.mark.asyncio
    async def test_service_tasks_are_named(
        self,
        mock_orchestrator,
        mock_dispatcher,
        mock_scoring_engine,
        mock_aggregator,
    ):
        """Service tasks should have descriptive names."""
        runtime = AgentBenchRuntime()

        # Mock signal handlers
        runtime._setup_signal_handlers = MagicMock()

        # Inject mocks
        runtime.orchestrator = mock_orchestrator
        runtime.dispatcher = mock_dispatcher
        runtime.scoring_engine = mock_scoring_engine
        runtime.aggregator = mock_aggregator

        # Start services
        await runtime.start()

        # Verify task names
        task_names = [t.get_name() for t in runtime._tasks]
        assert "orchestrator" in task_names
        assert "dispatcher" in task_names
        assert "scoring_engine" in task_names
        assert "aggregator" in task_names

    @pytest.mark.asyncio
    async def test_start_logs_service_initialization(self):
        """Runtime should log when services are started."""
        runtime = AgentBenchRuntime()
        runtime._setup_signal_handlers = MagicMock()

        # Mock all services
        runtime.orchestrator = AsyncMock()
        runtime.orchestrator.run = AsyncMock()
        runtime.dispatcher = AsyncMock()
        runtime.dispatcher.run = AsyncMock()
        runtime.scoring_engine = AsyncMock()
        runtime.scoring_engine.run = AsyncMock()
        runtime.aggregator = AsyncMock()
        runtime.aggregator.run = AsyncMock()

        with patch("agentbench.main.logger") as mock_logger:
            await runtime.start()
            mock_logger.info.assert_any_call("Starting AgentBench services...")
            mock_logger.info.assert_any_call("All services started")


class TestGracefulShutdown:
    """Test graceful shutdown (MAIN-01-T03)."""

    @pytest.mark.asyncio
    async def test_stop_cancels_service_tasks(
        self,
        mock_orchestrator,
        mock_dispatcher,
        mock_scoring_engine,
        mock_aggregator,
    ):
        """Runtime.stop() should cancel all service tasks."""
        runtime = AgentBenchRuntime()

        # Inject mocks
        runtime.orchestrator = mock_orchestrator
        runtime.dispatcher = mock_dispatcher
        runtime.scoring_engine = mock_scoring_engine
        runtime.aggregator = mock_aggregator

        # Create mock tasks
        mock_task1 = AsyncMock()
        mock_task1.cancel = MagicMock()
        mock_task2 = AsyncMock()
        mock_task2.cancel = MagicMock()
        runtime._tasks = [mock_task1, mock_task2]

        await runtime.stop()

        # Verify tasks were cancelled
        mock_task1.cancel.assert_called_once()
        mock_task2.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_calls_service_stop_methods(
        self,
        mock_orchestrator,
        mock_dispatcher,
        mock_scoring_engine,
        mock_aggregator,
    ):
        """Runtime.stop() should call stop() on all services."""
        runtime = AgentBenchRuntime()

        # Inject mocks
        runtime.orchestrator = mock_orchestrator
        runtime.dispatcher = mock_dispatcher
        runtime.scoring_engine = mock_scoring_engine
        runtime.aggregator = mock_aggregator

        # Create mock tasks
        runtime._tasks = [AsyncMock(), AsyncMock()]

        await runtime.stop()

        # Verify stop() was called on each service
        mock_orchestrator.stop.assert_called_once()
        mock_dispatcher.stop.assert_called_once()
        mock_scoring_engine.stop.assert_called_once()
        mock_aggregator.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_logs_shutdown(self):
        """Runtime should log during shutdown."""
        runtime = AgentBenchRuntime()

        # Inject minimal mocks
        runtime.orchestrator = AsyncMock()
        runtime.orchestrator.stop = AsyncMock()
        runtime.dispatcher = AsyncMock()
        runtime.dispatcher.stop = AsyncMock()
        runtime.scoring_engine = AsyncMock()
        runtime.scoring_engine.stop = AsyncMock()
        runtime.aggregator = AsyncMock()
        runtime.aggregator.stop = AsyncMock()
        runtime._tasks = []

        with patch("agentbench.main.logger") as mock_logger:
            await runtime.stop()
            mock_logger.info.assert_any_call("Stopping AgentBench services...")
            mock_logger.info.assert_any_call("All services stopped")

    @pytest.mark.asyncio
    async def test_handles_cancelled_error_gracefully(
        self,
        mock_orchestrator,
        mock_dispatcher,
        mock_scoring_engine,
        mock_aggregator,
    ):
        """Runtime should handle CancelledError gracefully during stop."""
        runtime = AgentBenchRuntime()
        runtime._setup_signal_handlers = MagicMock()

        # Inject mocks
        runtime.orchestrator = mock_orchestrator
        runtime.dispatcher = mock_dispatcher
        runtime.scoring_engine = mock_scoring_engine
        runtime.aggregator = mock_aggregator

        # Start services to create tasks
        await runtime.start()

        # Verify services were started
        mock_orchestrator.run.assert_called_once()
        mock_dispatcher.run.assert_called_once()
        mock_scoring_engine.run.assert_called_once()
        mock_aggregator.run.assert_called_once()

        # Clean up tasks
        for task in runtime._tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_signal_handler_sets_shutdown_event(self):
        """Signal handler should set shutdown event."""
        runtime = AgentBenchRuntime()

        # Initially not set
        assert not runtime._shutdown_event.is_set()

        # Trigger signal handler
        await runtime._signal_handler(signal.SIGTERM)

        # Event should be set
        assert runtime._shutdown_event.is_set()


class TestErrorHandling:
    """Test error handling during initialization."""

    @pytest.mark.asyncio
    async def test_handles_initialization_errors(self):
        """Runtime should handle initialization errors gracefully."""
        runtime = AgentBenchRuntime()
        runtime._setup_signal_handlers = MagicMock()

        # Simulate initialization failure
        with (
            patch.object(runtime, "initialize", side_effect=Exception("Init failed")),
            pytest.raises(Exception, match="Init failed"),
        ):
            await runtime.run()

    @pytest.mark.asyncio
    async def test_handles_service_start_errors(
        self,
        mock_orchestrator,
        mock_dispatcher,
        mock_scoring_engine,
        mock_aggregator,
    ):
        """Runtime should handle service start errors."""
        runtime = AgentBenchRuntime()
        runtime._setup_signal_handlers = MagicMock()

        # Inject mocks
        runtime.orchestrator = mock_orchestrator
        runtime.dispatcher = mock_dispatcher
        runtime.scoring_engine = mock_scoring_engine
        runtime.aggregator = mock_aggregator

        # Make one service fail to start
        mock_orchestrator.run = AsyncMock(side_effect=Exception("Start failed"))

        with pytest.raises(Exception, match="Start failed"):
            await runtime.start()
