"""Step dispatcher service for AgentBench.

This module provides the StepDispatcher class that:
- Consumes workflow.step.dispatched events from stream:eval-steps
- Loads cases, renders prompts with case placeholders
- Resolves and invokes the correct AgentAdapter
- Persists raw I/O to filesystem under data/raw_io/{run_id}/{step_id}.json
- Emits agent.response.received or workflow.step.timed_out events

Service contract:
- Consumes: stream:eval-steps (workflow.step.dispatched)
- Publishes: stream:eval-steps (agent.response.received, workflow.step.timed_out)
- Owns: raw I/O files under data/raw_io/{run_id}/{step_id}.json
"""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentbench.cases.loader import load_case
from agentbench.cases.models import ReviewCaseDefinition
from agentbench.dispatcher.adapters import ADAPTER_REGISTRY
from agentbench.events.bus import EventBus
from agentbench.events.types import (
    AGENT_RESPONSE_RECEIVED,
    EVALUATION_RUN_FAILED,
    STREAM_EVAL_RUNS,
    STREAM_EVAL_STEPS,
    WORKFLOW_STEP_TIMED_OUT,
)
from agentbench.models import EvaluationRun, RunState, StepDefinition
from agentbench.models.events import EventEnvelope
from agentbench.storage.mongo import MongoStorage
from agentbench.storage.redis_client import RedisStorage

logger = logging.getLogger(__name__)


