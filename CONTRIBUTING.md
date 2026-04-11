# Contributing to AgentBench

This guide covers local development setup and CI-parity workflows.

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12+ | Runtime and development |
| Docker Compose | v2 | Infrastructure services (MongoDB, Redis) |
| uv | latest | Python package management |
| just | latest | Task runner |

Install uv and just:

```bash
# macOS
brew install uv just

# Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to ~/.local/bin
```

## Local Setup

Clone and initialize the project:

```bash
git clone <repo-url> && cd agentbench

# Install dependencies (includes dev tools)
uv sync --dev

# Install pre-commit hooks
uv run pre-commit install

# Start infrastructure and seed fixtures
just init
```

The `just init` command:
1. Syncs Python dependencies
2. Starts MongoDB and Redis containers
3. Seeds benchmark fixtures into MongoDB

## Daily Workflow

Run these commands during development:

| Command | Purpose | Duration |
|---------|---------|----------|
| `just lint` | Check code style with ruff | ~1s |
| `just format` | Apply ruff formatting | ~1s |
| `just typecheck` | Run mypy type checking | ~5s |
| `just test-unit` | Run unit tests (fast, no external deps) | ~5s |
| `just coverage` | Unit tests with coverage reports | ~10s |

Run all quality checks in sequence:

```bash
just lint && just typecheck && just test-unit
```

## Integration Testing

Integration tests verify the full pipeline including LLM calls. These are **gated** and do not run on every PR.

**Requirements:**
- Docker Compose running (`just start`)
- Runtime service running (`just runtime`)
- API server running (`just api`)
- API keys in `.env` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`)
- Gate flag: `AGENTBENCH_INTEGRATION_TEST=1`

**Run integration tests:**

```bash
# Terminal 1: Start infrastructure
just start

# Terminal 2: Start runtime
just runtime

# Terminal 3: Start API
just api

# Terminal 4: Run gated integration tests
AGENTBENCH_INTEGRATION_TEST=1 just test-integration
```

Integration tests are intentionally separated from the daily workflow because they:
- Require running services (runtime + API)
- Make live LLM API calls (costs + latency)
- Take ~100 seconds to complete
- Need provider API keys configured

## Pre-Commit

Pre-commit hooks run automatically on `git commit`. To run manually:

```bash
just precommit
```

This executes: lint → format → typecheck → test-unit

## CI Parity

These commands match what runs in CI:

| Command | CI Equivalent | Purpose |
|---------|---------------|---------|
| `just ci-pr` | PR quality gate | Lint + typecheck + coverage (no integration) |
| `just ci-integration` | Integration workflow | Full stack test with gated integration |

**Before submitting a PR:**

```bash
just ci-pr
```

This runs the exact checks that CI will run on your pull request.

**Full integration validation (optional):**

```bash
just ci-integration
```

This command:
1. Syncs dependencies and starts infrastructure
2. Launches runtime and API as background processes
3. Polls `/health` endpoint until ready (up to 60s)
4. Runs gated integration tests
5. Cleans up background processes on exit

## Available Commands

List all just recipes:

```bash
just
```

Common infrastructure commands:

| Command | Purpose |
|---------|---------|
| `just start` | Start MongoDB and Redis containers |
| `just stop` | Stop infrastructure containers |
| `just restart` | Restart infrastructure |
| `just status` | Show container status |
| `just logs` | Tail infrastructure logs |
| `just seed` | Seed fixture data into MongoDB |
| `just runtime` | Start the event-driven runtime |
| `just api` | Start the API server |
| `just demo` | Run a sample benchmark comparison |

## Environment Setup

Copy the example environment file and add your API keys:

```bash
cp .env.example .env
```

Required for integration tests and demo runs:
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`

## Troubleshooting

**Issue:** `just init` fails with Docker errors  
**Fix:** Ensure Docker Desktop or Docker Engine is running and `docker compose` (v2) is available.

**Issue:** Unit tests pass but integration tests fail  
**Fix:** Verify all services are running (`just status`), API keys are set, and the gate flag is exported.

**Issue:** Pre-commit hooks fail on mypy  
**Fix:** Run `uv sync --dev` to ensure all type stubs are installed.

**Issue:** Coverage reports not generating  
**Fix:** The `just coverage` command outputs to `coverage.xml` and `htmlcov/`. Check these files exist after running.
