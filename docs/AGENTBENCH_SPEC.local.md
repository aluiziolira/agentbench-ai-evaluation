# AgentBench - Spec-Driven Development Source of Truth

**Version:** 2.0.0
**Status:** Active - Source of Truth
**Scope:** Portfolio project. This spec defines the single active benchmark, the implementation constraints, and the acceptance criteria for all agentic development work.

---

## 0. How to Use This Document

This document is the source of truth for AgentBench.

Rules:
- Before writing code, read the relevant section here.
- If a requirement is not in this document, it is out of scope.
- If an implementation idea conflicts with this document, the document wins.
- Build in the implementation order defined near the end of this spec.

There is only one active benchmark in this project:
- `wf_pr_review_v1`

Do not preserve legacy factual benchmark behavior, prompts, fixtures, or scoring paths unless this spec is updated to require them.

---

## 1. Project Purpose and Portfolio Framing

AgentBench is a minimal AI agent evaluation framework for PR review behavior.

It registers versioned workflows, expands benchmark runs over a seeded case set, invokes multiple agents against the same review cases, scores their review outputs, and generates comparative benchmark reports.

**Portfolio signal this project should send:**
- event-driven thinking applied to AI evaluation
- clean separation between orchestration, model invocation, scoring, and reporting
- reproducible benchmarking through immutable fixtures and stored raw outputs
- pragmatic stack simplification that still resembles real AI platform architecture
- evaluation design grounded in a realistic engineering workflow

**What this project is not:**
- a production PR review bot
- a GitHub App or Jira integration
- an autonomous code-fixing system
- a framework for external users to plug arbitrary providers into
- a benchmark marketplace or dataset platform

---

## 2. Benchmark Task - Fixed Scope

The benchmark task is fixed across the entire project. Do not change it mid-build.

### Task: PR Review Benchmark

Each benchmark case consists of:
- a seeded ticket describing intent, expected behavior, or a requested change
- a seeded unified diff representing the code change under review
- a seeded ground-truth file describing the material findings a strong reviewer should catch

Each agent reviews the case like a pragmatic senior engineer and produces:
- a structured list of material findings
- a concise review summary

### Fixed identifiers

- **Workflow ID:** `wf_pr_review_v1`
- **Case Set ID:** `pr_review_cases_v1`

### Determinism requirements

- Agent temperature defaults to `0`
- `runs_per_agent` is fixed to `1`
- Reproducibility comes from seeded fixtures and raw I/O capture, not repeated stochastic sampling

Do not add repeated multi-run sampling in v1.

### Required benchmark agents

Minimum two agents are required:
- `gpt-4o-mini` via OpenAI SDK
- `claude-haiku-4-5` via Anthropic SDK

These are cheap, fast, and sufficient for meaningful portfolio-level comparisons.

---

## 3. Review Corpus - Source of Tickets and Diffs

The benchmark corpus is static and committed to the repository.

### 3.1 Source of truth

Tickets and diffs come from seeded fixtures authored for this project.

Allowed sources:
- handwritten tickets and diffs created directly for the benchmark
- diffs generated from a tiny local sample codebase and then committed as static `.patch` fixtures

Disallowed sources:
- live GitHub pull requests
- live Jira tickets
- scraped public PR datasets
- runtime ingestion from external repositories
- LLM-generated ground truth treated as authoritative without manual curation

### 3.2 Why seeded fixtures are required

Static fixtures are required because they provide:
- reproducibility
- stable scoring
- easy local execution
- clear demo assets for the portfolio
- no privacy or licensing ambiguity

### 3.3 Corpus layout

```text
fixtures/
└── pr_review/
    ├── manifest.json
    └── cases/
        ├── pr_001_missing_auth_check/
        │   ├── ticket.md
        │   ├── diff.patch
        │   ├── ground_truth.json
        │   └── metadata.json
        ├── pr_002_missing_test_coverage/
        │   ├── ticket.md
        │   ├── diff.patch
        │   ├── ground_truth.json
        │   └── metadata.json
        └── ...
```

### 3.4 Manifest contract

`fixtures/pr_review/manifest.json` defines the active case set.

```json
{
  "case_set_id": "pr_review_cases_v1",
  "version": "1.0.0",
  "cases": [
    {
      "case_id": "pr_001_missing_auth_check",
      "difficulty": "medium",
      "enabled": true,
      "tags": ["auth", "api", "tests"]
    }
  ]
}
```

