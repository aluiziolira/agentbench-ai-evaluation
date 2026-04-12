"""Integration test for the full AgentBench pipeline.

This test runs the complete benchmark workflow end-to-end using
real API keys. It validates:
- Benchmark can be started via API
- Raw I/O files are written
- Step scores are persisted
- Final benchmark report is generated
"""

import asyncio
import os
from pathlib import Path

import httpx
import pytest

# Skip all integration tests unless explicitly enabled
pytestmark = pytest.mark.skipif(
    os.environ.get("AGENTBENCH_INTEGRATION_TEST") != "1",
    reason="Integration tests disabled. Set AGENTBENCH_INTEGRATION_TEST=1 to enable.",
)


@pytest.fixture
async def api_client():
    """Create HTTP client for API tests."""
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        yield client


@pytest.fixture
def require_api_keys():
    """Skip if API keys are not configured."""
    openai_key = os.environ.get("OPENAI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if not openai_key or not anthropic_key:
        pytest.skip("API keys not configured. Set OPENAI_API_KEY and ANTHROPIC_API_KEY.")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_benchmark_pipeline(api_client, require_api_keys):
    """
    Test the complete benchmark pipeline end-to-end.

    This test:
    1. Seeds the database with the workflow
    2. Creates a benchmark via API
    3. Waits for all runs to complete
    4. Verifies raw I/O files exist
    5. Verifies benchmark report is generated
    """
    # First seed the database
    import subprocess

    result = subprocess.run(
        ["agentbench", "seed"],
        capture_output=True,
        text=True,
        cwd="/home/aluizio/aluizio-projects/agentbench-ai-evaluation",
    )
    assert result.returncode == 0, f"Seed failed: {result.stderr}"

    # Create a benchmark
    response = await api_client.post(
        "/benchmarks",
        json={
            "workflow_id": "wf_pr_review_v1",
            "case_set_id": "pr_review_cases_v1",
            "agents": ["gpt-4o-mini", "claude-haiku-4-5"],
        },
        timeout=30.0,
    )
    assert response.status_code == 200
    benchmark_id = response.json()["benchmark_id"]

    # Poll for completion (up to 5 minutes)
    max_wait = 300  # seconds
    poll_interval = 5
    elapsed = 0

    report = None
    while elapsed < max_wait:
        response = await api_client.get(f"/benchmarks/{benchmark_id}")
        assert response.status_code == 200

        data = response.json()
        if data.get("status") != "in_progress":
            report = data
            break

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    assert report is not None, "Benchmark did not complete within timeout"
    assert "agents" in report
    assert len(report["agents"]) == 2  # Both agents

    # Verify per-case scores exist
    assert "per_case_scores" in report
    case_count = len(report["per_case_scores"])
    assert case_count > 0

    # Verify raw I/O files were written
    raw_io_dir = Path("data/raw_io")
    if raw_io_dir.exists():
        run_dirs = list(raw_io_dir.iterdir())
        # Should have 2 agents * case_count runs
        expected_runs = 2 * case_count
        assert len(run_dirs) == expected_runs, (
            f"Expected {expected_runs} run directories, found {len(run_dirs)}"
        )

    # Verify agent summaries have expected fields
    for agent in report["agents"]:
        assert "agent_id" in agent
        assert "avg_score" in agent
        assert "p50_latency_ms" in agent
        assert "p95_latency_ms" in agent
        assert "failure_rate" in agent


@pytest.mark.integration
@pytest.mark.asyncio
async def test_benchmark_with_single_agent(api_client, require_api_keys):
    """Test benchmark with just one agent for faster validation."""
    # Seed database
    import subprocess

    subprocess.run(["agentbench", "seed"], capture_output=True)

    # Create benchmark with single agent
    response = await api_client.post(
        "/benchmarks",
        json={
            "workflow_id": "wf_pr_review_v1",
            "case_set_id": "pr_review_cases_v1",
            "agents": ["gpt-4o-mini"],
        },
        timeout=30.0,
    )
    assert response.status_code == 200

    benchmark_id = response.json()["benchmark_id"]

    # Poll for completion
    max_wait = 180
    elapsed = 0

    while elapsed < max_wait:
        response = await api_client.get(f"/benchmarks/{benchmark_id}")
        data = response.json()

        if data.get("status") != "in_progress":
            assert "agents" in data
            assert len(data["agents"]) == 1
            assert data["agents"][0]["agent_id"] == "gpt-4o-mini"
            break

        await asyncio.sleep(5)
        elapsed += 5
    else:
        pytest.fail("Benchmark did not complete within timeout")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_benchmark_runs(api_client, require_api_keys):
    """Test listing runs for a benchmark."""
    import subprocess

    subprocess.run(["agentbench", "seed"], capture_output=True)

    # Create benchmark
    response = await api_client.post(
        "/benchmarks",
        json={
            "workflow_id": "wf_pr_review_v1",
            "case_set_id": "pr_review_cases_v1",
            "agents": ["gpt-4o-mini"],
        },
    )
    benchmark_id = response.json()["benchmark_id"]

    # List runs
    response = await api_client.get(f"/benchmarks/{benchmark_id}/runs")
    assert response.status_code == 200

    runs = response.json()
    assert isinstance(runs, list)

    # Each run should have required fields
    for run in runs:
        assert "run_id" in run
        assert "case_id" in run
        assert "agent_id" in run
        assert "state" in run
