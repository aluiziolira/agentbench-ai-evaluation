# AgentBench Implementation Orchestration

**Status:** Active
**Purpose:** Central implementation board for all agentic development work against `docs/AGENTBENCH_SPEC.local.md`.

This document is the operational layer for implementation. It breaks the SDD into module-scoped tasks that can be executed by multiple agents in parallel while preserving clean handoffs and validation rules.

---

## 0. Operating Protocol

Rules for any agent working from this document:
- Do not start a task unless all dependencies listed for that task are complete.
- Update only the task status and evidence for tasks you actually worked on.
- Keep changes inside the file and module scope listed for the task.
- Use the validation checklist before marking a task complete.
- If implementation pressure suggests changing scope, update the SDD first, not this task board.

### Status markers

- `[ ]` pending
- `[~]` in progress
- `[x]` completed
- `[!]` blocked

### Evidence format

Each completed task should record:
- changed files
- validation run
- follow-up notes or blockers discovered

---

## 1. Critical Path

Execution order:
1. `CASES-01` -> `CASES-02`
2. `MODELS-01` and `WORKFLOW-01`
3. `STORAGE-01` and `EVENTS-01`
4. `SCORING-01`
5. `DISPATCH-01`
6. `ORCH-01`
7. `AGG-01`
8. `API-01` and `CLI-01`
9. `TEST-INT-01`
10. `README-01`

Parallelizable groups:
- `MODELS-01`, `WORKFLOW-01`, and `EVENTS-01`
- `API-01` and `CLI-01`
- `TEST-UNIT-01`, `TEST-UNIT-02`, and `TEST-UNIT-03` once their target modules exist

---

## 2. Task Index

| Task ID | Module | Summary | Depends On | Status |
|---|---|---|---|---|
| `CASES-01` | `agentbench/cases/models.py` | Define typed review case models | none | `[ ]` |
| `CASES-02` | `agentbench/cases/loader.py` | Load manifest and cases from fixtures | `CASES-01` | `[ ]` |
| `FIXTURES-01` | `fixtures/pr_review/**` | Create seeded manifest and case fixtures | `CASES-01` | `[ ]` |
| `MODELS-01` | `agentbench/models/*.py` | Refactor run, workflow, results models for case-based benchmarking | `CASES-01` | `[ ]` |
| `WORKFLOW-01` | `workflows/wf_pr_review_v1.json` | Define the single active workflow | `MODELS-01` | `[ ]` |
| `EVENTS-01` | `agentbench/events/*.py` | Align event types and payload helpers with case-based runs | `MODELS-01` | `[ ]` |
| `STORAGE-01` | `agentbench/storage/mongo.py` | Persist workflows, runs, and reports with case-set semantics | `MODELS-01` | `[ ]` |
| `STORAGE-02` | `agentbench/storage/redis_client.py` | Support run FSM and benchmark tracking keys | `MODELS-01`, `EVENTS-01` | `[ ]` |
| `SCORING-01` | `agentbench/scoring/strategies/finding_match.py` | Implement deterministic findings scorer | `CASES-01`, `MODELS-01`, `FIXTURES-01` | `[ ]` |
| `SCORING-02` | `agentbench/scoring/strategies/llm_judge.py` | Implement summary judge scorer | `MODELS-01` | `[ ]` |
| `SCORING-03` | `agentbench/scoring/engine.py` | Route responses to benchmark scoring strategies | `SCORING-01`, `SCORING-02`, `CASES-02` | `[ ]` |
| `ADAPTERS-01` | `agentbench/dispatcher/adapters/*.py` | Implement async provider adapters | `MODELS-01` | `[ ]` |
| `DISPATCH-01` | `agentbench/dispatcher/dispatcher.py` | Render prompts, invoke adapters, and persist raw I/O | `ADAPTERS-01`, `CASES-02`, `WORKFLOW-01` | `[ ]` |
| `ORCH-01` | `agentbench/orchestrator/orchestrator.py` | Expand benchmarks into case runs and drive step FSM | `WORKFLOW-01`, `STORAGE-01`, `STORAGE-02`, `EVENTS-01` | `[ ]` |
| `AGG-01` | `agentbench/aggregator/aggregator.py` | Build run and benchmark reports with per-case scoring | `MODELS-01`, `SCORING-03`, `STORAGE-01`, `STORAGE-02` | `[ ]` |
| `API-01` | `agentbench/api/routers/*.py` | Expose benchmark run and report endpoints | `ORCH-01`, `AGG-01` | `[ ]` |
| `CLI-01` | `cli/main.py` | Expose run, report, seed, rescore, and list-cases commands | `ORCH-01`, `AGG-01`, `CASES-02` | `[ ]` |
| `MAIN-01` | `agentbench/main.py` | Wire all long-running services together | `EVENTS-01`, `DISPATCH-01`, `SCORING-03`, `ORCH-01`, `AGG-01` | `[ ]` |
| `TEST-UNIT-01` | `tests/unit/test_case_loader.py` | Cover fixture and loader behavior | `CASES-02`, `FIXTURES-01` | `[ ]` |
| `TEST-UNIT-02` | `tests/unit/test_finding_match.py` | Cover deterministic scoring behavior | `SCORING-01`, `FIXTURES-01` | `[ ]` |
| `TEST-UNIT-03` | `tests/unit/test_adapters.py`, `tests/unit/test_llm_judge.py` | Cover adapters and summary judge | `ADAPTERS-01`, `SCORING-02` | `[ ]` |
| `TEST-INT-01` | `tests/integration/test_pipeline.py` | Cover end-to-end benchmark pipeline | `MAIN-01`, `API-01`, `CLI-01` | `[ ]` |
| `README-01` | `README.md` | Document architecture, benchmark, and demo assets | `TEST-INT-01` | `[ ]` |

