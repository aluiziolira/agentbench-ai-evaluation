"""MongoDB persistence layer for AgentBench.

This module provides the MongoStorage class for persisting and retrieving
workflow definitions, evaluation runs, and reports from MongoDB.
"""

from __future__ import annotations

import logging
from datetime import UTC
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from agentbench.models import (
    BenchmarkReport,
    EvaluationRun,
    RunReport,
    RunState,
    WorkflowDefinition,
)

logger = logging.getLogger(__name__)


class ImmutableWorkflowError(Exception):
    """Raised when attempting to modify a published workflow."""

    pass


class WorkflowNotFoundError(Exception):
    """Raised when a workflow is not found."""

    pass


class RunNotFoundError(Exception):
    """Raised when a run is not found."""

    pass


class MongoStorage:
    """MongoDB storage layer for AgentBench data.

    This class provides CRUD operations for workflows, runs, and reports
    with proper indexing and immutability enforcement for published workflows.

    Attributes:
        client: Motor async MongoDB client.
        db: Database instance for AgentBench collections.
    """

    def __init__(self, mongo_uri: str, db_name: str) -> None:
        """Initialize MongoDB storage."""
        self.client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(mongo_uri)
        self.db: AsyncIOMotorDatabase[Any] = self.client[db_name]

    async def setup_indexes(self) -> None:
        """Create all required MongoDB indexes.

        Creates indexes:
        - workflows: unique index on (workflow_id, version)
        - runs: unique on run_id, index on benchmark_id, index on (case_set_id, case_id)
        - run_reports: unique on run_id, index on benchmark_id, index on case_id
        - benchmark_reports: unique on benchmark_id
        """
        # Workflows collection indexes
        await self.db.workflows.create_index(
            [("workflow_id", 1), ("version", 1)],
            unique=True,
            name="unique_workflow_version",
        )
        logger.info("Created unique index on workflows(workflow_id, version)")

        # Runs collection indexes
        await self.db.runs.create_index(
            [("run_id", 1)],
            unique=True,
            name="unique_run_id",
        )
        await self.db.runs.create_index(
            [("benchmark_id", 1)],
            name="idx_benchmark_id",
        )
        await self.db.runs.create_index(
            [("case_set_id", 1), ("case_id", 1)],
            name="idx_case_set_case",
        )
        logger.info("Created indexes on runs collection")

        # Run reports collection indexes
        await self.db.run_reports.create_index(
            [("run_id", 1)],
            unique=True,
            name="unique_run_report",
        )
        await self.db.run_reports.create_index(
            [("benchmark_id", 1)],
            name="idx_run_report_benchmark",
        )
        await self.db.run_reports.create_index(
            [("case_id", 1)],
            name="idx_run_report_case",
        )
        logger.info("Created indexes on run_reports collection")

        # Benchmark reports collection indexes
        await self.db.benchmark_reports.create_index(
            [("benchmark_id", 1)],
            unique=True,
            name="unique_benchmark_report",
        )
        logger.info("Created unique index on benchmark_reports(benchmark_id)")

    # ==========================================================================
    # Workflow Operations
    # ==========================================================================

    async def create_workflow(self, workflow: WorkflowDefinition) -> None:
        """Create a new workflow definition. Raises DuplicateKeyError if duplicate."""
        doc = workflow.model_dump()
        try:
            await self.db.workflows.insert_one(doc)
            logger.info(
                "Created workflow",
                extra={
                    "workflow_id": workflow.workflow_id,
                    "version": workflow.version,
                    "status": workflow.status,
                },
            )
        except DuplicateKeyError:
            logger.warning(
                "Workflow already exists",
                extra={
                    "workflow_id": workflow.workflow_id,
                    "version": workflow.version,
                },
            )
            raise

    async def get_workflow(
        self, workflow_id: str, version: str | None = None
    ) -> WorkflowDefinition | None:
        """Retrieve a workflow definition. Returns None if not found.

        If version is None, returns the latest published version."""
        if version:
            doc = await self.db.workflows.find_one({"workflow_id": workflow_id, "version": version})
        else:
            # Get latest published version
            doc = await self.db.workflows.find_one(
                {"workflow_id": workflow_id, "status": "published"},
                sort=[("version", -1)],
            )

        if doc is None:
            return None

        return WorkflowDefinition.model_validate(doc)

    async def publish_workflow(self, workflow_id: str, version: str) -> None:
        """Publish a workflow version, making it immutable.

        Raises WorkflowNotFoundError if the workflow doesn't exist."""
        from datetime import datetime

        result = await self.db.workflows.update_one(
            {"workflow_id": workflow_id, "version": version, "status": "draft"},
            {
                "$set": {
                    "status": "published",
                    "published_at": datetime.now(UTC).isoformat(),
                }
            },
        )

        if result.matched_count == 0:
            # Check if it already exists as published
            existing = await self.db.workflows.find_one(
                {"workflow_id": workflow_id, "version": version}
            )
            if existing is None:
                raise WorkflowNotFoundError(f"Workflow {workflow_id} version {version} not found")
            if existing.get("status") == "published":
                logger.info(
                    "Workflow already published",
                    extra={"workflow_id": workflow_id, "version": version},
                )
                return

        logger.info(
            "Published workflow",
            extra={"workflow_id": workflow_id, "version": version},
        )

    async def list_workflows(self) -> list[WorkflowDefinition]:
        """List all workflow definitions."""
        cursor = self.db.workflows.find()
        workflows = []
        async for doc in cursor:
            workflows.append(WorkflowDefinition.model_validate(doc))
        return workflows

    async def _check_workflow_mutable(self, workflow_id: str, version: str) -> bool:
        """Check if a workflow is mutable (draft). Raises WorkflowNotFoundError if missing."""
        doc = await self.db.workflows.find_one({"workflow_id": workflow_id, "version": version})
        if doc is None:
            raise WorkflowNotFoundError(f"Workflow {workflow_id} version {version} not found")
        status: object = doc.get("status")
        return status != "published"

    async def _enforce_immutability(self, workflow_id: str, version: str) -> None:
        """Raise ImmutableWorkflowError if the workflow is published."""
        is_mutable = await self._check_workflow_mutable(workflow_id, version)
        if not is_mutable:
            raise ImmutableWorkflowError(
                f"Workflow {workflow_id} version {version} is published and immutable"
            )

    # ==========================================================================
    # Run Operations
    # ==========================================================================

    async def create_run(self, run: EvaluationRun) -> None:
        """Create a new evaluation run. Raises DuplicateKeyError if duplicate."""
        doc = run.model_dump()
        try:
            await self.db.runs.insert_one(doc)
            logger.info(
                "Created run",
                extra={
                    "run_id": run.run_id,
                    "benchmark_id": run.benchmark_id,
                    "agent_id": run.agent_id,
                    "case_id": run.case_id,
                },
            )
        except DuplicateKeyError:
            logger.warning("Run already exists", extra={"run_id": run.run_id})
            raise

    async def get_run(self, run_id: str) -> EvaluationRun | None:
        """Retrieve an evaluation run by ID. Returns None if not found."""
        doc = await self.db.runs.find_one({"run_id": run_id})
        if doc is None:
            return None
        return EvaluationRun.model_validate(doc)

    async def update_run_state(
        self,
        run_id: str,
        state: RunState,
        current_step: int | None = None,
    ) -> None:
        """Update run state. Raises RunNotFoundError if the run doesn't exist."""
        from datetime import datetime

        update_doc: dict[str, Any] = {
            "state": state.value if isinstance(state, RunState) else state
        }

        if current_step is not None:
            update_doc["current_step"] = current_step

        if state in (RunState.COMPLETED, RunState.FAILED, RunState.TIMED_OUT):
            update_doc["completed_at"] = datetime.now(UTC).isoformat()

        result = await self.db.runs.update_one(
            {"run_id": run_id},
            {"$set": update_doc},
        )

        if result.matched_count == 0:
            raise RunNotFoundError(f"Run {run_id} not found")

        logger.info(
            "Updated run state",
            extra={
                "run_id": run_id,
                "state": state.value if isinstance(state, RunState) else state,
                "current_step": current_step,
            },
        )

    async def list_runs(
        self,
        benchmark_id: str | None = None,
        case_set_id: str | None = None,
    ) -> list[EvaluationRun]:
        """List evaluation runs, optionally filtered by benchmark_id or case_set_id."""
        query: dict[str, Any] = {}
        if benchmark_id:
            query["benchmark_id"] = benchmark_id
        if case_set_id:
            query["case_set_id"] = case_set_id

        cursor = self.db.runs.find(query)
        runs = []
        async for doc in cursor:
            runs.append(EvaluationRun.model_validate(doc))
        return runs

    # ==========================================================================
    # Run Report Operations
    # ==========================================================================

    async def create_run_report(self, report: RunReport) -> None:
        """Create a new run report. Raises DuplicateKeyError if duplicate."""
        doc = report.model_dump()
        try:
            await self.db.run_reports.insert_one(doc)
            logger.info(
                "Created run report",
                extra={
                    "run_id": report.run_id,
                    "benchmark_id": report.benchmark_id,
                    "total_score": report.total_score,
                },
            )
        except DuplicateKeyError:
            logger.warning(
                "Run report already exists",
                extra={"run_id": report.run_id},
            )
            raise

    async def get_run_report(self, run_id: str) -> RunReport | None:
        """Retrieve a run report by run_id. Returns None if not found."""
        doc = await self.db.run_reports.find_one({"run_id": run_id})
        if doc is None:
            return None
        return RunReport.model_validate(doc)

    # ==========================================================================
    # Benchmark Report Operations
    # ==========================================================================

    async def create_benchmark_report(self, report: BenchmarkReport) -> None:
        """Create a new benchmark report. Raises DuplicateKeyError if duplicate."""
        doc = report.model_dump()
        try:
            await self.db.benchmark_reports.insert_one(doc)
            logger.info(
                "Created benchmark report",
                extra={
                    "benchmark_id": report.benchmark_id,
                    "case_count": report.case_count,
                    "agent_count": len(report.agents),
                },
            )
        except DuplicateKeyError:
            logger.warning(
                "Benchmark report already exists",
                extra={"benchmark_id": report.benchmark_id},
            )
            raise

    async def get_benchmark_report(self, benchmark_id: str) -> BenchmarkReport | None:
        """Retrieve a benchmark report by benchmark_id. Returns None if not found."""
        doc = await self.db.benchmark_reports.find_one({"benchmark_id": benchmark_id})
        if doc is None:
            return None
        return BenchmarkReport.model_validate(doc)

    async def close(self) -> None:
        """Close the MongoDB client connection."""
        self.client.close()
        logger.info("Closed MongoDB connection")
