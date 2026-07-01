"""Aggregator service for AgentBench.

This module provides the Aggregator class which:
1. Consumes stream:scores (step.scored, workflow.completed) events
2. Accumulates step scores in memory keyed by run_id
3. Computes and persists RunReport on workflow.completed
4. Computes and persists BenchmarkReport when all runs complete
5. Emits benchmark.report.generated event

Service contract:
- Consumes: stream:scores (step.scored, workflow.completed)
- Publishes: stream:reports (benchmark.report.generated)
- Owns: RunReport and BenchmarkReport documents in MongoDB
"""

import asyncio
import json
import logging
import os
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import redis.asyncio as redis_module
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

from agentbench.cases.loader import load_case, resolve_case_topic
from agentbench.events.bus import EventBus
from agentbench.events.types import STREAM_REPORTS, STREAM_SCORES
from agentbench.models import (
    BENCHMARK_REPORT_GENERATED,
    STEP_SCORED,
    WORKFLOW_COMPLETED,
    AgentSummary,
    BenchmarkReport,
    EventEnvelope,
    RunReport,
    RunState,
    StepScore,
)
from agentbench.storage.mongo import MongoStorage
from agentbench.storage.redis_client import RedisStorage

logger = logging.getLogger(__name__)

HANDLED_AGGREGATOR_ERRORS = (
    redis_module.RedisError,
    ValidationError,
    ValueError,
    FileNotFoundError,
    json.JSONDecodeError,
)


