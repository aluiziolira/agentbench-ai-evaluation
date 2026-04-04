"""Unit tests for the main runtime (MAIN-01).

Tests runtime initialization, service startup, and graceful shutdown.
"""

import asyncio
import os
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentbench.main import AgentBenchRuntime, main


@pytest.fixture
def mock_mongo_storage():
    """Create a mock MongoStorage."""
    storage = AsyncMock()
    storage.setup_indexes = AsyncMock()
    return storage


@pytest.fixture
def mock_redis_storage():
    """Create a mock RedisStorage with a client."""
    storage = AsyncMock()
    storage._get_client = AsyncMock(return_value=MagicMock())
    return storage


@pytest.fixture
def mock_event_bus():
    """Create a mock EventBus."""
    return MagicMock()


@pytest.fixture
def mock_orchestrator():
    """Create a mock Orchestrator."""
    orch = MagicMock()
    orch.run = AsyncMock()
    orch.stop = AsyncMock()
    return orch


@pytest.fixture
def mock_dispatcher():
    """Create a mock StepDispatcher."""
    disp = MagicMock()
    disp.run = AsyncMock()
    disp.stop = AsyncMock()
    return disp


@pytest.fixture
def mock_scoring_engine():
    """Create a mock ScoringEngine."""
    engine = MagicMock()
    engine.run = AsyncMock()
    engine.stop = AsyncMock()
    return engine


@pytest.fixture
def mock_aggregator():
    """Create a mock Aggregator."""
    agg = MagicMock()
    agg.run = AsyncMock()
    agg.stop = AsyncMock()
    return agg


