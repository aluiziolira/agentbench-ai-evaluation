# AgentBench - Professional Task Runner Configuration
# https://just.systems/man/en/
#
# Requirements:
#   - Docker & Docker Compose
#   - uv (https://docs.astral.sh/uv/)
#   - Python 3.12+
#   - just (https://just.systems)
#
# Quick Start:
#   just init          # Bootstrap everything
#   just dev           # Start all services + watch logs
#   just test          # Run full test suite
#
# See 'just --list' for all recipes

set dotenv-load := false
set shell := ["bash", "-euo", "pipefail", "-c"]

# ═════════════════════════════════════════════════════════════════════════════
# CONFIGURATION & CONSTANTS
# ═════════════════════════════════════════════════════════════════════════════

export PROJECT_NAME := "agentbench"
export COMPOSE_PROJECT_NAME := "agentbench"
export API_PORT := env("API_PORT", "8000")
export MONGO_PORT := "27017"
export REDIS_PORT := "6379"
export COVERAGE_THRESHOLD := "80"
export LOG_LEVEL := env("LOG_LEVEL", "INFO")

ci := env("CI", "false")
# ═════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS (prefixed with _)
# ═════════════════════════════════════════════════════════════════════════════

# Print formatted status message
[private]
_status message:
    @echo -e "\033[1;34m[{{PROJECT_NAME}}]\033[0m {{message}}"

# Print error and exit
[private]
_error message:
    @echo -e "\033[1;31m[ERROR]\033[0m {{message}}" >&2
    exit 1

# Verify required tools are available
[private]
_verify-tool tool:
    @command -v {{tool}} >/dev/null 2>&1 || { echo "ERROR: {{tool}} is required but not installed."; exit 1; }

# Wait for service with timeout and health check
[private]
_wait-for-service host port timeout_secs="30":
    @timeout={{timeout_secs}}; host={{host}}; port={{port}}; \\
    for i in $(seq 1 $timeout); do \\
        if nc -z $host $port 2>/dev/null; then \\
            echo "✓ $host:$port ready after ${i}s"; \\
            exit 0; \\
        fi; \\
        sleep 1; \\
    done; \\
    echo "ERROR: $host:$port not ready after ${timeout}s" >&2; \\
    exit 1

# ═════════════════════════════════════════════════════════════════════════════
# BOOTSTRAP & SETUP
# ═════════════════════════════════════════════════════════════════════════════

# Show available recipes with descriptions
[group('info')]
default:
    @just --list --unsorted

# Initialize development environment (install deps, start infra, seed data)
[group('setup')]
init: sync start
    @sleep 3
    @just _status "Seeding database..."
    @just seed
    @just _status "Environment ready! Run 'just dev' to start all services."

# Sync Python dependencies using uv
[group('setup')]
sync:
    @just _verify-tool uv
    @just _status "Syncing dependencies..."
    uv sync --frozen

# Validate environment configuration
[group('setup')]
validate-env:
    @just _status "Validating environment..."
    @if [ ! -f .env ]; then \
        just _error ".env file not found. Copy .env.example and configure."; \
    fi
    @# Check required env vars (non-destructive)
    @grep -E '^OPENAI_API_KEY=|^ANTHROPIC_API_KEY=' .env >/dev/null 2>&1 || \
        echo "⚠️  Warning: API keys not configured in .env"

# ═════════════════════════════════════════════════════════════════════════════
# INFRASTRUCTURE (Docker Compose)
# ═════════════════════════════════════════════════════════════════════════════

# Start infrastructure services (MongoDB + Redis)
[group('infra')]
start:
    @just _verify-tool docker
    @just _status "Starting infrastructure services..."
    docker compose up -d mongodb redis --wait
    @just _wait-for-service localhost {{MONGO_PORT}}
    @just _wait-for-service localhost {{REDIS_PORT}}
    @just _status "Infrastructure ready ✓"

# Stop all infrastructure services
[group('infra')]
stop:
    @just _status "Stopping infrastructure..."
    docker compose down --remove-orphans

# Restart infrastructure services
[group('infra')]
restart: stop start

# Show infrastructure service status
[group('infra')]
status:
    @docker compose ps

# View service logs (usage: just logs [service] [-f])
[group('infra')]
logs service="" *args="-f --tail=100":
    @if [ -z "{{service}}" ]; then \
        docker compose logs {{args}}; \
    else \
        docker compose logs {{args}} {{service}}; \
    fi

