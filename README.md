# AgentBench

A minimal AI agent evaluation framework for PR review behavior, built with event-driven architecture.

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What is AgentBench?

AgentBench evaluates how well AI agents perform as code reviewers. It runs agents against seeded PR review cases, scores their findings, and generates comparative benchmark reports.

**Key Features:**
- **Event-Driven Architecture**: Async services communicating via Redis Streams
- **Deterministic Scoring**: Finding match strategy for reproducible results
- **Multi-Agent Support**: Compare GPT-4o-mini, Claude Haiku, and other agents
- **Re-scoring Demo**: Re-judge outputs without re-invoking agents
- **Raw I/O Capture**: Complete request/response storage for analysis

## Architecture

### Event-Driven Design

AgentBench uses a single-process, multi-async-task architecture with clean separation of concerns:

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   CLI/API   │────▶│  Orchestrator│────▶│   Redis     │
└─────────────┘     │              │     │   Streams   │
                    └──────────────┘     └──────┬──────┘
                                                │
           ┌─────────────────────────────────────┼─────┐
           │                                     │     │
           ▼                                     ▼     ▼
    ┌────────────┐                      ┌───────────┐ ┌──────────┐
    │ Dispatcher │                      │  Scoring  │ │Aggregator│
    │            │                      │  Engine   │ │          │
    └────────────┘                      └───────────┘ └──────────┘
           │                                     │          │
           ▼                                     ▼          ▼
    ┌────────────┐                      ┌───────────┐ ┌──────────┐
    │  OpenAI/   │                      │  Finding  │ │ MongoDB  │
    │ Anthropic  │                      │  Match /  │ │ Reports  │
    │            │                      │  LLM Judge│ │          │
    └────────────┘                      └───────────┘ └──────────┘
           │
           ▼
    ┌────────────┐
    │ Raw I/O    │
    │ Storage    │
    └────────────┘
```

**Why Event-Driven?**

This design demonstrates production-grade patterns while staying minimal:

| Component | Simplified Version | Production Analogue |
|-----------|-------------------|---------------------|
| Redis Streams | Single Redis instance | Kafka / RabbitMQ |
| MongoDB | Single node | MongoDB Atlas / replicaset |
| Object Storage | Local filesystem | S3 / GCS |
| Single Process | Asyncio tasks | Kubernetes / ECS |
| In-memory scoring | Pydantic models | Dedicated scoring service |

### Data Flow

1. **Benchmark Creation**: CLI/API creates benchmark → Orchestrator expands to runs
2. **Step Dispatch**: Orchestrator emits `workflow.step.dispatched` → Dispatcher invokes agent
3. **Agent Invocation**: Adapter calls OpenAI/Anthropic API → Raw I/O persisted
4. **Scoring**: `agent.response.received` → Scoring Engine computes score → `step.scored`
5. **Progression**: Orchestrator receives `step.scored` → Dispatches next step
6. **Completion**: All steps complete → Aggregator generates `BenchmarkReport`

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose
- OpenAI API key
- Anthropic API key

### 5-Minute Local Run

```bash
# Clone and enter directory
git clone <repo-url>
cd agentbench

# Install dependencies
pip install uv
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your API keys:
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...

# Start infrastructure
docker-compose up -d mongodb redis

# Seed database
source .env
uv run python -m cli.main seed

# Start services (in separate terminals)
source .env && uv run python -m agentbench.main
source .env && uv run python start_api.py

# Run benchmark
uv run python -m cli.main run \
  --workflow wf_pr_review_v1 \
  --case-set pr_review_cases_v1 \
  --agents gpt-4o-mini --agents claude-haiku-4-5

# Check report (in another terminal)
uv run python -m cli.main report {benchmark_id} --watch
```

## Benchmark Results

### Agent Performance Comparison

Sample run on 8 PR review cases:

| Agent | Avg Score | P50 Latency | P95 Latency | Failure Rate |
|-------|-----------|-------------|-------------|--------------|
| **claude-haiku-4-5** | 0.788 | 4,036ms | 6,785ms | 0.0% |
| **gpt-4o-mini** | 0.695 | 7,750ms | 11,881ms | 0.0% |

**Key Observations:**
- Claude Haiku achieved 13% higher average scores
- Claude Haiku was 2× faster (P50 latency)
- Both agents had 100% API success rate
- Scores from `s2_review_summary` LLM-judged step

### Per-Case Breakdown

| Case | Claude Haiku | GPT-4o-mini | Topic |
|------|--------------|-------------|-------|
| pr_001_missing_auth_check | 0.72 | 0.72 | Auth/Security |
| pr_002_missing_test_coverage | 0.82 | 0.72 | Testing |
| pr_003_missing_null_guard | 0.82 | 0.62 | Defensive Programming |
| pr_004_contract_breaking_change | 0.78 | 0.62 | API Compatibility |
| pr_005_missing_error_handling | 0.78 | 0.72 | Error Handling |
| pr_006_state_consistency_bug | 0.82 | 0.72 | Caching/State |
| pr_007_missing_validation | 0.78 | 0.72 | Input Validation |
| pr_008_performance_regression | 0.78 | 0.72 | Database/N+1 |

## Sample Case Walkthrough

### Case: PR-002 Missing Test Coverage

**Ticket:**
```markdown
# PR-002: Implement order discount calculator

