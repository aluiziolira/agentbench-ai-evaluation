"""Main entry point for AgentBench.

Wires all services together in a single async process.
"""

import asyncio
import contextlib
import logging
import signal
import sys
import traceback
from collections.abc import Coroutine
from functools import partial
from pathlib import Path

import structlog
from dotenv import load_dotenv

from agentbench.aggregator.aggregator import Aggregator
from agentbench.config import get_settings
from agentbench.dispatcher.dispatcher import StepDispatcher
from agentbench.events.bus import EventBus
from agentbench.orchestrator.orchestrator import Orchestrator
from agentbench.scoring.engine import ScoringEngine
from agentbench.storage.mongo import MongoStorage
from agentbench.storage.redis_client import RedisStorage

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
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

    def _signal_handler(self, sig: signal.Signals) -> None:
        logger.info(f"Received signal {sig.name}, shutting down...")
        self._shutdown_event.set()

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        loop = asyncio.get_event_loop()
        try:
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, partial(self._signal_handler, sig))
        except ValueError:
            logger.warning("Signal handlers can only be set in main thread")

    async def initialize(self) -> None:
        logger.info("Initializing AgentBench runtime...")
        settings = get_settings()

        self.mongo_storage = MongoStorage(settings.mongodb_uri, settings.mongodb_db)
        await self.mongo_storage.setup_indexes()
        logger.info("MongoDB storage initialized")

        self.redis_storage = RedisStorage(redis_url=settings.redis_url)
        _ = await self.redis_storage._get_client()
        logger.info("Redis storage initialized")

        redis_client = await self.redis_storage._get_client()
        self.event_bus = EventBus(redis_client=redis_client)
        logger.info("Event bus initialized")

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

        self._tasks = [
            asyncio.create_task(coroutine, name=name) for name, coroutine in service_coroutines
        ]

        logger.info("All services started")

    async def stop(self) -> None:
        logger.info("Stopping AgentBench services...")

        if self.orchestrator:
            await self.orchestrator.stop()
        if self.dispatcher:
            await self.dispatcher.stop()
        if self.scoring_engine:
            await self.scoring_engine.stop()
        if self.aggregator:
            await self.aggregator.stop()

        for task in self._tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        logger.info("All services stopped")

    async def run(self) -> None:
        self._setup_signal_handlers()

        try:
            await self.initialize()
            await self.start()
        except Exception:
            logger.exception("Failed to initialize or start services")
            logging.shutdown()
            raise

        logger.info("AgentBench runtime running. Press Ctrl+C to stop.")

        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            logger.info("Runtime cancelled, shutting down...")
        finally:
            await self.stop()


async def main() -> None:
    runtime = AgentBenchRuntime()
    await runtime.run()


def _main_entry_point() -> None:
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