class Aggregator:
    """Accumulates step scores and generates reports.

    The Aggregator is a long-running asyncio service that:
    - Listens to stream:scores for step.scored and workflow.completed events
    - Accumulates StepScore objects in memory by run_id
    - Generates RunReport when a workflow completes
    - Generates BenchmarkReport when all expected runs for a benchmark complete
    - Persists reports to MongoDB

    Attributes:
        event_bus: EventBus for consuming and publishing events.
        mongo_storage: MongoStorage for persisting reports.
        redis_storage: RedisStorage for tracking benchmark completion.
        _running: Flag to control the main loop.
        _run_scores: In-memory accumulation of scores by run_id.
    """

    def __init__(
        self,
        event_bus: EventBus,
        mongo_storage: MongoStorage,
        redis_storage: RedisStorage,
    ):
        """Initialize the aggregator.

        Args:
            event_bus: EventBus instance for event consumption and publishing.
            mongo_storage: MongoStorage for persisting RunReport and BenchmarkReport.
            redis_storage: RedisStorage for checking benchmark completion status.
        """
        self.event_bus = event_bus
        self.mongo_storage = mongo_storage
        self.redis_storage = redis_storage
        self._running = False
        # In-memory accumulation: run_id -> list of StepScore
        self._run_scores: dict[str, list[StepScore]] = defaultdict(list)

    def _calculate_percentile(self, values: list[int], percentile: float) -> int:
        """Calculate percentile value from a list.

        Uses the nearest-rank method for percentile calculation.

        Args:
            values: List of integer values.
            percentile: Percentile to calculate (0-100).

        Returns:
            The calculated percentile value, or 0 if values is empty.
        """
        if not values:
            return 0
        sorted_values = sorted(values)
        index = int(len(sorted_values) * percentile / 100)
        return sorted_values[min(index, len(sorted_values) - 1)]

    def _compute_run_report(
        self,
        run_id: str,
        benchmark_id: str,
        case_id: str,
        case_tags: list[str],
        agent_id: str,
        workflow_id: str,
        scores: list[StepScore],
    ) -> RunReport:
        """Compute a RunReport from accumulated scores.

        Args:
            run_id: The run identifier.
            benchmark_id: The benchmark identifier.
            case_id: The case identifier.
            case_tags: Tags associated with the case.
            agent_id: The agent identifier.
            workflow_id: The workflow identifier.
            scores: List of StepScore objects accumulated for this run.

        Returns:
            A RunReport with computed totals.
        """
        total_weight = sum(s.weight for s in scores)
        total_score = sum(s.weighted_score for s in scores) / total_weight if total_weight else 0.0
        total_latency = sum(s.latency_ms for s in scores)

        return RunReport(
            run_id=run_id,
            benchmark_id=benchmark_id,
            case_id=case_id,
            case_tags=case_tags,
            agent_id=agent_id,
            workflow_id=workflow_id,
            total_score=total_score,
            step_scores=scores,
            total_latency_ms=total_latency,
            completed_at=datetime.now(UTC).isoformat(),
        )

    def _compute_benchmark_report(
        self,
        benchmark_id: str,
        workflow_id: str,
        case_set_id: str,
        run_reports: list[RunReport],
        agent_failures: dict[str, int] | None = None,
        agent_totals: dict[str, int] | None = None,
    ) -> BenchmarkReport:
        """Compute a BenchmarkReport from run reports.

        Aggregates per-agent statistics including average scores,
        latency percentiles, and per-case score breakdowns.

        Args:
            benchmark_id: The benchmark identifier.
            workflow_id: The workflow identifier.
            case_set_id: The case set identifier.
            run_reports: List of RunReport objects for completed runs.
            agent_failures: Per-agent count of terminally failed runs. Failed and
                timed-out runs never produce RunReports, so this is supplied
                separately by the caller.
            agent_totals: Per-agent count of total runs (successful and failed),
                used as the failure_rate denominator.

        Returns:
            A BenchmarkReport with agent summaries and per-case scores.
        """
        # Aggregate scores by agent
        agent_scores: dict[str, list[float]] = defaultdict(list)
        agent_latencies: dict[str, list[int]] = defaultdict(list)
        # Failure counts and run totals cover all runs (including failed ones,
        # which never emit RunReports); default to no failures when unavailable.
        failures = agent_failures or {}
        totals = agent_totals or {}

        for report in run_reports:
            agent_scores[report.agent_id].append(report.total_score)
            agent_latencies[report.agent_id].append(report.total_latency_ms)

        # Track per-case scores for cross-agent comparison
        per_case_scores: dict[str, dict[str, float]] = defaultdict(dict)
        for report in run_reports:
            per_case_scores[report.case_id][report.agent_id] = report.total_score

        # Map each case to its canonical topic
        per_case_topics: dict[str, str] = {}
        seen_cases: set[str] = set()
        for report in run_reports:
            if report.case_id not in seen_cases:
                seen_cases.add(report.case_id)
                per_case_topics[report.case_id] = resolve_case_topic(report.case_tags)
        # Build final agent summaries with step breakdowns
        agents = []
        for agent_id in agent_scores:
            scores = agent_scores[agent_id]
            latencies = agent_latencies[agent_id]
            # Failure rate is failures over total runs; fall back to the count of
            # successful runs when run totals were not provided.
            total_runs = totals.get(agent_id, len(scores))

            # Average raw step scores across all runs for this agent
            step_scores: dict[str, list[float]] = defaultdict(list)
            for report in run_reports:
                if report.agent_id == agent_id:
                    for step_score in report.step_scores:
                        step_scores[step_score.step_id].append(step_score.raw_score)

            step_breakdown = {
                step_id: sum(scores) / len(scores) if scores else 0.0
                for step_id, scores in step_scores.items()
            }

            summary = AgentSummary(
                agent_id=agent_id,
                avg_score=sum(scores) / len(scores) if scores else 0.0,
                p50_latency_ms=self._calculate_percentile(latencies, 50),
                p95_latency_ms=self._calculate_percentile(latencies, 95),
                failure_rate=failures.get(agent_id, 0) / total_runs if total_runs else 0.0,
                step_breakdown=step_breakdown,
            )
            agents.append(summary)

        return BenchmarkReport(
            benchmark_id=benchmark_id,
            workflow_id=workflow_id,
            case_set_id=case_set_id,
            created_at=datetime.now(UTC).isoformat(),
            case_count=len(per_case_scores),
            agents=agents,
            per_case_scores=dict(per_case_scores),
            per_case_topics=per_case_topics,
        )

    def _handle_step_scored(self, envelope: EventEnvelope) -> None:
        """Accumulate step scores in memory keyed by run_id."""
        payload = envelope.payload
        run_id = payload["run_id"]

        # Create StepScore from payload
        score = StepScore(
            run_id=run_id,
            case_id=payload.get("case_id", ""),
            step_id=payload["step_id"],
            strategy=payload.get("strategy", ""),
            raw_score=payload.get("raw_score", 0.0),
            weight=payload.get("weight", 1.0),
            weighted_score=payload.get("weighted_score", 0.0),
            latency_ms=payload.get("latency_ms", 0),
            passed=payload.get("passed", False),
            details=payload.get("details", {}),
        )

        self._run_scores[run_id].append(score)
        logger.info(
            f"Accumulated score for run {run_id}, step {score.step_id}",
            extra={
                "correlation_id": run_id,
                "run_id": run_id,
                "step_id": score.step_id,
                "strategy": score.strategy,
                "weighted_score": score.weighted_score,
            },
        )

    async def _handle_workflow_completed(self, envelope: EventEnvelope) -> None:
        """Handle workflow.completed event.

        Computes and persists RunReport, checks if benchmark is complete,
        and generates BenchmarkReport if all runs are done.

        Args:
            envelope: The EventEnvelope containing the workflow.completed event.
        """
        payload = envelope.payload
        run_id = payload["run_id"]
        benchmark_id = payload["benchmark_id"]

        # Get accumulated scores
        scores = self._run_scores.get(run_id, [])
        if not scores:
            logger.warning(
                f"No scores accumulated for run {run_id}",
                extra={"correlation_id": run_id, "run_id": run_id},
            )
            return

        # Load run from storage to get metadata
        run = await self.mongo_storage.get_run(run_id)
        if run is None:
            logger.error(
                f"Run not found: {run_id}",
                extra={"correlation_id": run_id, "run_id": run_id},
            )
            return

        # Load case to get tags
        fixtures_dir = Path(os.environ.get("PR_REVIEW_FIXTURES_DIR", "fixtures/pr_review"))
        case = load_case(run.case_id, fixtures_dir)
        case_tags = case.tags

        # Compute and persist RunReport
        report = self._compute_run_report(
            run_id=run_id,
            benchmark_id=benchmark_id,
            case_id=run.case_id,
            case_tags=case_tags,
            agent_id=run.agent_id,
            workflow_id=run.workflow_id,
            scores=scores,
        )

        try:
            await self.mongo_storage.create_run_report(report)
            logger.info(
                f"Created run report for {run_id}",
                extra={
                    "correlation_id": run_id,
                    "run_id": run_id,
                    "benchmark_id": benchmark_id,
                    "total_score": report.total_score,
                },
            )
        except DuplicateKeyError:
            logger.warning(
                f"Run report already exists for {run_id}, treating as idempotent",
                extra={"correlation_id": run_id, "run_id": run_id},
            )

        # Mark run as completed in Redis
        await self.redis_storage.mark_run_completed(benchmark_id, run_id)

        # Check if benchmark is complete
        is_complete = await self.redis_storage.is_benchmark_complete(benchmark_id)
        if is_complete:
            logger.info(
                f"Benchmark {benchmark_id} is complete, generating report",
                extra={"correlation_id": run_id, "benchmark_id": benchmark_id},
            )
            await self._generate_benchmark_report(benchmark_id)

        # Clean up accumulated scores
        del self._run_scores[run_id]

    async def _generate_benchmark_report(self, benchmark_id: str) -> None:
        """Generate final benchmark report.

        Loads all run reports for the benchmark, computes aggregate statistics,
        persists the BenchmarkReport, and emits the report generated event.

        Args:
            benchmark_id: The benchmark identifier.
        """
        # Get all completed run IDs for benchmark
        run_ids = await self.redis_storage.get_benchmark_completed_runs(benchmark_id)

        # Load run reports
        run_reports = []
        for run_id in run_ids:
            report = await self.mongo_storage.get_run_report(run_id)
            if report:
                run_reports.append(report)

        if not run_reports:
            logger.warning(
                f"No run reports found for benchmark {benchmark_id}",
                extra={"correlation_id": benchmark_id, "benchmark_id": benchmark_id},
            )
            return

        # Get workflow and case set info from first report
        first_report = run_reports[0]
        workflow_id = first_report.workflow_id
        # Load case set ID from first report's run
        first_run = await self.mongo_storage.get_run(first_report.run_id)
        case_set_id = first_run.case_set_id if first_run else "pr_review_cases_v1"

        # Tally per-agent totals and terminal failures across ALL runs. Failed and
        # timed-out runs never emit workflow.completed, so they are absent from
        # run_reports; load them from Mongo to compute an accurate failure rate.
        all_runs = await self.mongo_storage.list_runs(benchmark_id=benchmark_id)
        agent_totals: dict[str, int] = defaultdict(int)
        agent_failures: dict[str, int] = defaultdict(int)
        for run in all_runs:
            agent_totals[run.agent_id] += 1
            if run.state in (RunState.FAILED, RunState.TIMED_OUT):
                agent_failures[run.agent_id] += 1

        # Compute benchmark report
        benchmark_report = self._compute_benchmark_report(
            benchmark_id=benchmark_id,
            workflow_id=workflow_id,
            case_set_id=case_set_id,
            run_reports=run_reports,
            agent_failures=agent_failures,
            agent_totals=agent_totals,
        )

        try:
            await self.mongo_storage.create_benchmark_report(benchmark_report)
            logger.info(
                f"Created benchmark report for {benchmark_id}",
                extra={
                    "correlation_id": benchmark_id,
                    "benchmark_id": benchmark_id,
                    "case_count": benchmark_report.case_count,
                    "agent_count": len(benchmark_report.agents),
                },
            )
        except DuplicateKeyError:
            logger.warning(
                f"Benchmark report already exists for {benchmark_id}, treating as idempotent",
                extra={"correlation_id": benchmark_id, "benchmark_id": benchmark_id},
            )

        # Emit report generated event
        event = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=BENCHMARK_REPORT_GENERATED,
            schema_version="1.0",
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id=benchmark_id,
            payload={"benchmark_id": benchmark_id},
        )

        await self.event_bus.publish(STREAM_REPORTS, event)
        logger.info(
            f"Generated benchmark report for {benchmark_id}",
            extra={
                "correlation_id": benchmark_id,
                "benchmark_id": benchmark_id,
            },
        )

    async def run(self) -> None:
        """Main loop.

        Consumes events from stream:scores and dispatches to appropriate
        handlers based on event type. Runs until stop() is called.
        """
        self._running = True
        logger.info("Aggregator started")

        while self._running:
            try:
                async for envelope in self.event_bus.consume(
                    STREAM_SCORES,
                    consumer_group="aggregator",
                    consumer_name="aggregator-1",
                ):
                    if not self._running:
                        break

                    if envelope.event_type == STEP_SCORED:
                        self._handle_step_scored(envelope)
                    elif envelope.event_type == WORKFLOW_COMPLETED:
                        await self._handle_workflow_completed(envelope)

                    # Acknowledge the message
                    if envelope.delivery_message_id:
                        delivery_stream = (
                            envelope.delivery_stream
                            if isinstance(envelope.delivery_stream, str)
                            else STREAM_SCORES
                        )
                        delivery_consumer_group = (
                            envelope.delivery_consumer_group
                            if isinstance(envelope.delivery_consumer_group, str)
                            else "aggregator"
                        )
                        await self.event_bus.ack(
                            delivery_stream,
                            delivery_consumer_group,
                            envelope.delivery_message_id,
                        )
            except HANDLED_AGGREGATOR_ERRORS as e:
                logger.error(f"Error in aggregator: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the aggregator.

        Sets the running flag to False, causing the main loop to exit
        after processing the current message.
        """
        self._running = False
        logger.info("Aggregator stopped")

    # ==========================================================================
    # Utility methods for testing and debugging
    # ==========================================================================

    def get_accumulated_scores(self, run_id: str) -> list[StepScore]:
        """Get accumulated scores for a run (for testing).

        Args:
            run_id: The run identifier.

        Returns:
            List of accumulated StepScore objects, or empty list if none.
        """
        return self._run_scores.get(run_id, [])

    def clear_accumulated_scores(self, run_id: str | None = None) -> None:
        """Clear accumulated scores (for testing).

        Args:
            run_id: Optional run_id to clear. If None, clears all.
        """
        if run_id:
            if run_id in self._run_scores:
                del self._run_scores[run_id]
        else:
            self._run_scores.clear()