### 3.5 Ground truth contract

Each case must define the expected material findings.

```json
{
  "case_id": "pr_001_missing_auth_check",
  "expected_findings": [
    {
      "finding_id": "F1",
      "canonical_label": "missing_permission_check",
      "severity": "high",
      "file_path": "app/api/admin.py",
      "line_span": [42, 57],
      "must_detect": true,
      "summary": "The endpoint no longer enforces the admin permission check."
    },
    {
      "finding_id": "F2",
      "canonical_label": "missing_test_coverage",
      "severity": "medium",
      "file_path": "tests/test_admin.py",
      "line_span": [1, 1],
      "must_detect": false,
      "summary": "No regression test covers unauthorized access to the updated endpoint."
    }
  ],
  "disallowed_findings": [
    {
      "canonical_label": "style_only_nit"
    }
  ]
}
```

`ground_truth.json` is the authoritative scoring baseline and must be manually curated.

### 3.6 Corpus size

For the initial portfolio release, the corpus should contain 6 to 10 cases.

Recommended issue coverage:
- missing permission check
- contract-breaking API change
- missing null or empty guard
- missing error handling
- missing validation
- missing regression test
- state consistency bug
- performance regression

Do not build a large dataset.

---

## 4. Architecture Overview

```text
[CLI / API] -> expand benchmark into case runs
                 |
                 v
          emit evaluation.run.requested
                 |
                 v
            [Redis Streams]
             /     |      \
            /      |       \
 [Orchestrator] [Dispatcher] [Scoring Engine]
       |              |              |
       v              v              v
    [Redis]      [Object FS]      [MongoDB]
  (FSM state)   (raw I/O)   (workflow + reports + runs)
                                         |
                                         v
                              [Results Aggregator]
```

**Single process, multiple async tasks.** This is not microservices. All logical services run as asyncio tasks within one Python process, communicating exclusively through Redis Streams. Module boundaries enforce separation of concerns.

The evented design is retained because it is one of the strongest portfolio signals in the project.

---

## 5. Repository Structure

```text
agentbench/
├── AGENTBENCH_SPEC.md
├── docker-compose.yml
├── pyproject.toml
├── .env.example
│
├── agentbench/
│   ├── __init__.py
│   ├── main.py
│   │
│   ├── cases/
│   │   ├── loader.py
│   │   └── models.py
│   │
│   ├── models/
│   │   ├── workflow.py
│   │   ├── run.py
│   │   ├── events.py
│   │   └── results.py
│   │
│   ├── storage/
│   │   ├── mongo.py
│   │   └── redis_client.py
│   │
│   ├── events/
│   │   ├── bus.py
│   │   └── types.py
│   │
│   ├── orchestrator/
│   │   └── orchestrator.py
│   │
│   ├── dispatcher/
│   │   ├── dispatcher.py
│   │   └── adapters/
│   │       ├── base.py
│   │       ├── openai_adapter.py
│   │       └── anthropic_adapter.py
│   │
│   ├── scoring/
│   │   ├── engine.py
│   │   └── strategies/
│   │       ├── base.py
│   │       ├── finding_match.py
│   │       └── llm_judge.py
│   │
│   ├── aggregator/
│   │   └── aggregator.py
│   │
│   └── api/
│       ├── app.py
│       └── routers/
│           ├── benchmarks.py
│           └── workflows.py
│
├── cli/
│   └── main.py
│
├── workflows/
│   └── wf_pr_review_v1.json
│
├── fixtures/
│   └── pr_review/
│       ├── manifest.json
│       └── cases/
│
└── tests/
    ├── unit/
    │   ├── test_case_loader.py
    │   ├── test_finding_match.py
    │   ├── test_llm_judge.py
    │   └── test_adapters.py
    └── integration/
        └── test_pipeline.py
```

---

## 6. Data Models

All models use Pydantic v2. All IDs are UUID4 strings unless otherwise specified. All timestamps are ISO-8601 UTC strings.

### 6.1 WorkflowDefinition

