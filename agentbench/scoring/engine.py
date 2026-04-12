"""Scoring engine service for AgentBench.

This module provides the ScoringEngine class that:
- Consumes agent.response.received events from stream:eval-steps
- Loads step definitions and review cases
- Resolves configured scoring strategies
- Computes StepScore using the appropriate strategy
- Emits step.scored events to stream:scores

Service Contract (spec Section 9.4):
- Consumes: stream:eval-steps (agent.response.received)
- Publishes: stream:scores (step.scored)
- Behavior:
  1. Load the step definition and the review case
  2. Resolve the configured scoring strategy
  3. Compute StepScore
  4. Emit step.scored
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from agentbench.cases.loader import load_case
from agentbench.cases.models import ReviewCaseDefinition
from agentbench.events.bus import EventBus
from agentbench.events.types import (
    AGENT_RESPONSE_RECEIVED,
    STEP_SCORED,
    STREAM_EVAL_STEPS,
    STREAM_SCORES,
)
from agentbench.models import (
    EvaluationRun,
    EventEnvelope,
    StepDefinition,
    StepScore,
)
from agentbench.scoring.strategies import FindingMatchStrategy, LLMJudgeStrategy
from agentbench.scoring.strategies.base import ScoringStrategy
from agentbench.storage.mongo import MongoStorage

logger = logging.getLogger(__name__)


class UnknownStrategyError(Exception):
    """Raised when an unknown scoring strategy is requested."""

    pass


class RawIONotFoundError(Exception):
    """Raised when raw I/O file is not found."""

    pass


class ScoringEngine:
    """Scores agent responses using configured strategies.

    The scoring engine is a long-running asyncio service that consumes events
    from Redis Streams, loads the necessary data (step, case, raw response),
    scores the response using the configured strategy, and emits the score.

    Attributes:
        STRATEGY_REGISTRY: Mapping of strategy IDs to strategy classes.
        event_bus: Redis Streams event bus for publishing/consuming events.
        mongo_storage: MongoDB storage for loading runs and workflows.
        raw_io_dir: Directory for reading raw agent I/O files.
        _running: Flag to control the main loop.
    """

    STRATEGY_REGISTRY: dict[str, type[ScoringStrategy]] = {
        "finding_match": FindingMatchStrategy,
        "llm_judge": LLMJudgeStrategy,
    }

    def __init__(
        self,
        event_bus: EventBus,
        mongo_storage: MongoStorage,
        raw_io_dir: Path = Path("data/raw_io"),
    ):
        """Initialize the scoring engine.

        Args:
            event_bus: Redis Streams event bus instance.
            mongo_storage: MongoDB storage for loading runs and workflows.
            raw_io_dir: Directory path for raw I/O file storage.
        """
        self.event_bus = event_bus
        self.mongo_storage = mongo_storage
        self.raw_io_dir = raw_io_dir
        self._running = False

    def _resolve_strategy(self, strategy_id: str) -> ScoringStrategy:
        """Resolve scoring strategy by ID.

        Args:
            strategy_id: The strategy identifier (e.g., "finding_match", "llm_judge").

        Returns:
            An instance of the scoring strategy.

        Raises:
            UnknownStrategyError: If the strategy ID is not in the registry.
        """
        strategy_class = self.STRATEGY_REGISTRY.get(strategy_id)
        if strategy_class is None:
            raise UnknownStrategyError(f"Unknown scoring strategy: {strategy_id}")
        return strategy_class()

    def _load_raw_io(self, run_id: str, step_id: str) -> dict:
        """Load raw I/O data from filesystem.

        File format per spec Section 13:
        - Path: data/raw_io/{run_id}/{step_id}.json
        - Contents: run_id, case_set_id, case_id, step_id, agent_id,
                    request, response, latency_ms, timestamp

        Args:
            run_id: The evaluation run identifier.
            step_id: The workflow step identifier.

        Returns:
            Dictionary containing the raw I/O data.

        Raises:
            RawIONotFoundError: If the raw I/O file does not exist.
            ValueError: If the file contains malformed JSON.
        """
        io_file = self.raw_io_dir / run_id / f"{step_id}.json"

        if not io_file.exists():
            raise RawIONotFoundError(f"Raw I/O file not found: {io_file}")

        try:
            with open(io_file, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Malformed JSON in raw I/O file {io_file}: {e}") from e

    async def _score_step(
        self,
        step: StepDefinition,
        response_text: str,
        run_id: str,
        case_id: str,
        latency_ms: int,
        case: ReviewCaseDefinition,
    ) -> StepScore:
        """Score a single step.

        Args:
            step: The workflow step definition.
            response_text: The raw agent response text.
            run_id: The evaluation run identifier.
            case_id: The case identifier.
            latency_ms: Execution latency in milliseconds.
            case: The review case definition with ground truth.

        Returns:
            StepScore containing the computed score and metadata.
        """
        # Resolve strategy
        strategy = self._resolve_strategy(step.scoring.strategy)

        # Score (await async strategy score method)
        score = await strategy.score(step, response_text, run_id, latency_ms, case)

        logger.info(
            f"Scored run {run_id}, step {step.step_id}: "
            f"raw={score.raw_score:.2f}, weighted={score.weighted_score:.2f}",
            extra={
                "correlation_id": run_id,
                "run_id": run_id,
                "case_id": case_id,
                "step_id": step.step_id,
                "strategy": step.scoring.strategy,
                "raw_score": score.raw_score,
                "weighted_score": score.weighted_score,
            },
        )

        return score

    async def _process_response(self, envelope: EventEnvelope) -> StepScore | None:
        """Process an agent response received event.

        Args:
            envelope: The EventEnvelope containing agent.response.received.

        Returns:
            StepScore if scoring succeeded, None otherwise.
        """
        run_id = envelope.payload.get("run_id")
        step_id = envelope.payload.get("step_id")
        latency_ms = envelope.payload.get("latency_ms")

        if not run_id or not step_id:
            logger.error(
                "Invalid event payload: missing run_id or step_id",
                extra={
                    "correlation_id": envelope.correlation_id,
                    "event_type": envelope.event_type,
                },
            )
            return None

        # Load run from MongoDB
        run = await self.mongo_storage.get_run(run_id)
        if run is None:
            logger.error(
                f"Run not found: {run_id}",
                extra={
                    "correlation_id": envelope.correlation_id,
                    "run_id": run_id,
                },
            )
            return None

        # Load workflow from MongoDB
        workflow = await self.mongo_storage.get_workflow(run.workflow_id, run.workflow_version)
        if workflow is None:
            logger.error(
                f"Workflow not found: {run.workflow_id} version {run.workflow_version}",
                extra={
                    "correlation_id": envelope.correlation_id,
                    "workflow_id": run.workflow_id,
                    "workflow_version": run.workflow_version,
                },
            )
            return None

        # Find step in workflow
        step = next((s for s in workflow.steps if s.step_id == step_id), None)
        if step is None:
            logger.error(
                f"Step not found: {step_id} in workflow {run.workflow_id}",
                extra={
                    "correlation_id": envelope.correlation_id,
                    "workflow_id": run.workflow_id,
                    "step_id": step_id,
                },
            )
            return None

        # Load case from fixtures
        # Get fixtures directory from environment or use default
        import os

        fixtures_dir = Path(os.environ.get("PR_REVIEW_FIXTURES_DIR", "fixtures/pr_review"))
        try:
            case = load_case(run.case_id, fixtures_dir)
        except (FileNotFoundError, ValueError) as e:
            logger.error(
                f"Failed to load case {run.case_id}: {e}",
                extra={
                    "correlation_id": run_id,
                    "run_id": run_id,
                    "case_id": run.case_id,
                },
            )
            return None

        # Load raw I/O to get response text
        try:
            raw_io = self._load_raw_io(run_id, step_id)
            response_text = raw_io.get("response", "")
            # Use latency from raw I/O if event doesn't have it
            if latency_ms is None:
                latency_ms = raw_io.get("latency_ms", 0)
        except (RawIONotFoundError, ValueError) as e:
            logger.error(
                f"Failed to load raw I/O for run {run_id}, step {step_id}: {e}",
                extra={
                    "correlation_id": run_id,
                    "run_id": run_id,
                    "step_id": step_id,
                },
            )
            return None

        # Score the step
        try:
            score = await self._score_step(
                step=step,
                response_text=response_text,
                run_id=run_id,
                case_id=run.case_id,
                latency_ms=latency_ms or 0,
                case=case,
            )
            return score
        except Exception as e:
            logger.exception(
                f"Failed to score step {step_id} for run {run_id}: {e}",
                extra={
                    "correlation_id": run_id,
                    "run_id": run_id,
                    "step_id": step_id,
                },
            )
            return None

    async def run(self) -> None:
        """Main loop - consume responses and score them.

        Consumes agent.response.received events from stream:eval-steps,
        scores them using the configured strategy, and emits step.scored
        events to stream:scores.
        """
        self._running = True
        logger.info("Scoring engine started")

        try:
            async for envelope in self.event_bus.consume(
                STREAM_EVAL_STEPS,
                consumer_group="scoring",
                consumer_name=f"scoring-{uuid.uuid4().hex[:8]}",
            ):
                if not self._running:
                    break

                # Only process agent.response.received events
                if envelope.event_type != AGENT_RESPONSE_RECEIVED:
                    # Acknowledge non-score events without processing
                    await self.event_bus.ack(
                        STREAM_EVAL_STEPS,
                        "scoring",
                        envelope._message_id,  # type: ignore[attr-defined]
                    )
                    continue

                # Process the response
                score = await self._process_response(envelope)

                if score:
                    # Emit step.scored event
                    event = EventEnvelope(
                        event_id=str(uuid.uuid4()),
                        event_type=STEP_SCORED,
                        timestamp=datetime.now(UTC).isoformat(),
                        correlation_id=envelope.payload.get("run_id", ""),
                        payload={
                            "run_id": score.run_id,
                            "case_id": score.case_id,
                            "step_id": score.step_id,
                            "score": score.raw_score,
                            "weighted_score": score.weighted_score,
                        },
                    )
                    await self.event_bus.publish(STREAM_SCORES, event)

                # Acknowledge the message after processing
                await self.event_bus.ack(
                    STREAM_EVAL_STEPS,
                    "scoring",
                    envelope._message_id,  # type: ignore[attr-defined]
                )

        except Exception:
            logger.exception("Scoring engine main loop failed")
            raise
        finally:
            logger.info("Scoring engine main loop ended")

    async def stop(self) -> None:
        """Stop the engine.

        Sets the running flag to False, which will cause the main loop
        to exit on the next iteration.
        """
        self._running = False
        logger.info("Scoring engine stopped")

    # Public API for direct scoring (useful for testing and re-scoring)
    async def score_response(
        self,
        run: EvaluationRun,
        step: StepDefinition,
        response_text: str,
        latency_ms: int,
    ) -> StepScore:
        """Score a response directly without going through the event bus.

        This is useful for testing, re-scoring, and manual scoring operations.

        Args:
            run: The evaluation run context.
            step: The workflow step definition.
            response_text: The raw agent response text.
            latency_ms: Execution latency in milliseconds.

        Returns:
            StepScore containing the computed score.

        Raises:
            UnknownStrategyError: If the scoring strategy is not recognized.
            FileNotFoundError: If the case cannot be loaded.
        """
        # Load case from fixtures
        import os

        fixtures_dir = Path(os.environ.get("PR_REVIEW_FIXTURES_DIR", "fixtures/pr_review"))
        case = load_case(run.case_id, fixtures_dir)

        return await self._score_step(
            step=step,
            response_text=response_text,
            run_id=run.run_id,
            case_id=run.case_id,
            latency_ms=latency_ms,
            case=case,
        )