---

## 3. Module Tasks

### `CASES-01` - Typed Review Case Models

- Status: `[ ]`
- Scope: `agentbench/cases/models.py`
- Goal: Define the typed models needed to represent the manifest, case metadata, ground truth, and fully loaded review cases.
- Inputs:
  - `docs/AGENTBENCH_SPEC.local.md` Sections 3 and 6
- Deliverables:
  - `ReviewCaseDefinition`
  - manifest entry models
  - ground-truth finding models
  - validation for severity and difficulty enums
- Constraints:
  - keep models minimal and benchmark-specific
  - do not introduce general dataset abstractions
- Validation:
  - model import succeeds
  - invalid severity and malformed line spans fail validation
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `CASES-02` - Fixture Loader

- Status: `[ ]`
- Scope: `agentbench/cases/loader.py`
- Depends on: `CASES-01`
- Goal: Load the manifest and resolve enabled cases from local fixtures.
- Deliverables:
  - load case set manifest by path
  - list enabled cases
  - load full case by `case_id`
  - raise explicit errors for missing files or malformed fixtures
- Constraints:
  - filesystem only
  - no remote loading or caching layer beyond simple in-process memoization if needed
- Validation:
  - one unit test for happy path loading
  - one unit test for missing case files
  - one unit test for disabled case filtering
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `FIXTURES-01` - Seeded PR Review Corpus

- Status: `[ ]`
- Scope: `fixtures/pr_review/**`
- Depends on: `CASES-01`
- Goal: Create the initial immutable seeded benchmark corpus.
- Deliverables:
  - `manifest.json`
  - 6 to 10 case directories
  - each case contains `ticket.md`, `diff.patch`, `ground_truth.json`, `metadata.json`
- Constraints:
  - only material engineering issues
  - no style-only findings
  - no generated placeholder lorem content
- Validation:
  - all cases load through `CASES-02`
  - each case has at least one expected finding
  - the corpus spans multiple issue categories
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `MODELS-01` - Core Benchmark Models