```python
class ScoringConfig(BaseModel):
    strategy: Literal["finding_match", "llm_judge"]
    rubric: str | None = None
    weight: float = 1.0

class StepDefinition(BaseModel):
    step_id: str
    order: int
    input: str
    timeout_ms: int = 15000
    scoring: ScoringConfig

class WorkflowDefinition(BaseModel):
    workflow_id: str
    version: str
    status: Literal["draft", "published"]
    description: str
    steps: list[StepDefinition]
    scoring_aggregation: Literal["weighted_average"] = "weighted_average"
    created_at: str
    published_at: str | None = None
```

**Immutability rule:** Once `status` is `published`, no field may be mutated. Any change creates a new version. Enforce this in the MongoDB storage layer.

### 6.2 ReviewCaseDefinition

```python
class ReviewFindingTruth(BaseModel):
    finding_id: str
    canonical_label: str
    severity: Literal["high", "medium", "low"]
    file_path: str
    line_span: tuple[int, int]
    must_detect: bool = True
    summary: str

class DisallowedFinding(BaseModel):
    canonical_label: str

class ReviewCaseDefinition(BaseModel):
    case_id: str
    case_set_id: str
    difficulty: Literal["easy", "medium", "hard"]
    tags: list[str]
    ticket_text: str
    diff_patch: str
    expected_findings: list[ReviewFindingTruth]
    disallowed_findings: list[DisallowedFinding] = []
```

### 6.3 EvaluationRun

```python
class RunState(str, Enum):
    PENDING = "PENDING"
    STARTED = "STARTED"
    STEP_IN_PROGRESS = "STEP_IN_PROGRESS"
    STEP_SCORED = "STEP_SCORED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"

class EvaluationRun(BaseModel):
    run_id: str
    benchmark_id: str
    workflow_id: str
    workflow_version: str
    case_set_id: str
    case_id: str
    agent_id: str
    agent_config: dict
    state: RunState = RunState.PENDING
    current_step: int = 0
    created_at: str
    completed_at: str | None = None
```

### 6.4 EventEnvelope

```python
class EventEnvelope(BaseModel):
    event_id: str
    event_type: str
    schema_version: str = "1.0"
    timestamp: str
    correlation_id: str
    payload: dict
```

`correlation_id` equals `run_id` for all run-scoped events. Every consumer must log it.

### 6.5 StepScore and Reports

```python
class StepScore(BaseModel):
    run_id: str
    case_id: str
    step_id: str
    strategy: str
    raw_score: float
    weighted_score: float
    latency_ms: int
    passed: bool
    details: dict = {}

class RunReport(BaseModel):
    run_id: str
    benchmark_id: str
    case_id: str
    case_tags: list[str]
    agent_id: str
    workflow_id: str
    total_score: float
    step_scores: list[StepScore]
    total_latency_ms: int
    completed_at: str

class AgentSummary(BaseModel):
    agent_id: str
    avg_score: float
    p50_latency_ms: int
    p95_latency_ms: int
    failure_rate: float
    step_breakdown: dict[str, float]

class BenchmarkReport(BaseModel):
    benchmark_id: str
    workflow_id: str
    case_set_id: str
    created_at: str
    case_count: int
    agents: list[AgentSummary]
    per_case_scores: dict[str, dict[str, float]]
```

---

## 7. Workflow Definition

The active workflow is fixed and case-driven.

### Step 1 - Findings Extraction

**Step ID:** `s1_findings`

**Input template:**

```text
You are reviewing a pull request as a senior software engineer.

Ticket:
{ticket_text}

Diff:
{diff_patch}

Identify only material issues that could cause bugs, regressions, security problems,
contract breaks, data issues, or missing required tests.

Return JSON only with this schema:
{
  "findings": [
    {
      "canonical_label": "<enum>",
      "severity": "high|medium|low",
      "file_path": "<repo path>",
      "start_line": <int>,
      "end_line": <int>,
      "title": "<short title>",
      "why_it_matters": "<one or two sentences>",
      "suggested_test": "<short regression test suggestion>"
    }
  ]
}

Rules:
- Return at most 5 findings.
- Do not include style nits, naming preferences, or formatting comments.
- If there are no material issues, return {"findings": []}.
- Use only canonical labels from the allowed taxonomy.
```

**Scoring:** `finding_match`

**Weight:** `2.0`

### Step 2 - Final Review Summary

**Step ID:** `s2_review_summary`