# Clean infrastructure volumes (⚠️ DESTRUCTIVE)
[group('infra')]
nuke:
    @echo -n "⚠️  This will DELETE all data volumes. Continue? [y/N] "
    @read -r response; [ "$response" = "y" ] || exit 1
    docker compose down -v --remove-orphans
    docker volume rm -f {{COMPOSE_PROJECT_NAME}}_mongodb_data {{COMPOSE_PROJECT_NAME}}_redis_data 2>/dev/null || true
    @just _status "Volumes destroyed"

# ═════════════════════════════════════════════════════════════════════════════
# APPLICATION SERVICES
# ═════════════════════════════════════════════════════════════════════════════

# Seed database with fixtures
[group('app')]
seed:
    @just _status "Seeding database..."
    uv run python -m cli.main seed

# Start runtime (orchestrator + event bus)
[group('app')]
runtime *args:
    @just _status "Starting runtime..."
    uv run python -m agentbench.main {{args}}

# Start API server
[group('app')]
api *args:
    @just _status "Starting API server on port {{API_PORT}}..."
    uv run python start_api.py {{args}}

# Start all services (background, logs to tmp)
[group('app')]
services-bg:
    @just _status "Starting services in background..."
    @mkdir -p /tmp/{{PROJECT_NAME}}
    @pkill -f "python -m agentbench.main" 2>/dev/null || true
    @pkill -f "python start_api.py" 2>/dev/null || true
    @sleep 1
    @just _status "Starting runtime..."
    @nohup uv run python -m agentbench.main > /tmp/{{PROJECT_NAME}}/runtime.log 2>&1 &
    @just _status "Starting API..."
    @nohup uv run python start_api.py > /tmp/{{PROJECT_NAME}}/api.log 2>&1 &
    @sleep 2
    @just _wait-for-service localhost {{API_PORT}} 30 || (just _error "API failed to start. Check /tmp/{{PROJECT_NAME}}/api.log"; exit 1)
    @just _status "Services running. Logs: /tmp/{{PROJECT_NAME}}/"

# Stop background services
[group('app')]
services-stop:
    @just _status "Stopping background services..."
    @pkill -f "python -m agentbench.main" 2>/dev/null || true
    @pkill -f "python start_api.py" 2>/dev/null || true
    @just _status "Services stopped"

