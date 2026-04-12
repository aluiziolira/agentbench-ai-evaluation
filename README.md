# AgentBench

A minimal AI agent evaluation framework for PR review behavior, built with event-driven architecture.

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/agentbench/agentbench/actions/workflows/ci.yml/badge.svg)](https://github.com/agentbench/agentbench/actions/workflows/ci.yml)

## Project Title

AgentBench is an evaluation framework that runs AI agents against seeded PR review cases, scores their findings through deterministic matching, and produces comparative benchmark reports.

- Event-driven orchestration coordinates dispatch, scoring, and reporting through Redis Streams
- Deterministic finding-match scoring produces reproducible results without stochastic resampling
- Dual-layer storage (MongoDB for reports, raw I/O files) supports offline re-scoring without re-invoking agents
- Committed fixture sets provide stable, versioned benchmarks that run locally with no external dependencies

AgentBench is not a production PR review bot, a GitHub App, a Jira integration, or a platform for evaluating agents against live repositories.

## Benchmark Proof

End-to-end validated against 8 fixed cases, these metrics show how the framework scores and ranks agents by review accuracy, speed, and reliability.

### Agent Performance Comparison

Sample run on 8 PR review cases (E2E validated 2026-04-04):

| Agent | Avg Score | P50 Latency | P95 Latency | Failure Rate |
|-------|-----------|-------------|-------------|--------------|
| **claude-haiku-4-5** | **0.913** | 2,500ms | 5,000ms | 0.0% |
| **gpt-4o-mini** | **0.888** | 1,500ms | 7,500ms | 0.0% |

**Key Observations:**
- Claude Haiku achieved highest score (91.3%) - 2.8% better than GPT-4o-mini
- GPT-4o-mini was faster on P50 latency (1.5s vs 2.5s)
- Both agents had 100% API success rate
- Scores from `s2_review_summary` LLM-judged step

*Run your own comparison:*
```bash
agentbench run --workflow wf_pr_review_v1 --case-set pr_review_cases_v1 \
  --agents gpt-4o-mini --agents claude-haiku-4-5
```

### Per-Case Breakdown

| Case | Claude Haiku | GPT-4o-mini | Topic |
|------|--------------|-------------|-------|
| pr_006_state_consistency_bug | **0.96** | 0.92 | Caching/State |
| pr_001_missing_auth_check | 0.92 | 0.92 | Auth/Security |
| pr_002_missing_test_coverage | 0.92 | **0.92** | Testing |
| pr_007_missing_validation | **0.92** | 0.88 | Input Validation |
| pr_008_performance_regression | **0.92** | 0.88 | Database/N+1 |
| pr_003_missing_null_guard | **0.90** | 0.82 | Null Safety |
| pr_004_contract_breaking_change | 0.88 | **0.88** | API Compatibility |
| pr_005_missing_error_handling | 0.88 | **0.88** | Error Handling |

## Problem Statement

Evaluating AI agents against each other is harder than it sounds. Most evaluation setups pull inputs from live sources: real GitHub pull requests, scraped Jira tickets, or provider-specific data feeds. That creates a comparability problem. When the inputs change between runs, scores drift. When different teams use different providers, results can't be compared side by side. When you need to re-score under a different rubric, you have to re-invoke the agent because the raw output wasn't stored. The result is benchmarks that look precise but can't be reproduced, can't be compared, and can't be iterated on without spending more API credits.

AgentBench solves this by fixing the inputs and storing the outputs. Every benchmark case is a committed fixture: a ticket, a diff, and a ground-truth file that never changes unless the case set is explicitly versioned. Every agent response is persisted as raw I/O, so re-scoring costs nothing. Every agent runs against the same workflow and the same case set, making cross-agent comparison a direct measurement rather than an approximation.

### Out of Scope

AgentBench is intentionally limited to what it can reproduce and compare. It is not a production PR review bot, not a GitHub App or Jira integration, and not a platform for evaluating agents against live repositories. It does not apply patches, run test suites, or execute the code under review. Fixing the benchmark scope to a single workflow and a versioned case set is a deliberate design choice, not a missing feature.

## Technical Decisions

AgentBench routes every step transition through Redis Streams instead of calling each service directly. A simpler design would have the orchestrator invoke dispatchers, scorers, and aggregators as synchronous functions within the same call stack, and for a single-user evaluation tool that would work fine. The trade-off is more event choreography and more moving parts: stream producers, consumer groups, and event schemas that all need to stay aligned. In exchange for that complexity, each service gets a hard boundary and can be reasoned about in isolation. Dispatch, scoring, and aggregation all react to the same event bus, so none of them holds a direct reference to the others. The result is pipeline behavior that mirrors production message-bus architectures, where services consume events rather than waiting on function calls. That modularity matters because it means swapping a scoring strategy or adding a new aggregation step requires wiring a new consumer rather than refactoring the orchestrator's control flow.

Storage splits intentionally between MongoDB for structured reports and the local filesystem for raw agent I/O. A single-store approach, whether MongoDB for everything or flat files for everything, would be simpler to set up but would make re-scoring expensive or reports harder to query. MongoDB stores benchmark metadata, scores, and per-case breakdowns with typed Pydantic validation and index-backed queries, while raw prompt and response pairs live as files that the scoring engine reads directly. Two scoring roles cover different needs: `finding_match` compares agent findings against ground truth with deterministic label matching for reproducible baselines, and `llm_judge` sends the full review to another LLM for qualitative assessment under a configurable rubric. The supporting infrastructure reflects backend best practices drawn from the codebase itself: async service composition for non-blocking orchestration, retries with exponential backoff and circuit breakers for API resilience, strict tooling with ruff formatting and mypy typing, and explicit index setup on query-heavy MongoDB collections. This split means any stored run can be re-scored under a new rubric without re-invoking the agent, and every scoring decision traces back to the exact inputs that produced it.

## Architecture

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

| Component | Simplified Version | Production Analogue |
|-----------|-------------------|---------------------|
| Redis Streams | Single Redis instance | Kafka / RabbitMQ |
| MongoDB | Single node | MongoDB Atlas / replicaset |
| Object Storage | Local filesystem | S3 / GCS |
| Single Process | Asyncio tasks | Kubernetes / ECS |
| In-memory scoring | Pydantic models | Dedicated scoring service |

## Why Seeded Fixtures?

The alternative is live ingestion: pulling PRs and tickets from GitHub, Jira, or GitLab at runtime. That approach introduces non-determinism, rate limits, auth complexity, and privacy risk. Seeded fixtures eliminate all of those problems while keeping the evaluation grounded in realistic review scenarios.

| Seeded Fixtures | Live Ingestion |
|-----------------|----------------|
| Reproducible | Non-deterministic |
| Stable scoring | Score drift over time |
| No API rate limits | Rate limited |
| Works offline | Requires connectivity |
| No auth complexity | OAuth/App setup |
| Clear demo assets | Privacy concerns |

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

## Five-Minute Local Run

Requires Python 3.12+, Docker, and API keys (OpenAI + Anthropic).

```bash
git clone <repo-url> && cd agentbench
pip install uv && uv sync
cp .env.example .env          # Add OPENAI_API_KEY and ANTHROPIC_API_KEY

docker-compose up -d mongodb redis
source .env && uv run python -m cli.main seed

# Start services in separate terminals
source .env && uv run python -m agentbench.main   # Terminal 1: runtime
source .env && uv run python start_api.py           # Terminal 2: API

# Run benchmark
uv run python -m cli.main run \
  --workflow wf_pr_review_v1 --case-set pr_review_cases_v1 \
  --agents gpt-4o-mini --agents claude-haiku-4-5

# Watch report
uv run python -m cli.main report {benchmark_id} --watch
```

## Testing

### Quick Reference

| Test Type | Command | Duration | Requirements |
|-----------|---------|----------|--------------|
| Unit | `uv run pytest tests/unit/ -q` | ~5s | None (all mocked) |
| Integration | `uv run pytest tests/integration/test_pipeline.py -v` | ~100s | Docker, API keys |
| Coverage | `uv run pytest tests/unit/ --cov=agentbench` | ~10s | None |

**Unit Tests**

Mock external dependencies and run in ~5 seconds (330 tests). Coverage spans adapters, storage, orchestration, scoring, API, CLI, and workflow validation.

```bash
uv run pytest tests/unit/ -q                    # All unit tests
uv run pytest tests/unit/ --cov=agentbench       # With coverage report
uv run pytest tests/unit/test_adapters.py -v     # Single module
```

**Integration Tests**

End-to-end tests verify the full pipeline including LLM calls. Scope: 2 cases x 2 agents = 4 LLM calls, completes in ~100 seconds.

Requirements: Docker Compose, `.env` with `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`, gate flag `AGENTBENCH_INTEGRATION_TEST=1`, and running services (`start_api.py` and `agentbench.main`).

Tests validate: multi-agent pipeline completion, single-agent execution, and artifact storage.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/benchmarks` | POST | Create benchmark |
| `/benchmarks/{id}` | GET | Get report |
| `/benchmarks/{id}/runs` | GET | List runs |

## License

MIT License - See [LICENSE](LICENSE) for details.
