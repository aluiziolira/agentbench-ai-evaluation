# AgentBench

Portfolio-level AI evaluation framework for PR review behavior.

## Overview

AgentBench is an event-driven evaluation framework that benchmarks AI agents on realistic PR review tasks using:
- Redis Streams for event streaming
- MongoDB for data persistence
- Async Python for high-performance orchestration

## Quick Start

### Prerequisites

- Python 3.11+
- UV package manager
- Docker & Docker Compose

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd agentbench

# Install dependencies with UV
uv sync

# Copy environment variables
cp .env.example .env
# Edit .env with your API keys

# Start infrastructure services
docker-compose up -d mongodb redis
```

### Running the CLI

```bash
# Activate the virtual environment
source .venv/bin/activate

# Run the CLI
agentbench --help
```

## Development

```bash
# Run tests
uv run pytest

# Run linting
uv run ruff check .
uv run ruff format .

# Run type checking
uv run mypy agentbench cli
```

## Architecture

See the project documentation for detailed architecture information.