Add a new `DiscountCalculator` service that handles various discount 
rules for orders, including percentage discounts, fixed amount discounts, 
and tiered discounts based on order value.
```

**Diff Excerpt:**
```python
# app/services/discount.py (88 lines added)
def calculate_discount(order, discount_code):
    # Implementation without tests
    if discount_code.type == "percentage":
        return order.total * (discount_code.value / 100)
    elif discount_code.type == "fixed":
        return discount_code.value
    # ... more logic
```

**Ground Truth Expected Finding:**
- **Issue**: Missing unit tests for discount calculations
- **Severity**: High
- **File**: `app/services/discount.py`
- **Line span**: 1-88

**Claude Haiku Response (s1_findings):**
```json
{
  "findings": [
    {
      "canonical_label": "missing_input_validation",
      "severity": "high",
      "file_path": "app/api/admin.py",
      "title": "Missing input validation for date range and status filters",
      "why_it_matters": "Without validation, malformed date inputs could cause crashes or SQL injection vulnerabilities.",
      "suggested_test": "Test with invalid date formats, null values, extremely large date ranges."
    }
  ]
}
```

**GPT-4o-mini Response (s1_findings):**
```json
{
  "findings": [
    {
      "canonical_label": "MISSING_TESTS",
      "severity": "high", 
      "file_path": "app/services/discount.py",
      "title": "Missing unit tests for discount calculations",
      "why_it_matters": "Without unit tests, there is no assurance that calculations work correctly.",
      "suggested_test": "Add unit tests for each type of discount and their combinations."
    }
  ]
}
```

**Review Summary (Claude Haiku s2_review_summary):**
> The implementation is missing comprehensive unit tests for the discount 
> calculation logic, particularly around edge cases for tiered discounts and 
> discount code validation. The service lacks input validation on the 
> `calculate_discount` function which could lead to runtime errors with 
> malformed discount codes. Add thorough test coverage including edge cases 
> for percentage calculations (e.g., 0%, 100%), invalid discount codes, and 
> boundary conditions for tiered discount thresholds before merging.

## Re-Scoring Demo

AgentBench supports re-scoring stored outputs without re-invoking agents:

```bash
# Re-score a summary with a different rubric
uv run python -m cli.main rescore \
  --run-id {run_id} \
  --step s2_review_summary \
  --strategy llm_judge \
  --rubric "Prioritize production risk above all else"
```

**Why This Matters:**
- Deterministic `finding_match` scores remain stable
- LLM-judged scores change when rubric changes
- Enables experimentation with scoring criteria
- No additional API costs for re-scoring

## Why Seeded Fixtures?

AgentBench uses committed, static PR review cases instead of live GitHub/Jira ingestion:

| Seeded Fixtures | Live Ingestion |
|-----------------|----------------|
| ✅ Reproducible | ❌ Non-deterministic |
| ✅ Stable scoring | ❌ Score drift over time |
| ✅ No API rate limits | ❌ Rate limited |
| ✅ Works offline | ❌ Requires connectivity |
| ✅ No auth complexity | ❌ OAuth/App setup |
| ✅ Clear demo assets | ❌ Privacy concerns |

## Project Structure

```
agentbench/
├── agentbench/           # Core framework
│   ├── cases/           # Case loader and models
│   ├── dispatcher/      # Agent adapters and dispatch
│   ├── events/          # Event bus and types
│   ├── orchestrator/    # Run orchestration
│   ├── scoring/         # Scoring strategies
│   ├── aggregator/      # Report generation
│   └── api/             # REST API
├── cli/                 # Command-line interface
├── fixtures/            # Seeded PR review cases
│   └── pr_review/
│       ├── manifest.json
│       └── cases/
├── workflows/           # Workflow definitions
└── tests/               # Unit and integration tests
```

## Testing

```bash
# Run all unit tests
uv run pytest tests/unit/ -q

# Run with coverage
uv run pytest tests/unit/ --cov=agentbench --cov-report=html

# Run integration test (requires API keys)
uv run pytest tests/integration/test_pipeline.py -v --integration
```

## Environment Variables

```bash
OPENAI_API_KEY=           # Required
ANTHROPIC_API_KEY=        # Required
MONGODB_URI=              # Default: mongodb://localhost:27017
REDIS_URL=                # Default: redis://localhost:6379
RAW_IO_DIR=               # Default: ./data/raw_io
LOG_LEVEL=                # Default: INFO
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/benchmarks` | POST | Create benchmark |
| `/benchmarks/{id}` | GET | Get report |
| `/benchmarks/{id}/runs` | GET | List runs |

## License

MIT License - See [LICENSE](LICENSE) for details.

## Portfolio Context

This project demonstrates:

- **Event-driven architecture** applied to AI evaluation
- **Clean separation** between orchestration, invocation, scoring, and reporting
- **Reproducible benchmarking** through immutable fixtures and stored raw outputs
- **Pragmatic stack simplification** that still resembles real AI platform architecture
- **Evaluation design** grounded in a realistic engineering workflow (PR review)

**Not Production Features:**
- This is not a production PR review bot
- Not a GitHub App or Jira integration
- Not an autonomous code-fixing system
- Not a framework for external arbitrary provider plugins
</content>