"""Integration test for the full AgentBench pipeline.

⚠️  MANUAL-ONLY: These tests make REAL API calls to OpenAI and Anthropic.
   They cost money (~$0.50-1.00 per run) and are NEVER run in CI.

   To run locally:
   1. Ensure services are running: just start && just runtime && just api
   2. Set AGENTBENCH_INTEGRATION_TEST=1
   3. Run: uv run pytest tests/integration/test_pipeline.py -v

This test runs the complete benchmark workflow end-to-end using
real API keys. It validates:
- Benchmark can be started via API
- Raw I/O files are written
- Step scores are persisted
- Final benchmark report is generated
"""

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv

# Load .env from project root so API keys are available
load_dotenv(Path(__file__).parent.parent.parent / ".env")
PROJECT_ROOT = Path(__file__).parent.parent.parent
RAW_IO_DIR = PROJECT_ROOT / "data" / "raw_io"

# Skip all integration tests unless explicitly enabled
pytestmark = pytest.mark.skipif(
    os.environ.get("AGENTBENCH_INTEGRATION_TEST") != "1",
    reason="Integration tests disabled. Set AGENTBENCH_INTEGRATION_TEST=1 to enable.",
)


def _seed_database() -> None:
    """Seed database and assert success."""
    # Build seed command with auth URI from environment
    mongo_uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
    result = subprocess.run(
        ["agentbench", "seed", "--mongo-uri", mongo_uri],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, f"Seed failed: {result.stderr}"


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
    _seed_database()

    # Clean raw I/O from previous runs for accurate count
    if RAW_IO_DIR.exists():
        shutil.rmtree(RAW_IO_DIR)

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

    # Verify raw I/O files were written (MUST exist, not silently skipped)
    assert RAW_IO_DIR.exists(), f"Raw I/O directory not found: {RAW_IO_DIR}"
    run_dirs = [d for d in RAW_IO_DIR.iterdir() if d.is_dir()]
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
    _seed_database()

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
    max_wait = 300
    elapsed = 0

    while elapsed < max_wait:
        response = await api_client.get(f"/benchmarks/{benchmark_id}")
        assert response.status_code == 200
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
    _seed_database()

    # Create benchmark
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

    # Poll until benchmark completes (runs are created asynchronously)
    max_wait = 300
    elapsed = 0

    while elapsed < max_wait:
        poll_resp = await api_client.get(f"/benchmarks/{benchmark_id}")
        assert poll_resp.status_code == 200
        data = poll_resp.json()

        if data.get("status") != "in_progress":
            break

        await asyncio.sleep(5)
        elapsed += 5
    else:
        pytest.fail("Benchmark did not complete within timeout")

    # List runs
    response = await api_client.get(f"/benchmarks/{benchmark_id}/runs")
    assert response.status_code == 200

    runs = response.json()
    assert isinstance(runs, list)
    assert len(runs) > 0, "Expected at least one run after benchmark completion"

    # Each run should have required fields
    for run in runs:
        assert "run_id" in run
        assert "case_id" in run
        assert "agent_id" in run
        assert "state" in run