**Input template:**

```text
You are writing the final PR review summary for the following change.

Ticket:
{ticket_text}

Diff:
{diff_patch}

Write a concise review summary for the PR author.

Rules:
- 4 to 8 lines total
- prioritize the most important issue first
- mention missing tests when they matter
- no praise, no filler, no restating the entire ticket
- focus on actionability and risk
```

**Scoring:** `llm_judge`

**Weight:** `1.0`

### Placeholder support

Workflow prompts may contain only these placeholders:
- `{ticket_text}`
- `{diff_patch}`
- `{case_id}`

Use plain `str.format()`-style rendering. Do not add a general templating engine.

---

## 8. Event Taxonomy

These are the only valid event types.

```python
EVALUATION_RUN_REQUESTED   = "evaluation.run.requested"
EVALUATION_RUN_STARTED     = "evaluation.run.started"
EVALUATION_RUN_COMPLETED   = "evaluation.run.completed"
EVALUATION_RUN_FAILED      = "evaluation.run.failed"

WORKFLOW_STEP_DISPATCHED   = "workflow.step.dispatched"
WORKFLOW_STEP_TIMED_OUT    = "workflow.step.timed_out"
WORKFLOW_COMPLETED         = "workflow.completed"

AGENT_RESPONSE_RECEIVED    = "agent.response.received"

STEP_SCORED                = "step.scored"

BENCHMARK_REPORT_GENERATED = "benchmark.report.generated"
```

### Stream-to-event mapping

| Stream key | Event types written to it |
|---|---|
| `stream:eval-runs` | `evaluation.run.*` |
| `stream:eval-steps` | `workflow.step.*`, `agent.response.received` |
| `stream:scores` | `step.scored`, `workflow.completed` |
| `stream:reports` | `benchmark.report.generated` |

### Event payload rules

Events may carry IDs and metadata only.

Allowed payload fields include:
- `benchmark_id`
- `run_id`
- `workflow_id`
- `agent_id`
- `case_set_id`
- `case_id`
- `step_id`

Disallowed payload contents:
- full diff contents
- full ticket contents
- full workflow definitions
- full ground-truth documents
- raw agent responses larger than the event metadata requirement

Large artifacts must stay on disk or be loaded from storage by the consumer.

---

## 9. Service Contracts

Each service is a long-running asyncio coroutine. Services do not call each other directly.

### 9.1 Case Loader

**Module:** `agentbench/cases/loader.py`

Responsibilities:
- load `fixtures/pr_review/manifest.json`
- resolve enabled cases by `case_set_id`
- load a single case by `case_id`
- return typed `ReviewCaseDefinition` instances

Case loading is local and file-based only.

### 9.2 Orchestrator

**Consumes:** `stream:eval-runs` (`evaluation.run.requested`, `step.scored`)

**Publishes:** `stream:eval-runs` (`evaluation.run.started`, `evaluation.run.completed`, `evaluation.run.failed`), `stream:eval-steps` (`workflow.step.dispatched`)

**Owns:** FSM state in Redis

**Behavior:**
1. On `evaluation.run.requested`, load the workflow and set FSM to `STARTED`
2. Dispatch step 0 for the run
3. On `step.scored`, advance the step cursor
4. Dispatch the next step or emit `workflow.completed` when all steps are done
5. On timeout or unrecoverable error, emit `evaluation.run.failed`

### 9.3 Step Dispatcher

**Consumes:** `stream:eval-steps` (`workflow.step.dispatched`)

**Publishes:** `stream:eval-steps` (`agent.response.received`, `workflow.step.timed_out`)

**Owns:** raw I/O files under `data/raw_io/{run_id}/{step_id}.json`

**Behavior:**
1. Load the `EvaluationRun`, workflow step, and `ReviewCaseDefinition`
2. Render the prompt using the case placeholders
3. Resolve the correct `AgentAdapter` from `agent_id`
4. Invoke the adapter with `asyncio.wait_for()` using `timeout_ms`
5. Save request, response, case metadata, and latency to raw I/O storage
6. Emit `agent.response.received`

### 9.4 Scoring Engine

**Consumes:** `stream:eval-steps` (`agent.response.received`)

**Publishes:** `stream:scores` (`step.scored`)

