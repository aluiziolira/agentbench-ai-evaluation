"""Benchmark API endpoints."""

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentbench.models import EVALUATION_RUN_REQUESTED, BenchmarkReport, EventEnvelope

router = APIRouter()


class CreateBenchmarkRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    workflow_id: str = Field(..., min_length=1)
    case_set_id: str = Field(..., min_length=1)
    agents: list[str] = Field(..., min_length=1)

    @field_validator("agents", mode="after")
    @classmethod
    def validate_agents_not_empty(cls, v: list[str]) -> list[str]:
        for agent in v:
            if not agent:
                raise ValueError("Agent identifiers cannot be empty")
        return v


class BenchmarkResponse(BaseModel):
    benchmark_id: str
    status: str


@router.post("", response_model=BenchmarkResponse)
async def create_benchmark(
    request: CreateBenchmarkRequest,
    req: Request,
) -> BenchmarkResponse:
    """Trigger a new benchmark run."""

    benchmark_id = str(uuid.uuid4())

    # Get dependencies from app state
    mongo = req.app.state.mongo
    event_bus = req.app.state.event_bus

    # Validate workflow exists
    workflow = await mongo.get_workflow(request.workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {request.workflow_id}")

    # Publish benchmark requested event
    await event_bus.publish(
        "stream:eval-runs",
        EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=EVALUATION_RUN_REQUESTED,
            timestamp=datetime.now(UTC).isoformat(),
            correlation_id=benchmark_id,
            payload={
                "benchmark_id": benchmark_id,
                "workflow_id": request.workflow_id,
                "case_set_id": request.case_set_id,
                "agents": request.agents,
            },
        ),
    )

    return BenchmarkResponse(benchmark_id=benchmark_id, status="started")


@router.get("/{benchmark_id}")
async def get_benchmark(benchmark_id: str, req: Request) -> dict[str, Any] | BenchmarkReport:
    """Get benchmark report (202 if in progress)."""
    mongo = req.app.state.mongo
    redis = req.app.state.redis

    # Check if complete
    is_complete = await redis.is_benchmark_complete(benchmark_id)

    if not is_complete:
        return {"benchmark_id": benchmark_id, "status": "in_progress"}

    # Get report
    report = await mongo.get_benchmark_report(benchmark_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Benchmark not found: {benchmark_id}")

    return cast(BenchmarkReport, report)


@router.get("/{benchmark_id}/runs")
async def list_benchmark_runs(benchmark_id: str, req: Request) -> list[dict[str, Any]]:
    """List run summaries for a benchmark."""
    mongo = req.app.state.mongo

    runs = await mongo.list_runs(benchmark_id=benchmark_id)

    return [
        {
            "run_id": r.run_id,
            "case_id": r.case_id,
            "agent_id": r.agent_id,
            "state": r.state.value,
        }
        for r in runs
    ]