- Status: `[ ]`
- Scope: `agentbench/models/workflow.py`, `agentbench/models/run.py`, `agentbench/models/results.py`, `agentbench/models/events.py`
- Depends on: `CASES-01`
- Goal: Align core models with the case-based PR review benchmark.
- Deliverables:
  - `EvaluationRun` with `case_set_id` and `case_id`
  - `BenchmarkReport` with per-case score structure
  - `StepScore` details field for scorer metadata
  - workflow scoring config restricted to active strategies
- Constraints:
  - do not retain dead fields from the factual benchmark if unused
  - preserve backward-compatible naming only when required by current code
- Validation:
  - model serialization round-trips
  - report shape matches the active spec
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `WORKFLOW-01` - Active Workflow Asset

- Status: `[ ]`
- Scope: `workflows/wf_pr_review_v1.json`
- Depends on: `MODELS-01`
- Goal: Publish the one active workflow definition.
- Deliverables:
  - two-step workflow matching the spec exactly
  - prompt templates with only supported placeholders
  - published workflow status for seeding
- Constraints:
  - exactly two steps
  - no factual QA legacy prompts
- Validation:
  - workflow validates against `WorkflowDefinition`
  - step IDs and strategy names match the spec
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `EVENTS-01` - Event Types and Bus Helpers

- Status: `[ ]`
- Scope: `agentbench/events/types.py`, `agentbench/events/bus.py`
- Depends on: `MODELS-01`
- Goal: Ensure event helpers match the case-based run model and enforce lean payloads.
- Deliverables:
  - canonical event constants
  - publish and consume helpers that preserve `correlation_id`
  - event payload helper shapes for case-aware runs
- Constraints:
  - no diff or ticket bodies in event payloads
- Validation:
  - event envelope creation includes `run_id` as `correlation_id`
  - payload helper tests reject oversized artifact inclusion patterns
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `STORAGE-01` - Mongo Persistence

- Status: `[ ]`
- Scope: `agentbench/storage/mongo.py`
- Depends on: `MODELS-01`
- Goal: Persist workflows, runs, run reports, and benchmark reports for the active benchmark.
- Deliverables:
  - workflow CRUD with immutability protection for published versions
  - run persistence keyed by `run_id`
  - report persistence for run and benchmark reports
  - indexes required by the SDD
- Constraints:
  - enforce immutability in storage, not in callers
- Validation:
  - published workflow update raises expected error
  - persisted run report includes `case_id`
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `STORAGE-02` - Redis FSM and Benchmark Tracking

- Status: `[ ]`
- Scope: `agentbench/storage/redis_client.py`
- Depends on: `MODELS-01`, `EVENTS-01`
- Goal: Track run state, current step, and benchmark completion progress.
- Deliverables:
  - helpers for FSM state read/write
  - helpers for current step read/write
  - helpers for benchmark run and completion sets
- Constraints:
  - keep the key surface small and aligned to the spec
- Validation:
  - key writes use the configured TTLs
  - benchmark completion calculations work for multi-case runs
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `SCORING-01` - Deterministic Findings Matcher

- Status: `[ ]`
- Scope: `agentbench/scoring/strategies/finding_match.py`
- Depends on: `CASES-01`, `MODELS-01`, `FIXTURES-01`
- Goal: Implement deterministic matching from structured findings to seeded ground truth.
- Deliverables:
  - JSON parse and schema validation
  - label, file path, and line range matching
  - severity bonus logic
  - false-positive and disallowed-finding penalties
  - normalized `StepScore.details`
- Constraints:
  - no LLM use
  - no case-specific heuristics
- Validation:
  - must-detect findings produce expected score
  - false positives reduce score
  - malformed JSON returns `0.0`
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `SCORING-02` - Summary Judge

- Status: `[ ]`
- Scope: `agentbench/scoring/strategies/llm_judge.py`
- Depends on: `MODELS-01`
- Goal: Score the summary step against the required rubric and preserve reasons for inspection.
- Deliverables:
  - fixed judge prompt contract
  - score parsing
  - parse-failure fallback behavior
- Constraints:
  - no benchmark-specific business logic beyond rubric evaluation
