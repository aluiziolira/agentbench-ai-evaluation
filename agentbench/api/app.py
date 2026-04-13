"""FastAPI application for AgentBench API."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agentbench.api.routers import benchmarks, workflows
from agentbench.events.bus import EventBus
from agentbench.storage.mongo import MongoStorage
from agentbench.storage.redis_client import RedisStorage


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler."""
    # Initialize storage with environment variables
    mongo_uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
    app.state.mongo = MongoStorage(mongo_uri, "agentbench")
    await app.state.mongo.setup_indexes()

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    app.state.redis = RedisStorage(redis_url=redis_url)

    app.state.event_bus = EventBus(redis_client=await app.state.redis._get_client())

    yield

    # Cleanup
    pass


app = FastAPI(
    title="AgentBench API",
    description="AI Agent Evaluation Framework",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(benchmarks.router, prefix="/benchmarks", tags=["benchmarks"])
app.include_router(workflows.router, prefix="/workflows", tags=["workflows"])


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}