# Development mode: start everything + watch logs
[group('dev')]
dev: start services-bg
    @just _status "Development mode active. Press Ctrl+C to stop."
    @trap 'just services-stop; exit 0' INT
    @tail -f /tmp/{{PROJECT_NAME}}/*.log 2>/dev/null || echo "No logs yet... waiting..."
    @sleep infinity

# Health check all services
[group('dev')]
health:
    @just _status "Checking service health..."
    @echo "  MongoDB (port {{MONGO_PORT}}): $(nc -z localhost {{MONGO_PORT}} 2>/dev/null && echo "✓ UP" || echo "✗ DOWN")"
    @echo "  Redis (port {{REDIS_PORT}}): $(nc -z localhost {{REDIS_PORT}} 2>/dev/null && echo "✓ UP" || echo "✗ DOWN")"
    @echo "  API (port {{API_PORT}}): $(curl -sf http://localhost:{{API_PORT}}/health >/dev/null 2>&1 && echo "✓ UP" || echo "✗ DOWN")"

# Interactive development shell with env loaded
[group('dev')]
shell:
    @just _status "Loading environment..."
    @if [ -f .env ]; then export $(grep -v '^#' .env | xargs); fi
    @exec $SHELL

# ═════════════════════════════════════════════════════════════════════════════
# TESTING & QUALITY
# ═════════════════════════════════════════════════════════════════════════════

# Base pytest command (private, used by other test recipes)
[private]
_pytest *args:
    uv run pytest {{args}}

# Run all tests with coverage
[group('quality')]
test *args:
    @just _status "Running tests..."
    just _pytest {{args}}

# Run unit tests only (fast, no external deps)
[group('quality')]
test-unit:
    @just _status "Running unit tests..."
    just _pytest tests/unit -q -x

# Run integration tests (requires AGENTBENCH_INTEGRATION_TEST=1)
[group('quality')]
test-integration *selector="tests/integration/test_pipeline.py":
    @if [ -z "${AGENTBENCH_INTEGRATION_TEST:-}" ]; then \
        just _error "Set AGENTBENCH_INTEGRATION_TEST=1 to run integration tests"; \
    fi
    @if [ "{{ci}}" != "true" ]; then \
        just _status "Starting infrastructure for local run..."; \
        just start; \
    fi
    @just _status "Running integration tests..."
    just _pytest {{selector}} -v

# Lint check (ruff)
[group('quality')]
lint:
    @just _status "Running linter..."
    uv run ruff check .

# Check formatting (ruff)
[group('quality')]
lint-format:
    uv run ruff format --check .

# Apply formatting (ruff)
[group('quality')]
format:
    @just _status "Applying formatting..."
    uv run ruff format .

# Type check (mypy)
[group('quality')]
typecheck:
    @just _status "Running type checker..."
    uv run mypy .

# Generate coverage report with threshold
[group('quality')]
coverage:
    @just _status "Running tests with coverage..."
    uv run pytest tests/unit --cov=agentbench --cov=cli --cov-report=xml --cov-report=html --cov-fail-under={{COVERAGE_THRESHOLD}}
    @just _status "Coverage report generated: htmlcov/index.html"

# Run all quality checks (lint + typecheck + coverage)
[group('quality')]
check: lint lint-format typecheck test-unit
    @just _status "All quality checks passed ✓"

# Security audit (bandit + safety)
[group('quality')]
audit:
    @just _status "Running security audit..."
    @# Check for secrets in codebase
    @if command -v gitleaks >/dev/null 2>&1; then \
        gitleaks detect --source . --verbose; \
    else \
        echo "  ⚠️  gitleaks not installed, skipping secret scan"; \
    fi
    @# Static security analysis
    @if uv run --quiet python -c "import bandit" 2>/dev/null; then \
        uv run bandit -r agentbench cli -f json -o bandit-report.json || true; \
        uv run bandit -r agentbench cli; \
    else \
        echo "  ℹ️  bandit not installed, install with: uv add --dev bandit"; \
    fi

# ═════════════════════════════════════════════════════════════════════════════
# CI/CD & RELEASE
# ═════════════════════════════════════════════════════════════════════════════

# CI PR gate: fast checks for CI
[group('ci')]
ci-pr:
    @just _status "Running CI PR gate..."
    just lint
    just lint-format
    just typecheck
    just coverage

# CI test gate: unit tests only (fast)
[group('ci')]
ci-test: test-unit
    @just _status "CI test gate passed ✓"


# CI build: full Docker build verification
[group('ci')]
ci-build:
    @just _status "Building Docker image..."
    docker build -t {{PROJECT_NAME}}:local .
    @just _status "Docker build successful ✓"

# Manual integration test with cost warning
[group('ci')]
test-manual: sync start services-bg
    @#!/usr/bin/env bash
    set -euo pipefail
    if [ -f .env ]; then set -a; . ./.env; set +a; fi
    echo "⚠️ WARNING: This will make real API calls costing ~$0.50-1.00"
    echo "Press Ctrl+C to cancel, or wait 3 seconds to continue..."
    sleep 3

    just _status "Running manual integration tests..."
    AGENTBENCH_INTEGRATION_TEST=1 uv run pytest tests/integration/test_pipeline.py -v

    just services-stop
# Run demo benchmark
[group('demo')]
demo:
    @just _status "Running demo benchmark..."
    uv run python -m cli.main run \
        --workflow wf_pr_review_v1 \
        --case-set pr_review_cases_v1 \
        --agents gpt-4o-mini --agents claude-haiku-4-5

# ═════════════════════════════════════════════════════════════════════════════
# MAINTENANCE
# ═════════════════════════════════════════════════════════════════════════════

# Clean build artifacts and caches
[group('maint')]
clean:
    @just _status "Cleaning artifacts..."
    rm -rf .pytest_cache htmlcov .coverage coverage.xml bandit-report.json
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    @just _status "Clean complete"

# Deep clean: remove all generated files + virtualenv
[group('maint')]
clean-all: clean
    @just _status "Deep cleaning..."
    rm -rf .venv .mypy_cache .ruff_cache
    @just _status "Virtual environment removed. Run 'just init' to rebuild."

# Update dependencies
[group('maint')]
update:
    @just _status "Updating dependencies..."
    uv lock --upgrade
    just sync

# Show project info
[group('info')]
info:
    @echo "=== AgentBench ==="
    @echo "Python: $(python3 --version 2>/dev/null || echo 'N/A')"
    @echo "UV: $(uv --version 2>/dev/null || echo 'N/A')"
    @echo "Docker: $(docker --version 2>/dev/null | cut -d' ' -f3 | tr -d ',')"
    @echo "Services: MongoDB(27017) Redis(6379) API(8000)"
    @just health