class StepDispatcher:
    """Dispatches workflow steps to agents and manages raw I/O persistence.

    The dispatcher is a long-running asyncio service that consumes events
    from Redis Streams and coordinates agent invocation.

    Attributes:
        event_bus: Redis Streams event bus for publishing/consuming events.
        mongo_storage: MongoDB storage for workflows and runs.
        raw_io_dir: Directory for persisting raw agent I/O files.
        _running: Flag to control the main loop.
    """

    def __init__(
        self,
        event_bus: EventBus,
        mongo_storage: MongoStorage,
        redis_storage: RedisStorage,
        raw_io_dir: Path = Path("data/raw_io"),
    ):
        """Initialize the step dispatcher.

        Args:
            event_bus: Redis Streams event bus instance.
            mongo_storage: MongoDB storage for loading runs and workflows.
            raw_io_dir: Directory path for raw I/O file storage.
        """
        self.event_bus = event_bus
        self.mongo_storage = mongo_storage
        self.redis_storage = redis_storage
        self.raw_io_dir = raw_io_dir
        self._running = False

    async def _fail_run(self, run: EvaluationRun, error_message: str) -> None:
        """Mark a run as failed due to dispatch error."""
        await self.redis_storage.set_run_state(run.run_id, RunState.FAILED)
        await self.mongo_storage.update_run_state(run.run_id, RunState.FAILED)
        await self.redis_storage.mark_run_completed(run.benchmark_id, run.run_id)
        await self.event_bus.publish(
            STREAM_EVAL_RUNS,
            EventEnvelope(
                event_id=str(uuid.uuid4()),
                event_type=EVALUATION_RUN_FAILED,
                timestamp=datetime.now(UTC).isoformat(),
                correlation_id=run.run_id,
                payload={
                    "run_id": run.run_id,
                    "error": error_message,
                },
            ),
        )
        logger.error("Run %s failed: %s", run.run_id, error_message)

    def _render_prompt(self, step: StepDefinition, case: ReviewCaseDefinition) -> str:
        """Render prompt template with case placeholders.

        Placeholders supported:
        - {ticket_text}: The ticket/PR description
        - {diff_patch}: The unified diff
        - {case_id}: The case identifier

        Args:
            step: Workflow step containing the prompt template.
            case: Review case with placeholder values.

        Returns:
            Rendered prompt string with placeholders replaced.
        """
        # Use safe string replacement instead of format() to avoid
        # issues with curly braces in JSON examples within the template
        result = step.input
        result = result.replace("{ticket_text}", case.ticket_text)
        result = result.replace("{diff_patch}", case.diff_patch)
        result = result.replace("{case_id}", case.case_id)
        return result

    def _persist_raw_io(
        self,
        run: EvaluationRun,
        step: StepDefinition,
        request: dict[str, Any],
        response: str,
        latency_ms: int,
    ) -> Path:
        """Persist raw I/O to filesystem. Called via asyncio.to_thread."""
        run_dir = self.raw_io_dir / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        io_data = {
            "run_id": run.run_id,
            "case_set_id": run.case_set_id,
            "case_id": run.case_id,
            "step_id": step.step_id,
            "agent_id": run.agent_id,
            "request": request,
            "response": response,
            "latency_ms": latency_ms,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        io_file = run_dir / f"{step.step_id}.json"
        io_file.write_text(json.dumps(io_data, indent=2))
        logger.info(
            "Persisted raw I/O for run %s, step %s",
            run.run_id,
            step.step_id,
            extra={
                "correlation_id": run.run_id,
                "run_id": run.run_id,
                "step_id": step.step_id,
                "agent_id": run.agent_id,
                "latency_ms": latency_ms,
            },
        )
        return io_file

    async def _dispatch_step(self, run: EvaluationRun, step: StepDefinition) -> None:
        """Dispatch a single step to the agent.

        Args:
            run: The evaluation run context.
            step: The workflow step to dispatch.

        Raises:
            ValueError: If agent_id is unknown (no adapter in registry).
        """
        logger.info(
            "Dispatching step %s for run %s",
            step.step_id,
            run.run_id,
            extra={
                "correlation_id": run.run_id,
                "run_id": run.run_id,
                "step_id": step.step_id,
                "agent_id": run.agent_id,
                "case_id": run.case_id,
            },
        )

        import os

        fixtures_dir = Path(os.environ.get("PR_REVIEW_FIXTURES_DIR", "fixtures/pr_review"))
        case = load_case(run.case_id, fixtures_dir)

        prompt = self._render_prompt(step, case)

        adapter = ADAPTER_REGISTRY.get(run.agent_id)
        if adapter is None:
            logger.error(
                "Unknown agent_id: %s",
                run.agent_id,
                extra={
                    "correlation_id": run.run_id,
                    "run_id": run.run_id,
                    "step_id": step.step_id,
                    "agent_id": run.agent_id,
                },
            )
            raise ValueError(f"Unknown agent_id: {run.agent_id}")

        request = {"prompt": prompt, "agent_id": run.agent_id}

        timeout_seconds = step.timeout_ms / 1000.0

        try:
            rendered_step = step.model_copy(update={"input": prompt})

            response, latency_ms = await asyncio.wait_for(
                adapter.invoke(rendered_step, run, []),
                timeout=timeout_seconds,
            )

            await asyncio.to_thread(self._persist_raw_io, run, step, request, response, latency_ms)

            event = EventEnvelope(
                event_id=str(uuid.uuid4()),
                event_type=AGENT_RESPONSE_RECEIVED,
                timestamp=datetime.now(UTC).isoformat(),
                correlation_id=run.run_id,
                payload={
                    "run_id": run.run_id,
                    "step_id": step.step_id,
                    "latency_ms": latency_ms,
                },
            )
            await self.event_bus.publish(STREAM_EVAL_STEPS, event)
            logger.info(
                "Agent response received for run %s, step %s",
                run.run_id,
                step.step_id,
                extra={
                    "correlation_id": run.run_id,
                    "run_id": run.run_id,
                    "step_id": step.step_id,
                    "latency_ms": latency_ms,
                },
            )

        except TimeoutError:
            logger.warning(
                "Step %s timed out for run %s after %ss",
                step.step_id,
                run.run_id,
                timeout_seconds,
                extra={
                    "correlation_id": run.run_id,
                    "run_id": run.run_id,
                    "step_id": step.step_id,
                    "timeout_ms": step.timeout_ms,
                },
            )
            event = EventEnvelope(
                event_id=str(uuid.uuid4()),
                event_type=WORKFLOW_STEP_TIMED_OUT,
                timestamp=datetime.now(UTC).isoformat(),
                correlation_id=run.run_id,
                payload={
                    "run_id": run.run_id,
                    "step_id": step.step_id,
                },
            )
            await self.event_bus.publish(STREAM_EVAL_STEPS, event)
            await self._fail_run(run, f"Step {step.step_id} timed out after {timeout_seconds}s")
        except (RuntimeError, ValueError, ConnectionError, OSError, json.JSONDecodeError) as e:
            logger.error("Step %s failed for run %s: %s", step.step_id, run.run_id, e)
            await self._fail_run(run, f"Step dispatch failed: {e}")

    async def run(self) -> None:
        """Main loop - consume and dispatch steps.

        Consumes workflow.step.dispatched events from stream:eval-steps
        and dispatches them to the appropriate agent adapter.
        """
        self._running = True
        logger.info("Step dispatcher started")

        try:
            async for envelope in self.event_bus.consume(
                STREAM_EVAL_STEPS,
                consumer_group="dispatcher",
                consumer_name=f"dispatcher-{uuid.uuid4().hex[:8]}",
            ):
                if not self._running:
                    break

                if envelope.event_type != "workflow.step.dispatched":
                    await self.event_bus.ack(
                        STREAM_EVAL_STEPS,
                        "dispatcher",
                        envelope._message_id,  # type: ignore[attr-defined]
                    )
                    continue

                run_id = envelope.payload.get("run_id")
                step_id = envelope.payload.get("step_id")

                if not run_id or not step_id:
                    logger.error(
                        "Invalid event payload: missing run_id or step_id",
                        extra={
                            "correlation_id": envelope.correlation_id,
                            "event_type": envelope.event_type,
                        },
                    )
                    await self.event_bus.ack(
                        STREAM_EVAL_STEPS,
                        "dispatcher",
                        envelope._message_id,  # type: ignore[attr-defined]
                    )
                    continue

                logger.info(
                    "Processing dispatched step %s for run %s",
                    step_id,
                    run_id,
                    extra={"correlation_id": run_id, "run_id": run_id, "step_id": step_id},
                )

                run = await self.mongo_storage.get_run(run_id)
                if run is None:
                    logger.error(
                        f"Run not found: {run_id}",
                        extra={
                            "correlation_id": envelope.correlation_id,
                            "run_id": run_id,
                        },
                    )
                    await self.event_bus.ack(
                        STREAM_EVAL_STEPS,
                        "dispatcher",
                        envelope._message_id,  # type: ignore[attr-defined]
                    )
                    continue

                workflow = await self.mongo_storage.get_workflow(
                    run.workflow_id, run.workflow_version
                )
                if workflow is None:
                    logger.error(
                        f"Workflow not found: {run.workflow_id} version {run.workflow_version}",
                        extra={
                            "correlation_id": envelope.correlation_id,
                            "workflow_id": run.workflow_id,
                            "workflow_version": run.workflow_version,
                        },
                    )
                    await self.event_bus.ack(
                        STREAM_EVAL_STEPS,
                        "dispatcher",
                        envelope._message_id,  # type: ignore[attr-defined]
                    )
                    continue

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
                    await self.event_bus.ack(
                        STREAM_EVAL_STEPS,
                        "dispatcher",
                        envelope._message_id,  # type: ignore[attr-defined]
                    )
                    continue

                try:
                    await self._dispatch_step(run, step)
                except Exception as e:
                    logger.exception(
                        f"Failed to dispatch step {step_id} for run {run_id}: {e}",
                        extra={
                            "correlation_id": run_id,
                            "run_id": run_id,
                            "step_id": step_id,
                        },
                    )

                await self.event_bus.ack(
                    STREAM_EVAL_STEPS,
                    "dispatcher",
                    envelope._message_id,  # type: ignore[attr-defined]
                )

        except Exception:
            logger.exception("Dispatcher main loop failed")
            raise
        finally:
            logger.info("Step dispatcher main loop ended")

    async def stop(self) -> None:
        """Stop the dispatcher.

        Sets the running flag to False, which will cause the main loop
        to exit on the next iteration.
        """
        self._running = False
        logger.info("Step dispatcher stopped")
