"""FastAPI application for AgentBench API."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from agentbench.api.routers import benchmarks, workflows
from agentbench.events.bus import EventBus
from agentbench.storage.mongo import MongoStorage
from agentbench.storage.redis_client import RedisStorage


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Initialize storage
    app.state.mongo = MongoStorage("mongodb://localhost:27017", "agentbench")
    await app.state.mongo.setup_indexes()

    app.state.redis = RedisStorage(redis_url="redis://localhost:6379")

    app.state.event_bus = EventBus(redis=app.state.redis._client)

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
async def health_check():
    return {"status": "healthy"}