class TestAgentBenchRuntime:
    """Tests for AgentBenchRuntime class."""

    @pytest.mark.asyncio
    async def test_initialize_creates_all_services(
        self,
        mock_mongo_storage,
        mock_redis_storage,
        mock_event_bus,
        mock_orchestrator,
        mock_dispatcher,
        mock_scoring_engine,
        mock_aggregator,
    ):
        """Test that initialize() creates all required services."""
        runtime = AgentBenchRuntime()

        with (
            patch(
                "agentbench.main.MongoStorage", return_value=mock_mongo_storage
            ) as mock_mongo_class,
            patch(
                "agentbench.main.RedisStorage", return_value=mock_redis_storage
            ) as mock_redis_class,
            patch("agentbench.main.EventBus", return_value=mock_event_bus) as mock_bus_class,
            patch(
                "agentbench.main.Orchestrator", return_value=mock_orchestrator
            ) as mock_orch_class,
            patch(
                "agentbench.main.StepDispatcher", return_value=mock_dispatcher
            ) as mock_disp_class,
            patch(
                "agentbench.main.ScoringEngine", return_value=mock_scoring_engine
            ) as mock_score_class,
            patch("agentbench.main.Aggregator", return_value=mock_aggregator) as mock_agg_class,
            patch.dict(
                os.environ,
                {"MONGODB_URI": "mongodb://localhost:27017", "REDIS_URL": "redis://localhost:6379"},
                clear=False,
            ),
        ):
            await runtime.initialize()

            # Verify all storage classes were instantiated with env values
            mock_mongo_class.assert_called_once_with("mongodb://localhost:27017", "agentbench")
            mock_redis_class.assert_called_once_with(redis_url="redis://localhost:6379")
            mock_bus_class.assert_called_once_with(
                redis_client=mock_redis_storage._get_client.return_value
            )

            # Verify all services were instantiated with correct dependencies
            mock_orch_class.assert_called_once_with(
                event_bus=mock_event_bus,
                mongo_storage=mock_mongo_storage,
                redis_storage=mock_redis_storage,
            )
            mock_disp_class.assert_called_once_with(
                event_bus=mock_event_bus,
                mongo_storage=mock_mongo_storage,
                raw_io_dir=Path("data/raw_io"),
            )
            mock_score_class.assert_called_once_with(
                event_bus=mock_event_bus,
                mongo_storage=mock_mongo_storage,
            )
            mock_agg_class.assert_called_once_with(
                event_bus=mock_event_bus,
                mongo_storage=mock_mongo_storage,
                redis_storage=mock_redis_storage,
            )

            # Verify storage setup
            mock_mongo_storage.setup_indexes.assert_called_once()
            mock_redis_storage._get_client.assert_called()

            # Verify runtime attributes
            assert runtime.mongo_storage is mock_mongo_storage
            assert runtime.redis_storage is mock_redis_storage
            assert runtime.event_bus is mock_event_bus
            assert runtime.orchestrator is mock_orchestrator
            assert runtime.dispatcher is mock_dispatcher
            assert runtime.scoring_engine is mock_scoring_engine
            assert runtime.aggregator is mock_aggregator

    @pytest.mark.asyncio
    async def test_start_creates_service_tasks(
        self,
        mock_orchestrator,
        mock_dispatcher,
        mock_scoring_engine,
        mock_aggregator,
    ):
        """Test that start() creates asyncio tasks for all services."""
        runtime = AgentBenchRuntime()
        runtime.orchestrator = mock_orchestrator
        runtime.dispatcher = mock_dispatcher
        runtime.scoring_engine = mock_scoring_engine
        runtime.aggregator = mock_aggregator

        await runtime.start()

        # Verify tasks were created
        assert len(runtime._tasks) == 4
        assert runtime._tasks[0].get_name() == "orchestrator"
        assert runtime._tasks[1].get_name() == "dispatcher"
        assert runtime._tasks[2].get_name() == "scoring_engine"
        assert runtime._tasks[3].get_name() == "aggregator"

        # Verify service run methods were called
        mock_orchestrator.run.assert_called_once()
        mock_dispatcher.run.assert_called_once()
        mock_scoring_engine.run.assert_called_once()
        mock_aggregator.run.assert_called_once()

        # Clean up tasks
        for task in runtime._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_stop_calls_service_stop_methods(
        self,
        mock_orchestrator,
        mock_dispatcher,
        mock_scoring_engine,
        mock_aggregator,
    ):
        """Test that stop() calls stop() on all services."""
        runtime = AgentBenchRuntime()
        runtime.orchestrator = mock_orchestrator
        runtime.dispatcher = mock_dispatcher
        runtime.scoring_engine = mock_scoring_engine
        runtime.aggregator = mock_aggregator

        # Create fake tasks that will be cancelled
        async def fake_run():
            await asyncio.sleep(100)

        runtime._tasks = [
            asyncio.create_task(fake_run(), name="orchestrator"),
            asyncio.create_task(fake_run(), name="dispatcher"),
            asyncio.create_task(fake_run(), name="scoring_engine"),
            asyncio.create_task(fake_run(), name="aggregator"),
        ]

        await runtime.stop()

        # Verify all service stop methods were called
        mock_orchestrator.stop.assert_called_once()
        mock_dispatcher.stop.assert_called_once()
        mock_scoring_engine.stop.assert_called_once()
        mock_aggregator.stop.assert_called_once()

        # Verify tasks were cancelled
        for task in runtime._tasks:
            assert task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_handles_none_services(self):
        """Test that stop() handles None services gracefully."""
        runtime = AgentBenchRuntime()
        # All services are None by default

        # Should not raise any errors
        await runtime.stop()

    @pytest.mark.asyncio
    async def test_signal_handler_triggers_shutdown(self):
        """Test that signal handler sets the shutdown event."""
        runtime = AgentBenchRuntime()

        # Signal handler should set the event
        assert not runtime._shutdown_event.is_set()
        await runtime._signal_handler(signal.SIGTERM)
        assert runtime._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_run_initializes_and_starts_services(self):
        """Test that run() calls initialize() and start()."""
        runtime = AgentBenchRuntime()

        with (
            patch.object(runtime, "initialize", AsyncMock()) as mock_init,
            patch.object(runtime, "start", AsyncMock()) as mock_start,
            patch.object(runtime, "stop", AsyncMock()) as mock_stop,
            patch("asyncio.get_event_loop") as mock_get_loop,
        ):
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            # Set shutdown event immediately so run() completes
            runtime._shutdown_event.set()

            await runtime.run()

            mock_init.assert_called_once()
            mock_start.assert_called_once()
            mock_stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_sets_signal_handlers(self):
        """Test that run() sets up signal handlers."""
        runtime = AgentBenchRuntime()

        with (
            patch.object(runtime, "initialize", AsyncMock()),
            patch.object(runtime, "start", AsyncMock()),
            patch.object(runtime, "stop", AsyncMock()),
            patch("asyncio.get_event_loop") as mock_get_loop,
        ):
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            # Set shutdown event immediately so run() completes
            runtime._shutdown_event.set()

            await runtime.run()

            # Verify signal handlers were set up
            assert mock_loop.add_signal_handler.call_count == 2
            calls = mock_loop.add_signal_handler.call_args_list
            assert calls[0][0][0] == signal.SIGTERM
            assert calls[1][0][0] == signal.SIGINT


@pytest.mark.asyncio
async def test_main_entry_point():
    """Test the main() entry point function."""
    with patch("agentbench.main.AgentBenchRuntime") as mock_runtime_class:
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock()
        mock_runtime_class.return_value = mock_runtime

        await main()

        mock_runtime_class.assert_called_once()
        mock_runtime.run.assert_called_once()
