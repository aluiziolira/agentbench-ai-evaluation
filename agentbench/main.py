"""Main entry point for AgentBench.

Wires all services together in a single async process.
"""

import asyncio
import contextlib
import logging
import os
import signal
import sys
import traceback
from collections.abc import Coroutine
from pathlib import Path

import structlog
from dotenv import load_dotenv

from agentbench.aggregator.aggregator import Aggregator
from agentbench.dispatcher.dispatcher import StepDispatcher
from agentbench.events.bus import EventBus
from agentbench.orchestrator.orchestrator import Orchestrator
from agentbench.scoring.engine import ScoringEngine
from agentbench.storage.mongo import MongoStorage
from agentbench.storage.redis_client import RedisStorage

# Load environment variables
load_dotenv()

# Configure standard library logging first (before structlog)
# This ensures logs from third-party libraries are visible
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)

# Configure structlog
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        # Use console renderer for development visibility
        structlog.dev.ConsoleRenderer(colors=True)
        if sys.stdout.isatty()
        else structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


class AgentBenchRuntime:
    """Main runtime that wires all services together."""

    def __init__(self) -> None:
        self.mongo_storage: MongoStorage | None = None
        self.redis_storage: RedisStorage | None = None
        self.event_bus: EventBus | None = None
        self.orchestrator: Orchestrator | None = None
        self.dispatcher: StepDispatcher | None = None
        self.scoring_engine: ScoringEngine | None = None
        self.aggregator: Aggregator | None = None
        self._shutdown_event = asyncio.Event()
        self._tasks: list[asyncio.Task[object]] = []

    async def _signal_handler(self, sig: signal.Signals) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received signal {sig.name}, shutting down...")
        self._shutdown_event.set()

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown.

        This must be called before starting services to ensure signals
        are caught during initialization.
        """
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            # Use a regular function that sets the event directly
            # instead of creating an async task
            def handle_signal(s: signal.Signals = sig) -> None:
                # Schedule the async handler in the event loop
                asyncio.create_task(self._signal_handler(s))

            try:
                loop.add_signal_handler(sig, handle_signal)
                logger.debug(f"Registered signal handler for {sig.name}")
            except ValueError as e:
                # Can happen on Windows or if signal handlers already set
                logger.warning(f"Could not set signal handler for {sig.name}: {e}")

    async def initialize(self) -> None:
        """Initialize all services."""
        logger.info("Initializing AgentBench runtime...")

        # Storage - use environment variables with defaults
        mongo_uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
        db_name = os.environ.get("MONGODB_DB", "agentbench")

        self.mongo_storage = MongoStorage(mongo_uri, db_name)
        await self.mongo_storage.setup_indexes()
        logger.info("MongoDB storage initialized")

        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        self.redis_storage = RedisStorage(redis_url=redis_url)
        # Ensure Redis client is connected
        _ = await self.redis_storage._get_client()
        logger.info("Redis storage initialized")

        # Event bus - needs the underlying redis client
        redis_client = await self.redis_storage._get_client()
        self.event_bus = EventBus(redis_client=redis_client)
        logger.info("Event bus initialized")

        # Services
        self.orchestrator = Orchestrator(
            event_bus=self.event_bus,
            mongo_storage=self.mongo_storage,
            redis_storage=self.redis_storage,
        )
        logger.info("Orchestrator initialized")

        self.dispatcher = StepDispatcher(
            event_bus=self.event_bus,
            mongo_storage=self.mongo_storage,
            redis_storage=self.redis_storage,
            raw_io_dir=Path("data/raw_io"),
        )
        logger.info("Dispatcher initialized")

        self.scoring_engine = ScoringEngine(
            event_bus=self.event_bus,
            mongo_storage=self.mongo_storage,
        )
        logger.info("Scoring engine initialized")

        self.aggregator = Aggregator(
            event_bus=self.event_bus,
            mongo_storage=self.mongo_storage,
            redis_storage=self.redis_storage,
        )
        logger.info("Aggregator initialized")

        logger.info("All services initialized")

    async def start(self) -> None:
        """Start all services."""
        logger.info("Starting AgentBench services...")

        assert self.orchestrator is not None
        assert self.dispatcher is not None
        assert self.scoring_engine is not None
        assert self.aggregator is not None

        service_coroutines: list[tuple[str, Coroutine[object, object, object]]] = [
            ("orchestrator", self.orchestrator.run()),
            ("dispatcher", self.dispatcher.run()),
            ("scoring_engine", self.scoring_engine.run()),
            ("aggregator", self.aggregator.run()),
        ]

        # Start service tasks
        self._tasks = [
            asyncio.create_task(coroutine, name=name) for name, coroutine in service_coroutines
        ]

        logger.info("All services started")

    async def stop(self) -> None:
        """Stop all services gracefully."""
        logger.info("Stopping AgentBench services...")

        # Stop services
        if self.orchestrator:
            await self.orchestrator.stop()
        if self.dispatcher:
            await self.dispatcher.stop()
        if self.scoring_engine:
            await self.scoring_engine.stop()
        if self.aggregator:
            await self.aggregator.stop()

        # Cancel tasks
        for task in self._tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        logger.info("All services stopped")

    async def run(self) -> None:
        """Main runtime loop."""
        # Set up signal handlers FIRST, before any initialization
        self._setup_signal_handlers()

        try:
            await self.initialize()
            await self.start()
        except Exception:
            logger.exception("Failed to initialize or start services")
            # Ensure logs are flushed before exit
            logging.shutdown()
            raise

        logger.info("AgentBench runtime running. Press Ctrl+C to stop.")

        try:
            # Wait for shutdown signal
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            logger.info("Runtime cancelled, shutting down...")
        finally:
            # Stop gracefully
            await self.stop()


async def main() -> None:
    """Main entry point."""
    runtime = AgentBenchRuntime()
    try:
        await runtime.run()
    except Exception as e:
        # Log the full traceback for debugging
        logger.error(f"Fatal error in main: {e}")
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        # Re-raise to exit with non-zero code
        raise


def _main_entry_point() -> None:
    """Synchronous entry point for the application.

    Handles the asyncio.run() call with proper error handling.
    """
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        # Ensure error is printed even if logging is broken
        print(f"Fatal error: {e}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _main_entry_point()