**Behavior:**
1. Load the step definition and the review case
2. Resolve the configured scoring strategy
3. Compute `StepScore`
4. Emit `step.scored`

### 9.5 Results Aggregator

**Consumes:** `stream:scores` (`step.scored`, `workflow.completed`)

**Publishes:** `stream:reports` (`benchmark.report.generated`)

**Owns:** `RunReport` and `BenchmarkReport` documents in MongoDB

**Behavior:**
1. On `step.scored`, accumulate scores in memory keyed by `run_id`
2. On `workflow.completed`, compute `RunReport` and persist it
3. When all expected `(agent_id, case_id)` runs for a benchmark are complete, compute `BenchmarkReport`
4. Persist the report and emit `benchmark.report.generated`

---

## 10. Agent Adapter Interface

```python
@runtime_checkable
class AgentAdapter(Protocol):
    agent_id: str

    async def invoke(
        self,
        step: StepDefinition,
        run: EvaluationRun,
        conversation_history: list[dict],
    ) -> tuple[str, int]:
        ...
```

Required implementations:
- `OpenAIAdapter` using `openai.AsyncOpenAI`
- `AnthropicAdapter` using `anthropic.AsyncAnthropic`

Adapter registry:

```python
ADAPTER_REGISTRY: dict[str, AgentAdapter] = {
    "gpt-4o-mini": OpenAIAdapter(model="gpt-4o-mini"),
    "claude-haiku-4-5": AnthropicAdapter(model="claude-haiku-4-5-20251001"),
}
```

Adding a new agent means adding a registry entry and a corresponding adapter implementation only when actually needed.

---

## 11. Review Behavior Contract

The benchmark evaluates PR review behavior, not general explanation quality.

### 11.1 Reviewer stance

The agent must behave like a pragmatic senior reviewer.

It should optimize for:
- correctness
- regression detection
- risk prioritization
- missing tests
- ticket-to-diff consistency

It should not optimize for:
- politeness
- code style preferences
- educational explanation
- speculative rewrites

### 11.2 Expected review patterns

Good outputs should:
- identify material defects and ignore cosmetic noise
- ground findings in the diff and ticket
- prioritize by severity
- name the affected file and approximate location
- suggest the most relevant regression test when applicable
- keep the finding list small and high-signal

### 11.3 Canonical finding taxonomy

The initial allowed `canonical_label` set is:
- `missing_permission_check`
- `contract_breaking_change`
- `missing_null_guard`
- `missing_error_handling`
- `missing_validation`
- `missing_test_coverage`
- `state_consistency_bug`
- `performance_regression`
- `logging_observability_gap`
- `incorrect_business_rule`

This taxonomy exists to make deterministic scoring possible.

### 11.4 Output constraints

- no inline comment threading
- no patch suggestions
- no full rewritten code
- no conversational back-and-forth
- no more than 5 structured findings per case

---

## 12. Scoring Strategy Interface

```python
class ScoringStrategy(Protocol):
    strategy_id: str

    def score(
        self,
        step: StepDefinition,
        response_text: str,
        run_id: str,
        latency_ms: int,
        case: ReviewCaseDefinition,
    ) -> StepScore:
        ...
```

### 12.1 `finding_match`

This is the core benchmark-specific scoring strategy.

Purpose:
- score the structured findings from `s1_findings` against seeded ground truth
- reward detection of important issues
- penalize noisy false positives
- keep scoring deterministic and explainable

Matching rules:
- `canonical_label` must match exactly
- `file_path` must match exactly
- predicted line range must overlap the expected `line_span`, or fall within a tolerance of plus or minus 5 lines

Severity handling:
- exact severity match gets full credit
- one-level mismatch gets reduced credit
- larger mismatch gets no severity bonus

Recommended formula:
- each `must_detect = true` finding is worth `1.0` base points
- each optional finding is worth `0.5` base points
- exact severity match adds `0.25`
- each unmatched false positive subtracts `0.25`
- each disallowed finding subtracts `0.5`
- floor the raw total at `0.0`
- normalize by the maximum achievable positive points for the case

The final `raw_score` must be clamped to `[0.0, 1.0]`.

If the response is not valid JSON matching the required schema:
- `raw_score = 0.0`
- log a warning with `correlation_id` and `case_id`

### 12.2 `llm_judge`

`s2_review_summary` is judged with an LLM rubric.

