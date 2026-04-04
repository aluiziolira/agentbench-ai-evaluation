"""Main entry point for AgentBench.

Wires all services together in a single async process.
"""

import asyncio
import logging
import signal
import sys
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

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


class AgentBenchRuntime:
    """Main runtime that wires all services together."""

    def __init__(self):
        self.mongo_storage: MongoStorage | None = None
        self.redis_storage: RedisStorage | None = None
        self.event_bus: EventBus | None = None
        self.orchestrator: Orchestrator | None = None
        self.dispatcher: StepDispatcher | None = None
        self.scoring_engine: ScoringEngine | None = None
        self.aggregator: Aggregator | None = None
        self._shutdown_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def _signal_handler(self, sig: signal.Signals) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received signal {sig.name}, shutting down...")
        self._shutdown_event.set()

    async def initialize(self) -> None:
        """Initialize all services."""
        logger.info("Initializing AgentBench runtime...")

        # Storage
        mongo_uri = "mongodb://localhost:27017"
        db_name = "agentbench"

        self.mongo_storage = MongoStorage(mongo_uri, db_name)
        await self.mongo_storage.setup_indexes()
        logger.info("MongoDB storage initialized")

        self.redis_storage = RedisStorage(redis_url="redis://localhost:6379")
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

        # Start service tasks
        self._tasks = [
            asyncio.create_task(self.orchestrator.run(), name="orchestrator"),
            asyncio.create_task(self.dispatcher.run(), name="dispatcher"),
            asyncio.create_task(self.scoring_engine.run(), name="scoring_engine"),
            asyncio.create_task(self.aggregator.run(), name="aggregator"),
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
            try:
                await task
            except asyncio.CancelledError:
                pass

        logger.info("All services stopped")

    async def run(self) -> None:
        """Main runtime loop."""
        await self.initialize()
        await self.start()

        # Set up signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self._signal_handler(s)))

        logger.info("AgentBench runtime running. Press Ctrl+C to stop.")

        # Wait for shutdown signal
        await self._shutdown_event.wait()

        # Stop gracefully
        await self.stop()


async def main():
    """Main entry point."""
    runtime = AgentBenchRuntime()
    await runtime.run()


if __name__ == "__main__":
    asyncio.run(main())