- Validation:
  - mocked judge success path
  - mocked parse failure path
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `SCORING-03` - Scoring Engine Routing

- Status: `[ ]`
- Scope: `agentbench/scoring/engine.py`
- Depends on: `SCORING-01`, `SCORING-02`, `CASES-02`
- Goal: Route agent responses to the configured strategy and emit `step.scored`.
- Deliverables:
  - workflow step lookup
  - case lookup
  - strategy registry
  - `StepScore` emission
- Constraints:
  - no workflow-specific branching outside configured strategy resolution
- Validation:
  - both active strategies route correctly
  - `case_id` is preserved in emitted score data
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `ADAPTERS-01` - Provider Adapters

- Status: `[ ]`
- Scope: `agentbench/dispatcher/adapters/base.py`, `agentbench/dispatcher/adapters/openai_adapter.py`, `agentbench/dispatcher/adapters/anthropic_adapter.py`
- Depends on: `MODELS-01`
- Goal: Provide async invocation wrappers for the supported benchmark agents.
- Deliverables:
  - protocol-aligned base interface
  - OpenAI async adapter
  - Anthropic async adapter
  - normalized `(response_text, latency_ms)` return contract
- Constraints:
  - async only
  - no sync HTTP clients
- Validation:
  - mocked request shape tests
  - latency is returned and non-negative
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `DISPATCH-01` - Prompt Rendering and Raw I/O Persistence

- Status: `[ ]`
- Scope: `agentbench/dispatcher/dispatcher.py`
- Depends on: `ADAPTERS-01`, `CASES-02`, `WORKFLOW-01`
- Goal: Render prompts from case fixtures, invoke adapters, and persist raw I/O files.
- Deliverables:
  - prompt rendering using supported placeholders only
  - adapter resolution by `agent_id`
  - timeout handling
  - raw I/O file write with `case_set_id` and `case_id`
- Constraints:
  - no scoring logic
  - no case mutation
- Validation:
  - rendered prompt includes ticket and diff content
  - timeout emits `workflow.step.timed_out`
  - raw I/O file matches the SDD shape
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `ORCH-01` - Benchmark Expansion and FSM

- Status: `[ ]`
- Scope: `agentbench/orchestrator/orchestrator.py`
- Depends on: `WORKFLOW-01`, `STORAGE-01`, `STORAGE-02`, `EVENTS-01`
- Goal: Expand one benchmark request into one run per `(agent_id, case_id)` and drive step progression for each run.
- Deliverables:
  - benchmark expansion logic
  - run initialization
  - FSM transitions
  - step progression on `step.scored`
- Constraints:
  - no direct calls into dispatcher or scoring modules
  - preserve `correlation_id = run_id`
- Validation:
  - benchmark with 2 agents and N cases yields `2 * N` runs
  - a completed last step emits `workflow.completed`
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `AGG-01` - Per-Case and Per-Agent Reporting

- Status: `[ ]`
- Scope: `agentbench/aggregator/aggregator.py`
- Depends on: `MODELS-01`, `SCORING-03`, `STORAGE-01`, `STORAGE-02`
- Goal: Accumulate step scores into run reports and benchmark reports.
- Deliverables:
  - `RunReport` generation on `workflow.completed`
  - `BenchmarkReport` generation when all runs complete
  - per-case score matrix
  - per-agent latency and average score aggregation
- Constraints:
  - no agent-specific branching
- Validation:
  - reports persist with expected case metadata
  - benchmark completion waits for all `(agent_id, case_id)` runs
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `API-01` - Benchmark API

- Status: `[ ]`
- Scope: `agentbench/api/app.py`, `agentbench/api/routers/benchmarks.py`, `agentbench/api/routers/workflows.py`
- Depends on: `ORCH-01`, `AGG-01`
- Goal: Expose benchmark execution and reporting endpoints for the active workflow.
- Deliverables:
  - `POST /benchmarks`
  - `GET /benchmarks/{benchmark_id}`
  - `GET /benchmarks/{benchmark_id}/runs`
  - workflow registration and publish endpoints if already part of the existing design