Required rubric dimensions:
- prioritizes the most important issue first
- remains grounded in the actual diff and ticket
- mentions missing tests when relevant
- avoids filler and low-value commentary
- is actionable for the PR author

The findings step is where deterministic benchmark signal lives. The summary step is intentionally the re-scoring demo.

### 12.3 Re-scoring requirement

Re-scoring is mandatory.

The demo must show:
- deterministic findings score staying stable for `s1_findings`
- summary score changing when the rubric for `s2_review_summary` changes

---

## 13. Storage Contracts

### MongoDB collections

**`workflows`**
- unique index on `workflow_id + version`
- published documents are immutable

**`runs`**
- unique index on `run_id`
- index on `benchmark_id`
- index on `case_set_id + case_id`

**`run_reports`**
- unique index on `run_id`
- index on `benchmark_id`
- index on `case_id`

**`benchmark_reports`**
- unique index on `benchmark_id`

### Redis keys

| Key pattern | Type | TTL | Purpose |
|---|---|---|---|
| `run:{run_id}:state` | String | 1 hour | FSM current state |
| `run:{run_id}:step` | String | 1 hour | Current step index |
| `benchmark:{id}:runs` | Set | 2 hours | run IDs in the benchmark |
| `benchmark:{id}:completed` | Set | 2 hours | completed run IDs |
| `workflow:{id}:{version}` | Hash | 24 hours | cached workflow definition |

### Raw I/O files

Path:

```text
data/raw_io/{run_id}/{step_id}.json
```

Each file must include:
- `run_id`
- `case_set_id`
- `case_id`
- `step_id`
- `agent_id`
- `request`
- `response`
- `latency_ms`
- `timestamp`

These files are the foundation of the re-scoring demo and must be preserved as fixtures for at least one complete benchmark run.

### Case set immutability

Once `pr_review_cases_v1` is used for published benchmark results, its fixtures must not change.

Any case content change requires a new case set version.

---

## 14. API Endpoints

```text
POST   /benchmarks                     -> trigger a benchmark run
GET    /benchmarks/{benchmark_id}      -> get report (202 if in progress)
GET    /benchmarks/{benchmark_id}/runs -> list run summaries

POST   /workflows                      -> register a workflow definition
GET    /workflows/{workflow_id}        -> get latest published workflow version
POST   /workflows/{workflow_id}/publish -> publish a workflow version
```

### `POST /benchmarks` request body

```json
{
  "workflow_id": "wf_pr_review_v1",
  "case_set_id": "pr_review_cases_v1",
  "agents": ["gpt-4o-mini", "claude-haiku-4-5"]
}
```

Rules:
- do not add case authoring endpoints in v1
- benchmark creation expands internally into one run per `(agent_id, case_id)`

---

## 15. CLI Commands

```bash
agentbench run --workflow wf_pr_review_v1 --case-set pr_review_cases_v1 --agents gpt-4o-mini claude-haiku-4-5

agentbench report --benchmark-id <id> --watch

agentbench rescore --run-id <id> --step s2_review_summary --strategy llm_judge --rubric "Prioritize production risk above all else"

agentbench seed

agentbench list-cases --case-set pr_review_cases_v1
```

Do not build fixture CRUD into the CLI.

---

## 16. Environment Variables

```bash
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=agentbench

REDIS_URL=redis://localhost:6379

RAW_IO_DIR=data/raw_io
PR_REVIEW_FIXTURES_DIR=fixtures/pr_review

LOG_LEVEL=INFO
```

No other configuration. Do not add feature flags or environment-specific branching.

---

## 17. Docker Compose

```yaml
services:
  mongodb:
    image: mongo:7
    ports: ["27017:27017"]
    volumes: ["mongo_data:/data/db"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  agentbench:
    build: .
    depends_on: [mongodb, redis]
    env_file: .env
    volumes: ["./data:/app/data", "./fixtures:/app/fixtures"]
    command: python -m agentbench.main

volumes:
  mongo_data:
```

---

## 18. Testing Strategy

**Unit tests:**
- `test_case_loader.py` validates manifest parsing, case loading, and error handling
- `test_finding_match.py` validates deterministic matching, penalties, parse failures, and normalization
- `test_llm_judge.py` mocks the Anthropic client and validates score parsing
- `test_adapters.py` mocks HTTP calls and validates request shape and response parsing

