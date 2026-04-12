"""Redis storage layer for AgentBench FSM and tracking."""

import logging

import redis.asyncio as redis

from agentbench.models.run import RunState

logger = logging.getLogger(__name__)


class RedisStorage:
    """Redis storage for run FSM state and benchmark tracking."""

    def __init__(
        self, redis_client: redis.Redis | None = None, redis_url: str = "redis://localhost:6379"
    ):
        self._client = redis_client
        self._redis_url = redis_url

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    # Run FSM Methods
    async def set_run_state(self, run_id: str, state: RunState, ttl: int = 3600) -> None:
        key = f"run:{run_id}:state"
        client = await self._get_client()
        await client.setex(key, ttl, state.value)
        logger.debug(f"Set run state: {run_id} -> {state.value}")

    async def get_run_state(self, run_id: str) -> RunState | None:
        key = f"run:{run_id}:state"
        client = await self._get_client()
        value = await client.get(key)
        if value:
            return RunState(value)
        return None

    # Step Tracking
    async def set_current_step(self, run_id: str, step_index: int, ttl: int = 3600) -> None:
        key = f"run:{run_id}:step"
        client = await self._get_client()
        await client.setex(key, ttl, str(step_index))
        logger.debug(f"Set current step: {run_id} -> {step_index}")

    async def get_current_step(self, run_id: str) -> int | None:
        key = f"run:{run_id}:step"
        client = await self._get_client()
        value = await client.get(key)
        if value:
            return int(value)
        return None

    # Benchmark Tracking
    async def add_run_to_benchmark(self, benchmark_id: str, run_id: str, ttl: int = 7200) -> None:
        key = f"benchmark:{benchmark_id}:runs"
        client = await self._get_client()
        await client.sadd(key, run_id)
        await client.expire(key, ttl)
        logger.debug(f"Added run to benchmark: {benchmark_id} -> {run_id}")

    async def get_benchmark_runs(self, benchmark_id: str) -> set[str]:
        key = f"benchmark:{benchmark_id}:runs"
        client = await self._get_client()
        members = await client.smembers(key)
        return set(members)

    async def mark_run_completed(self, benchmark_id: str, run_id: str, ttl: int = 7200) -> None:
        key = f"benchmark:{benchmark_id}:completed"
        client = await self._get_client()
        await client.sadd(key, run_id)
        await client.expire(key, ttl)
        logger.debug(f"Marked run completed: {benchmark_id} -> {run_id}")

    async def get_benchmark_completed_runs(self, benchmark_id: str) -> set[str]:
        key = f"benchmark:{benchmark_id}:completed"
        client = await self._get_client()
        members = await client.smembers(key)
        return set(members)

    async def is_benchmark_complete(self, benchmark_id: str) -> bool:
        runs = await self.get_benchmark_runs(benchmark_id)
        completed = await self.get_benchmark_completed_runs(benchmark_id)
        if not runs:
            return False
        return runs == completed

    # Workflow Caching
    async def cache_workflow(
        self, workflow_id: str, version: str, workflow_data: dict, ttl: int = 86400
    ) -> None:
        key = f"workflow:{workflow_id}:{version}"
        client = await self._get_client()
        await client.hset(key, mapping={k: str(v) for k, v in workflow_data.items()})
        await client.expire(key, ttl)
        logger.debug(f"Cached workflow: {workflow_id}:{version}")

    async def get_cached_workflow(self, workflow_id: str, version: str) -> dict | None:
        key = f"workflow:{workflow_id}:{version}"
        client = await self._get_client()
        data = await client.hgetall(key)
        if data:
            return dict(data)
        return None
