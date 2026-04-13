# AgentBench - bootstrap and runtime recipes
# Requires: Docker, uv, Python 3.12+

set dotenv-load := false

# Default: show available recipes
default:
    @just --list

# Sync dependencies (uv sync)
sync:
    uv sync

# Full init: sync deps + start infrastructure + seed
init: sync start
    @sleep 5
    @just seed

# Start infrastructure services (mongodb + redis)
start:
    docker compose up -d mongodb redis

# Stop infrastructure services
stop:
    docker compose down

# Restart infrastructure services
restart: stop start

# Show infrastructure status
status:
    docker compose ps

# Tail infrastructure logs
logs *args="--tail 50 -f":
    docker compose logs {{args}} mongodb redis

# Seed fixtures into MongoDB
seed:
    uv run python -m cli.main seed

# Start runtime (orchestrator + event bus)
runtime:
    uv run python -m agentbench.main

# Start API server
api:
    uv run python start_api.py

# Demo benchmark run
demo:
    uv run python -m cli.main run \
        --workflow wf_pr_review_v1 \
        --case-set pr_review_cases_v1 \
        --agents gpt-4o-mini --agents claude-haiku-4-5

# Clean runtime artifacts
clean:
    rm -rf .pytest_cache htmlcov .coverage coverage.xml

# ── Quality & Test Recipes ──────────────────────────────────

# Run all tests (unit + integration if gated)
test:
    uv run pytest -q

# Unit tests only (fast, no external deps)
test-unit:
    uv run pytest tests/unit -q

# Integration tests (loads .env if present; requires AGENTBENCH_INTEGRATION_TEST=1)
test-integration:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -f .env ]; then
        set -a
        . ./.env
        set +a
    fi
    if [ -z "${AGENTBENCH_INTEGRATION_TEST:-}" ]; then
        echo "ERROR: set AGENTBENCH_INTEGRATION_TEST=1 to run integration tests"
        exit 1
    fi
    uv run pytest tests/integration/test_pipeline.py -q

# Lint: ruff check + format check
lint:
    uv run ruff check .
    uv run ruff format --check .

# Format: apply ruff formatting
format:
    uv run ruff format .

# Typecheck: mypy strict
typecheck:
    uv run mypy .

# Coverage: unit tests with xml + html reports
coverage:
    uv run pytest tests/unit --cov=agentbench --cov=cli --cov-report=xml --cov-report=html

# CI PR gate: lint + typecheck + coverage (no integration)
ci-pr: lint typecheck coverage

# CI integration: MANUAL-ONLY local testing with real API calls
# ⚠️  Costs money (~$0.50-1.00 per run) - Never run in automated CI
test-manual-integration: sync start
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -f .env ]; then
        set -a
        . ./.env
        set +a
    fi
    echo "⚠️  WARNING: This will make real API calls costing ~$0.50-1.00"
    echo "Press Ctrl+C to cancel, or wait 3 seconds to continue..."
    sleep 3
    trap 'kill $(jobs -p) 2>/dev/null' EXIT
    uv run python -m agentbench.main > /tmp/runtime.log 2>&1 &
    uv run python start_api.py > /tmp/api.log 2>&1 &
    echo "Waiting for /health readiness..."
    for i in $$(seq 1 30); do
        if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
            echo "API ready after $$i attempts."
            break
        fi
        sleep 2
    done
    curl -sf http://localhost:8000/health > /dev/null 2>&1 || { echo "ERROR: API not ready after 60s"; cat /tmp/api.log; exit 1; }
    AGENTBENCH_INTEGRATION_TEST=1 uv run pytest tests/integration/test_pipeline.py -q
# Pre-commit hook: lint + format + typecheck + unit tests
precommit: lint format typecheck test-unit