- Constraints:
  - no fixture authoring endpoints
- Validation:
  - benchmark create request accepts `case_set_id`
  - in-progress benchmark returns `202`
  - completed benchmark returns `BenchmarkReport`
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `CLI-01` - Operator CLI

- Status: `[ ]`
- Scope: `cli/main.py`
- Depends on: `ORCH-01`, `AGG-01`, `CASES-02`
- Goal: Expose the benchmark workflow through a minimal CLI surface.
- Deliverables:
  - `run`
  - `report`
  - `seed`
  - `rescore`
  - `list-cases`
- Constraints:
  - no fixture editing commands
- Validation:
  - each command parses expected arguments
  - `list-cases` reflects enabled manifest cases
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `MAIN-01` - Runtime Wiring

- Status: `[ ]`
- Scope: `agentbench/main.py`
- Depends on: `EVENTS-01`, `DISPATCH-01`, `SCORING-03`, `ORCH-01`, `AGG-01`
- Goal: Wire the service coroutines into the single-process async runtime.
- Deliverables:
  - startup wiring for Redis bus, storage, orchestrator, dispatcher, scoring engine, aggregator
  - clean shutdown handling
- Constraints:
  - single process only
  - no service-to-service direct calls
- Validation:
  - app process starts under Docker Compose
  - all consumers subscribe to expected streams
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `TEST-UNIT-01` - Case Loader Tests

- Status: `[ ]`
- Scope: `tests/unit/test_case_loader.py`
- Depends on: `CASES-02`, `FIXTURES-01`
- Goal: Lock down fixture loading behavior.
- Validation:
  - happy path
  - malformed manifest
  - missing fixture file
  - disabled case filtering
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `TEST-UNIT-02` - Findings Scoring Tests

- Status: `[ ]`
- Scope: `tests/unit/test_finding_match.py`
- Depends on: `SCORING-01`, `FIXTURES-01`
- Goal: Lock down deterministic scoring.
- Validation:
  - exact match path
  - optional finding path
  - false positive penalty
  - disallowed finding penalty
  - malformed JSON path
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `TEST-UNIT-03` - Adapter and Judge Tests

- Status: `[ ]`
- Scope: `tests/unit/test_adapters.py`, `tests/unit/test_llm_judge.py`
- Depends on: `ADAPTERS-01`, `SCORING-02`
- Goal: Lock down outbound provider contracts and summary judging behavior.
- Validation:
  - provider request shape
  - provider response parsing
  - judge success path
  - judge parse failure path
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `TEST-INT-01` - End-to-End Pipeline Test

- Status: `[ ]`
- Scope: `tests/integration/test_pipeline.py`
- Depends on: `MAIN-01`, `API-01`, `CLI-01`
- Goal: Validate the benchmark end-to-end against the active workflow.
- Validation:
  - benchmark can be started
  - raw I/O files are written
  - step scores are persisted
  - final benchmark report is generated
- Constraints:
  - mark as integration
  - excluded from CI by default
- Evidence:
  - changed files:
  - validation run:
  - notes:

### `README-01` - Portfolio Presentation

- Status: `[ ]`
- Scope: `README.md`
- Depends on: `TEST-INT-01`
- Goal: Turn the implementation into a strong portfolio artifact.
- Deliverables:
  - architecture narrative
  - seeded fixture explanation
  - benchmark results table
  - re-scoring demo
  - one sample case walkthrough
- Validation:
  - README satisfies Section 20 of the SDD
- Evidence:
  - changed files:
  - validation run:
  - notes:

---

## 4. Progress Validation Checklist

Before marking a task complete, verify:
- the task scope matches the files changed
- no forbidden anti-pattern from the SDD was introduced
- targeted tests were added or updated where required
- the validation command was actually run
- any new follow-up dependency was added to this board if necessary

This document should remain the implementation coordination layer until the project reaches the SDD definition of done.