**Integration test:**
- `test_pipeline.py` runs the full `wf_pr_review_v1` workflow against the seeded case set using real API keys and asserts a `BenchmarkReport` is produced
- mark with `@pytest.mark.integration`
- exclude from CI by default and require an explicit opt-in flag

**Testing rules:**
- no browser tests
- no load tests
- no runtime contract tests against external providers

---

## 19. Anti-Patterns - Do Not Implement

**AP-01: Direct service-to-service calls**
Services must not call each other directly. All coordination happens through Redis Streams.

**AP-02: Mutable published workflows**
Published workflow versions must be immutable.

**AP-03: Mutable published case sets**
Do not edit case fixtures after publishing benchmark results against them. Version the case set instead.

**AP-04: Live provider ingestion**
Do not fetch tickets, PRs, or diffs from GitHub, GitLab, Bitbucket, or Jira at runtime.

**AP-05: Executing the reviewed change**
Do not apply patches, run test suites, or build sandboxes for review cases.

**AP-06: Storing large artifacts in Redis events**
Do not place full diff contents, full tickets, or other large review artifacts into events.

**AP-07: LLM-only scoring of findings**
Do not score the findings step purely with an LLM judge. The core benchmark signal must be deterministic.

**AP-08: Scoring logic in the Dispatcher**
The Dispatcher only invokes agents and writes raw I/O. It must not score, evaluate, or rewrite results.

**AP-09: Case-specific hardcoding in the pipeline**
Do not write logic keyed on a specific `case_id` outside loading fixture data.

**AP-10: Unbounded finding lists**
Do not allow arbitrarily large finding lists. This rewards shotgun guessing.

**AP-11: Style-nit scoring**
Do not include cosmetic formatting or naming comments in ground truth unless they map to a real behavioral risk.

**AP-12: Remediation-first prompting**
Do not ask the benchmarked agent to fix the code or produce a patch before it completes the review.

**AP-13: Infrastructure creep**
Do not add Kafka, Kubernetes, S3, or dynamic dataset infrastructure to this portfolio project.

**AP-14: Starting with the API**
Build from cases and scoring upward. Do not start implementation at the API layer.

---

## 20. README Requirements

The README is part of the portfolio deliverable. It must include:

1. an architecture decision narrative written for a tech lead reader
2. an explanation of why the benchmark uses seeded PR-review fixtures instead of live provider ingestion
3. a re-scoring demo showing the same stored outputs judged under a different summary rubric
4. one rendered benchmark result table comparing at least two agents
5. one sample case showing ticket, diff excerpt, expected finding, and model outputs
6. a stack justification table showing each simplified component and its production analogue
7. a five-minute local run path

---

## 21. Definition of Done

A feature is done when:
- [ ] behavior matches the contract defined in this spec
- [ ] unit tests pass for all new logic
- [ ] no anti-patterns from Section 19 are introduced
- [ ] `correlation_id` is present in all log lines produced by the feature
- [ ] the feature works end-to-end via Docker Compose where applicable

The project is done when:
- [ ] `wf_pr_review_v1` is implemented and published
- [ ] `pr_review_cases_v1` exists with 6 to 10 curated cases
- [ ] one run is created for each `(agent_id, case_id)` in a benchmark
- [ ] `s1_findings` uses deterministic `finding_match` scoring
- [ ] `s2_review_summary` uses `llm_judge` scoring
- [ ] `GET /benchmarks/{id}` returns a `BenchmarkReport`
- [ ] `agentbench rescore` can change the score of `s2_review_summary` without re-invoking the agent
- [ ] raw I/O fixtures for at least one complete benchmark are committed
- [ ] README includes all items from Section 20

---

## 22. Implementation Order

Build in this order:
1. review case models and case loader
2. seeded case corpus and manifest
3. workflow prompt assets for `wf_pr_review_v1`
4. storage contracts needed for case-based runs
5. `finding_match` scoring strategy
6. dispatcher prompt rendering and raw I/O persistence
7. orchestrator benchmark expansion and step progression
8. results aggregation for per-case and per-agent reports
9. API and CLI parameter updates
10. README demo assets and final fixture snapshots

Do not start with UI, live integrations, or fixture authoring tooling.
