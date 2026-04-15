"""Orchestrator service for AgentBench.

This module provides the Orchestrator class that manages evaluation runs,
step progression, and FSM state. It coordinates with other services through
the event bus.

Per spec Section 9.2:
- Consumes: stream:eval-runs (evaluation.run.requested, step.scored)
- Publishes: stream:eval-runs (evaluation.run.started, evaluation.run.completed,
                              evaluation.run.failed),
            stream:eval-steps (workflow.step.dispatched)
- Owns: FSM state in Redis

Behavior:
1. On evaluation.run.requested, load workflow and set FSM to STARTED
2. Dispatch step 0 for the run
3. On step.scored, advance step cursor
4. Dispatch next step or emit workflow.completed when all steps done
5. On timeout/unrecoverable error, emit evaluation.run.failed
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from agentbench.cases.loader import load_case_set
from agentbench.events.types import (
    EVALUATION_RUN_COMPLETED,
    EVALUATION_RUN_FAILED,
    EVALUATION_RUN_REQUESTED,
    EVALUATION_RUN_STARTED,
    STEP_SCORED,
    STREAM_EVAL_RUNS,
    STREAM_EVAL_STEPS,
    STREAM_SCORES,
    WORKFLOW_COMPLETED,
    WORKFLOW_STEP_DISPATCHED,
)
from agentbench.models import (
    EvaluationRun,
    EventEnvelope,
    RunState,
    WorkflowDefinition,
)

if TYPE_CHECKING:
    from agentbench.events.bus import EventBus
    from agentbench.storage.mongo import MongoStorage
    from agentbench.storage.redis_client import RedisStorage

logger = logging.getLogger(__name__)

# Fixtures directory for case loading
DEFAULT_FIXTURES_DIR = Path("fixtures/pr_review")


class Orchestrator:
    """Orchestrates benchmark runs and manages step progression.

    The orchestrator maintains FSM state in Redis and coordinates the
    lifecycle of evaluation runs. It expands benchmark requests into
    individual runs and manages step-by-step execution.
    """

    def __init__(
        self,
        event_bus: "EventBus",
        mongo_storage: "MongoStorage",
        redis_storage: "RedisStorage",
        fixtures_dir: Path | None = None,
    ):
        """Initialize the orchestrator.

        Args:
            event_bus: Event bus for publishing and consuming events.
            mongo_storage: MongoDB storage for runs and workflows.
            redis_storage: Redis storage for FSM state.
            fixtures_dir: Path to fixtures directory for case loading.
        """
        self.event_bus = event_bus
        self.mongo_storage = mongo_storage
        self.redis_storage = redis_storage
        self.fixtures_dir = fixtures_dir or DEFAULT_FIXTURES_DIR
        self._running = False

    async def _create_run(
        self,
        benchmark_id: str,
        workflow: WorkflowDefinition,
        case_set_id: str,
        case_id: str,
        agent_id: str,
    ) -> EvaluationRun:
        """Create a new evaluation run.

        Args:
            benchmark_id: The benchmark identifier.
            workflow: The workflow definition.
            case_set_id: The case set identifier.
            case_id: The case identifier.
            agent_id: The agent identifier.

        Returns:
            The created EvaluationRun.
        """
        run = EvaluationRun(
            run_id=str(uuid.uuid4()),
            benchmark_id=benchmark_id,
            workflow_id=workflow.workflow_id,
            workflow_version=workflow.version,
            case_set_id=case_set_id,
            case_id=case_id,
            agent_id=agent_id,
            agent_config={"temperature": 0},
            state=RunState.PENDING,
            created_at=datetime.now(UTC).isoformat(),
        )
        await self.mongo_storage.create_run(run)
        await self.redis_storage.add_run_to_benchmark(benchmark_id, run.run_id)
        return run

    async def _dispatch_step(self, run: EvaluationRun, step_index: int) -> None:
        """Dispatch a workflow step.

        Updates FSM state in Redis and publishes workflow.step.dispatched
        to stream:eval-steps.

        Args:
            run: The evaluation run.
            step_index: The index of the step to dispatch.

        Raises:
            ValueError: If the workflow is not found or step_index is invalid.
        """
        workflow = await self.mongo_storage.get_workflow(run.workflow_id, run.workflow_version)
        if workflow is None:
            raise ValueError(f"Workflow not found: {run.workflow_id}")

        if step_index < 0 or step_index >= len(workflow.steps):
            raise ValueError(
                f"Invalid step index {step_index} for workflow with {len(workflow.steps)} steps"
            )

        step = workflow.steps[step_index]

        # Update FSM state in Redis
        await self.redis_storage.set_current_step(run.run_id, step_index)
        await self.redis_storage.set_run_state(run.run_id, RunState.STEP_IN_PROGRESS)

        # Update run state in MongoDB
        await self.mongo_storage.update_run_state(run.run_id, RunState.STEP_IN_PROGRESS, step_index)

        # Publish step dispatched event
        logger.info(
            f"[ORCHESTRATOR] Publishing WORKFLOW_STEP_DISPATCHED: run_id={run.run_id}, step_id={step.step_id}, step_index={step_index}"
        )
        await self.event_bus.publish(
            STREAM_EVAL_STEPS,
            EventEnvelope(
                event_id=str(uuid.uuid4()),
                event_type=WORKFLOW_STEP_DISPATCHED,
                timestamp=datetime.now(UTC).isoformat(),
                correlation_id=run.run_id,
                payload={
                    "run_id": run.run_id,
                    "step_id": step.step_id,
                    "step_index": step_index,
                },
            ),
        )
        logger.info(
            "[ORCHESTRATOR] Successfully dispatched step %s for run %s",
            step.step_id,
            run.run_id,
            extra={
                "correlation_id": run.run_id,
                "step_id": step.step_id,
                "step_index": step_index,
            },
        )

    async def _handle_run_requested(self, envelope: EventEnvelope) -> None:
        """Handle evaluation.run.requested event.

        Creates runs for each (agent, case) combination and starts the first step.

        Args:
            envelope: The event envelope containing the request.

        Raises:
            ValueError: If the workflow is not found.
        """
        payload = envelope.payload
        benchmark_id = payload["benchmark_id"]
        workflow_id = payload["workflow_id"]
        case_set_id = payload["case_set_id"]
        agents = payload["agents"]

        # Get workflow
        workflow = await self.mongo_storage.get_workflow(workflow_id)
        if workflow is None:
            raise ValueError(f"Workflow not found: {workflow_id}")

        # Load enabled cases from the case set
        try:
            cases = load_case_set(case_set_id, self.fixtures_dir)
        except FileNotFoundError as e:
            logger.error(
                "Failed to load case set %s: %s",
                case_set_id,
                e,
                extra={"correlation_id": benchmark_id},
            )
            raise ValueError(f"Case set not found: {case_set_id}") from e
        except ValueError as e:
            logger.error(
                "Invalid case set %s: %s",
                case_set_id,
                e,
                extra={"correlation_id": benchmark_id},
            )
            raise

        logger.info(
            "Creating benchmark %s with %d agents and %d cases",
            benchmark_id,
            len(agents),
            len(cases),
            extra={"correlation_id": benchmark_id},
        )

        # Create runs for each (agent, case) combination
        for agent_id in agents:
            for case in cases:
                run = await self._create_run(
                    benchmark_id=benchmark_id,
                    workflow=workflow,
                    case_set_id=case_set_id,
                    case_id=case.case_id,
                    agent_id=agent_id,
                )

                # Set FSM state to STARTED
                await self.redis_storage.set_run_state(run.run_id, RunState.STARTED)
                await self.mongo_storage.update_run_state(run.run_id, RunState.STARTED)

                # Publish run started event
                await self.event_bus.publish(
                    STREAM_EVAL_RUNS,
                    EventEnvelope(
                        event_id=str(uuid.uuid4()),
                        event_type=EVALUATION_RUN_STARTED,
                        timestamp=datetime.now(UTC).isoformat(),
                        correlation_id=run.run_id,
                        payload={
                            "run_id": run.run_id,
                            "benchmark_id": benchmark_id,
                            "agent_id": agent_id,
                            "case_id": case.case_id,
                        },
                    ),
                )

                # Dispatch step 0
                await self._dispatch_step(run, 0)

        # Publish benchmark-level run started event
        await self.event_bus.publish(
            STREAM_EVAL_RUNS,
            EventEnvelope(
                event_id=str(uuid.uuid4()),
                event_type=EVALUATION_RUN_STARTED,
                timestamp=datetime.now(UTC).isoformat(),
                correlation_id=benchmark_id,
                payload={
                    "benchmark_id": benchmark_id,
                    "workflow_id": workflow_id,
                    "case_set_id": case_set_id,
                    "agents": agents,
                    "total_runs": len(agents) * len(cases),
                },
            ),
        )

    async def _handle_step_scored(self, envelope: EventEnvelope) -> None:
        """Handle step.scored event.

        Advances the step cursor and either dispatches the next step or
        emits workflow.completed when all steps are done.

        Args:
            envelope: The event envelope containing the score.
        """
        run_id = envelope.payload.get("run_id")
        if not run_id:
            logger.error("step.scored event missing run_id")
            return

        run = await self.mongo_storage.get_run(run_id)
        if run is None:
            logger.error("Run not found: %s", run_id, extra={"correlation_id": run_id})
            return

        # Get workflow
        workflow = await self.mongo_storage.get_workflow(run.workflow_id, run.workflow_version)
        if workflow is None:
            logger.error(
                "Workflow not found: %s",
                run.workflow_id,
                extra={"correlation_id": run_id},
            )
            # Mark run as failed
            await self._fail_run(run_id, f"Workflow not found: {run.workflow_id}")
            return

        # Get current step from Redis
        current_step = await self.redis_storage.get_current_step(run_id) or 0
        next_step = current_step + 1

        if next_step >= len(workflow.steps):
            # All steps completed - emit workflow.completed
            await self._complete_run(run, workflow)
        else:
            # Update step state in MongoDB
            await self.mongo_storage.update_run_state(
                run.run_id, RunState.STEP_SCORED, current_step
            )
            # Dispatch next step
            await self._dispatch_step(run, next_step)

    async def _complete_run(self, run: EvaluationRun, workflow: WorkflowDefinition) -> None:
        """Complete a run by updating state and emitting events.

        Args:
            run: The evaluation run to complete.
            workflow: The workflow definition.
        """
        # Update FSM state
        await self.redis_storage.set_run_state(run.run_id, RunState.COMPLETED)
        await self.redis_storage.mark_run_completed(run.benchmark_id, run.run_id)

        # Update MongoDB state
        await self.mongo_storage.update_run_state(run.run_id, RunState.COMPLETED)

        # Publish workflow.completed event to stream:scores per spec
        await self.event_bus.publish(
            STREAM_SCORES,
            EventEnvelope(
                event_id=str(uuid.uuid4()),
                event_type=WORKFLOW_COMPLETED,
                timestamp=datetime.now(UTC).isoformat(),
                correlation_id=run.run_id,
                payload={
                    "run_id": run.run_id,
                    "benchmark_id": run.benchmark_id,
                },
            ),
        )

        # Check if all runs in benchmark are complete
        if await self.redis_storage.is_benchmark_complete(run.benchmark_id):
            # Publish evaluation.run.completed for the benchmark
            await self.event_bus.publish(
                STREAM_EVAL_RUNS,
                EventEnvelope(
                    event_id=str(uuid.uuid4()),
                    event_type=EVALUATION_RUN_COMPLETED,
                    timestamp=datetime.now(UTC).isoformat(),
                    correlation_id=run.benchmark_id,
                    payload={
                        "benchmark_id": run.benchmark_id,
                    },
                ),
            )
            logger.info(
                "Benchmark %s completed",
                run.benchmark_id,
                extra={"correlation_id": run.benchmark_id},
            )
        else:
            logger.info(
                "Run %s completed, benchmark %s still in progress",
                run.run_id,
                run.benchmark_id,
                extra={"correlation_id": run.run_id},
            )

    async def _fail_run(self, run_id: str, error_message: str) -> None:
        """Fail a run by updating state and emitting event.

        Args:
            run_id: The run identifier.
            error_message: The error message describing the failure.
        """
        run = await self.mongo_storage.get_run(run_id)
        if run:
            # Update FSM state
            await self.redis_storage.set_run_state(run_id, RunState.FAILED)
            # Update MongoDB state
            await self.mongo_storage.update_run_state(run_id, RunState.FAILED)
            # Mark run as completed in Redis so benchmark completion check works
            await self.redis_storage.mark_run_completed(run.benchmark_id, run_id)

        # Publish evaluation.run.failed event
        await self.event_bus.publish(
            STREAM_EVAL_RUNS,
            EventEnvelope(
                event_id=str(uuid.uuid4()),
                event_type=EVALUATION_RUN_FAILED,
                timestamp=datetime.now(UTC).isoformat(),
                correlation_id=run_id,
                payload={
                    "run_id": run_id,
                    "error": error_message,
                },
            ),
        )
        logger.error(
            "Run %s failed: %s",
            run_id,
            error_message,
            extra={"correlation_id": run_id},
        )

    async def run(self) -> None:
        """Main loop for the orchestrator.

        Consumes events from stream:eval-runs and stream:scores,
        processing them according to their type.
        """
        self._running = True
        logger.info("Orchestrator started")

        # Start consumers for both streams
        await asyncio.gather(
            self._consume_eval_runs(),
            self._consume_scores(),
            return_exceptions=True,
        )

    async def _consume_eval_runs(self) -> None:
        """Consume events from stream:eval-runs."""
        try:
            async for envelope in self.event_bus.consume(
                STREAM_EVAL_RUNS,
                consumer_group="orchestrator",
                consumer_name="orchestrator-runs",
            ):
                if not self._running:
                    break

                try:
                    if envelope.event_type == EVALUATION_RUN_REQUESTED:
                        await self._handle_run_requested(envelope)
                    else:
                        logger.debug(
                            "Ignoring event type on eval-runs: %s",
                            envelope.event_type,
                            extra={"correlation_id": envelope.correlation_id},
                        )
                except Exception as e:
                    logger.exception(
                        "Error processing event %s",
                        envelope.event_type,
                        extra={"correlation_id": envelope.correlation_id},
                    )
                    if "run_id" in envelope.payload:
                        await self._fail_run(
                            envelope.payload["run_id"],
                            f"Error processing event: {str(e)}",
                        )

                # Acknowledge the message
                message_id = envelope.__dict__.get("_message_id")
                if message_id:
                    await self.event_bus.ack(
                        STREAM_EVAL_RUNS,
                        "orchestrator",
                        message_id,
                    )

        except Exception as e:
            logger.error("Error in eval-runs consumer: %s", e)

    async def _consume_scores(self) -> None:
        """Consume events from stream:scores."""
        try:
            async for envelope in self.event_bus.consume(
                STREAM_SCORES,
                consumer_group="orchestrator",
                consumer_name="orchestrator-scores",
            ):
                if not self._running:
                    break

                try:
                    if envelope.event_type == STEP_SCORED:
                        await self._handle_step_scored(envelope)
                    elif envelope.event_type == WORKFLOW_COMPLETED:
                        logger.debug(
                            "Workflow completed event received: %s",
                            envelope.payload.get("run_id"),
                            extra={"correlation_id": envelope.correlation_id},
                        )
                    else:
                        logger.debug(
                            "Ignoring event type on scores: %s",
                            envelope.event_type,
                            extra={"correlation_id": envelope.correlation_id},
                        )
                except Exception as e:
                    logger.exception(
                        "Error processing event %s",
                        envelope.event_type,
                        extra={"correlation_id": envelope.correlation_id},
                    )
                    if "run_id" in envelope.payload:
                        await self._fail_run(
                            envelope.payload["run_id"],
                            f"Error processing event: {str(e)}",
                        )

                # Acknowledge the message
                message_id = envelope.__dict__.get("_message_id")
                if message_id:
                    await self.event_bus.ack(
                        STREAM_SCORES,
                        "orchestrator",
                        message_id,
                    )

        except Exception as e:
            logger.error("Error in scores consumer: %s", e)

    async def stop(self) -> None:
        """Stop the orchestrator."""
        self._running = False
        logger.info("Orchestrator stopped")
