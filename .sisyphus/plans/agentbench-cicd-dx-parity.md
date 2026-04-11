# AgentBench CI/CD and DevOps Parity Plan

## TL;DR
> **Summary**: Add a PR-safe CI pipeline, a separately gated integration workflow, pre-commit enforcement, a complete Just-based command surface, report-only coverage publishing, and contributor-facing docs without changing AgentBench runtime architecture.
> **Deliverables**:
> - `.github/workflows/ci.yml`
> - `.github/workflows/integration.yml`
> - `.gitleaks.toml`
> - `.pre-commit-config.yaml`
> - `justfile`
> - `pyproject.toml` pytest/coverage updates
> - `CONTRIBUTING.md`
> - `README.md` CI badge update
> **Effort**: Medium
> **Parallel**: YES - 3 waves
> **Critical Path**: config contract → workflow files → docs/badges → verification

## Context
### Original Request
- Bring CI/CD and DevOps improvements from `mini-agent-telemetry-lab` into `agentbench-ai-evaluation`.
- Keep these policy decisions fixed:
  - Unit tests run on every PR.
  - Integration tests run in a separate gated workflow triggered by `workflow_dispatch` and `push` to `main` only.
  - Keep current whole-repo strict mypy posture.
  - Add coverage reporting now, but keep CI report-only initially.
- Deliver a structured markdown plan with immediate-action templates, implementation order, success criteria, atomic commits, and TDD-oriented execution.

### Interview Summary
- Current repo already has strict `ruff`, strict `mypy`, `pytest-asyncio`, integration gating with `AGENTBENCH_INTEGRATION_TEST=1`, a multi-stage Dockerfile, and Docker Compose for MongoDB + Redis.
- Missing pieces are GitHub Actions, pre-commit hooks, gitleaks config, a task runner, coverage publication, CONTRIBUTING guidance, and README CI badge wiring.
- Donor repo patterns are useful structurally, but Django/Postgres assumptions must be removed completely.
- Decision: keep pytest and coverage configuration centralized in `pyproject.toml`; do **not** add a standalone `pytest.ini` unless execution finds a concrete tool incompatibility.

### Metis Review (gaps addressed)
- Prevent donor-stack leakage: no `manage.py`, no `DATABASE_URL`, no Postgres service, no migration job, no Django language in templates.
- Avoid local/CI drift: define the final command contract in `justfile`, and make workflows mirror the same commands.
- Keep PR workflow fast and deterministic: secret scan, Ruff lint, Ruff format check, whole-repo mypy, unit tests, and coverage artifacts only.
- Keep integration workflow isolated: provision MongoDB + Redis for host-based processes, start API/runtime explicitly, wait on `/health`, capture logs on failure, always tear down.
- Keep coverage non-blocking: no `fail_under`, no coverage badge until a publishing backend is actually wired.

## Work Objectives
### Core Objective
Introduce a production-style CI/CD and developer-experience layer that matches AgentBench's actual FastAPI + MongoDB + Redis architecture, while keeping PR feedback fast and quarantining slow/secret-dependent integration runs.

### Deliverables
- PR CI workflow template with gitleaks, Ruff, mypy, unit tests, and coverage artifact upload.
- Separate integration workflow template with manual dispatch + `main` branch push gating.
- Minimal `.gitleaks.toml` allowlist tuned for example files only.
- `.pre-commit-config.yaml` that mirrors PR-safe quality gates.
- Complete `justfile` with 15-20 recipes for local development and CI parity.
- `pyproject.toml` updates for stricter pytest signaling and richer coverage output.
- `CONTRIBUTING.md` template for local setup, pre-commit install, and CI-equivalent commands.
- README CI badge update.

### Definition of Done (verifiable conditions with commands)
- `uv run ruff check .` passes locally.
- `uv run ruff format --check .` passes locally.
- `uv run mypy .` passes locally.
- `uv run pytest tests/unit -q --cov=agentbench --cov=cli --cov-report=term-missing --cov-report=xml --cov-report=html` passes locally.
- `pre-commit run --all-files` passes locally.
- `just --list` shows the required recipes.
- PR workflow YAML contains `pull_request` trigger and separate `secret-scan` + `quality` jobs.
- Integration workflow YAML contains `workflow_dispatch` and `push` to `main`, provisions MongoDB + Redis, starts API/runtime, and runs integration tests only with `AGENTBENCH_INTEGRATION_TEST=1`.

### Must Have
- Single-source config in `pyproject.toml` for pytest + coverage.
- Fast PR pipeline that excludes integration tests.
- Gated integration pipeline that requires secrets and infra readiness.
- Coverage report generation without merge blocking.
- Atomic commit sequence.
- TDD-oriented execution notes.

### Must NOT Have
- No Django/Postgres-specific text, commands, services, or settings.
- No `pytest.ini` duplication unless a concrete blocker forces extraction from `pyproject.toml`.
- No coverage threshold enforcement in the first rollout.
- No integration tests inside the default PR workflow.
- No secrets committed or broad gitleaks allowlists.

## Verification Strategy
> ZERO HUMAN INTERVENTION - all verification is agent-executed.
- Test decision: **tests-after**, with TDD-oriented sequencing per phase (define failing command contract first, make local commands pass, then wire CI to those commands).
- QA policy: Every task includes at least one happy-path and one failure/edge-case scenario.
- Evidence path: `.sisyphus/evidence/task-{N}-{slug}.{ext}`.

## Execution Strategy
### Parallel Execution Waves
Wave 1: config + command contract (`pyproject.toml`, `.gitleaks.toml`, `justfile`)

Wave 2: enforcement (`ci.yml`, `integration.yml`, `.pre-commit-config.yaml`)

Wave 3: documentation polish (`CONTRIBUTING.md`, `README.md`)

### Dependency Matrix (full, all tasks)
| Task | Depends On |
|---|---|
| 1. Pytest/Coverage contract | none |
| 2. Gitleaks config | none |
| 3. Justfile bootstrap/runtime recipes | none |
| 4. Justfile quality/test recipes | 1, 3 |
| 5. PR CI workflow | 1, 2, 4 |
| 6. Integration workflow | 1, 3, 4 |
| 7. Pre-commit hooks | 1, 2 |
| 8. CONTRIBUTING.md | 3, 4, 7 |
| 9. README badge + CI section | 5, 6, 8 |

### Agent Dispatch Summary
| Wave | Tasks | Recommended Categories |
|---|---:|---|
| 1 | 4 | quick, unspecified-low |
| 2 | 3 | quick, unspecified-high |
| 3 | 2 | writing, quick |

## Executive Summary
AgentBench already has the application-side rigor needed for CI/CD: strict lint/type settings, a meaningful unit/integration split, and containerized local infrastructure. The missing work is orchestration and enforcement. This plan ports the proven shape of `mini-agent-telemetry-lab` into AgentBench while intentionally replacing every Django/Postgres assumption with FastAPI + MongoDB + Redis equivalents. The rollout keeps PR checks fast, moves high-friction integration runs into an isolated gated workflow, and defers coverage enforcement until the workflow is stable.

## Phase 1: CI/CD Foundation (PRIORITY 1)
### Files
- `.github/workflows/ci.yml`
- `.github/workflows/integration.yml`
- `.gitleaks.toml`

### Decisions
- PR CI runs on `pull_request` and `push` to `main`; integration stays out of PR CI.
- Gitleaks uses full git history via `fetch-depth: 0` and uploads SARIF for code-scanning visibility.
- Integration workflow uses GitHub Actions `services:` for MongoDB and Redis rather than local Docker Compose because host-side Python processes need published service ports.
- API and runtime start as background host processes inside the integration job; the job waits on `http://127.0.0.1:8000/health` before testing.

### `.github/workflows/ci.yml` template
```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  secret-scan:
    runs-on: ubuntu-latest
    permissions:
      actions: read
      contents: read
      security-events: write
    steps:
      - name: Check out repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run Gitleaks
        run: |
          docker run --rm \
            -v "${{ github.workspace }}:/repo" \
            -w /repo \
            -e GIT_CONFIG_COUNT=1 \
            -e GIT_CONFIG_KEY_0=safe.directory \
            -e GIT_CONFIG_VALUE_0=/repo \
            ghcr.io/gitleaks/gitleaks:v8.24.2 \
            git . \
            --config .gitleaks.toml \
            --report-format sarif \
            --report-path gitleaks.sarif \
            --exit-code 1

      - name: Upload Gitleaks SARIF
        if: ${{ always() && hashFiles('gitleaks.sarif') != '' }}
        continue-on-error: true
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: gitleaks.sarif

  quality:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install uv
        run: python -m pip install uv

      - name: Sync dependencies
        run: uv sync --dev

      - name: Ruff lint
        run: uv run ruff check .

      - name: Ruff format check
        run: uv run ruff format --check .

      - name: MyPy typecheck
        run: uv run mypy .

      - name: Run unit tests with coverage
        run: |
          uv run pytest tests/unit -q \
            --cov=agentbench \
            --cov=cli \
            --cov-report=term-missing \
            --cov-report=xml:coverage.xml \
            --cov-report=html:htmlcov

      - name: Upload coverage XML
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: coverage-xml
          path: coverage.xml

      - name: Upload HTML coverage report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: htmlcov
          path: htmlcov/
```

### `.github/workflows/integration.yml` template
```yaml
name: Integration

on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      test_selector:
        description: "Pytest selector for gated integration runs"
        required: false
        default: "tests/integration/test_pipeline.py"

permissions:
  contents: read

concurrency:
  group: integration-${{ github.ref }}
  cancel-in-progress: true

jobs:
  integration-tests:
    runs-on: ubuntu-latest
    services:
      mongodb:
        image: mongo:7
        ports:
          - 27017:27017
        env:
          MONGO_INITDB_ROOT_USERNAME: admin
          MONGO_INITDB_ROOT_PASSWORD: changeme
          MONGO_INITDB_DATABASE: agentbench
        options: >-
          --health-cmd "mongosh --eval \"db.adminCommand('ping')\""
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    env:
      MONGO_USER: admin
      MONGO_PASSWORD: changeme
      MONGO_DB: agentbench
      MONGODB_URI: mongodb://admin:changeme@127.0.0.1:27017/agentbench?authSource=admin
      REDIS_URL: redis://127.0.0.1:6379/0
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      AGENTBENCH_INTEGRATION_TEST: "1"

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install uv
        run: python -m pip install uv

      - name: Sync dependencies
        run: uv sync --dev

      - name: Validate required secrets
        run: |
          test -n "$OPENAI_API_KEY"
          test -n "$ANTHROPIC_API_KEY"

      - name: Start runtime worker
        run: nohup uv run python -m agentbench.main > runtime.log 2>&1 &

      - name: Start API server
        run: nohup uv run python start_api.py > api.log 2>&1 &

      - name: Wait for API readiness
        run: |
          for i in $(seq 1 30); do
            if curl -fsS http://127.0.0.1:8000/health > /dev/null; then
              exit 0
            fi
            sleep 2
          done
          echo "API failed readiness check"
          exit 1

      - name: Run gated integration tests
        run: uv run pytest "${{ inputs.test_selector || 'tests/integration/test_pipeline.py' }}" -q

      - name: Upload integration logs
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: integration-logs
          path: |
            api.log
            runtime.log

      - name: Stop background processes
        if: always()
        run: |
          pkill -f "python -m agentbench.main" || true
          pkill -f "python start_api.py" || true
```

### `.gitleaks.toml` template
```toml
[extend]
useDefault = true

[allowlist]
paths = [
  '''\.env\.example''',
]
```

### Phase 1 notes
- Start with the minimal allowlist above; only expand after a real false positive is captured in CI evidence.
- Keep CI commands explicit even after `justfile` is added; then mirror them 1:1 in `just ci-pr` and `just ci-integration`.

## Phase 2: Pre-commit Hooks (PRIORITY 2)
### Files
- `.pre-commit-config.yaml`

### `.pre-commit-config.yaml` template
```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.24.2
    hooks:
      - id: gitleaks

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.9
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: check-yaml
      - id: check-toml
      - id: check-json
      - id: check-merge-conflict
      - id: end-of-file-fixer
      - id: trailing-whitespace

  - repo: local
    hooks:
      - id: mypy
        name: mypy (whole repo)
        entry: uv run mypy .
        language: system
        types: [python]
        pass_filenames: false
        always_run: true
```

### Installation steps
1. `uv sync --dev`
2. `uv run pre-commit install`
3. `uv run pre-commit run --all-files`
4. Fix all findings before enabling branch protection rules.

### Phase 2 notes
- Hook order matters: keep Ruff lint/fix before `ruff-format`.
- Keep mypy whole-repo to match the stated policy.
- Do not make pre-commit stricter than PR CI for Python quality checks.

## Phase 3: Task Runner (PRIORITY 3)
### Files
- `justfile`

### Decisions
- Use `docker compose`, not `docker-compose`, for modern Compose v2 parity.
- Replace telemetry-lab migration steps with `agentbench seed`; AgentBench has seeding, not schema migrations.
- Make the justfile the documented command contract for local execution and CI parity.

### `justfile` template
```just
set dotenv-load := true

default:
    just --list

# Sync the local development environment
sync:
    uv sync --dev

# First-time setup: env, services, seed data
init:
    uv sync --dev
    docker compose up -d mongodb redis
    just seed

# Start backing services for local development
start:
    docker compose up -d mongodb redis

# Stop backing services
stop:
    docker compose down

# Restart backing services cleanly
restart:
    docker compose down
    docker compose up -d mongodb redis

# Show service/container status
status:
    docker compose ps

# Stream container logs
logs:
    docker compose logs -f mongodb redis

# Seed workflows and fixtures into MongoDB
seed:
    uv run python -m cli.main seed

# Start the runtime worker locally
runtime:
    uv run python -m agentbench.main

# Start the API locally
api:
    uv run python start_api.py

# Run the full local demo flow
demo:
    just seed
    uv run python -m cli.main run --workflow wf_pr_review_v1 --case-set pr_review_cases_v1 --agents gpt-4o-mini --agents claude-haiku-4-5

# Run all tests
test:
    uv run pytest -q

# Run unit tests only
test-unit:
    uv run pytest tests/unit -q

# Run gated integration tests only
test-integration:
    AGENTBENCH_INTEGRATION_TEST=1 uv run pytest tests/integration/test_pipeline.py -q

# Run Ruff lint + format check
lint:
    uv run ruff check .
    uv run ruff format --check .

# Apply Ruff formatting
format:
    uv run ruff format .

# Run whole-repo strict mypy
typecheck:
    uv run mypy .

# Run unit coverage in report-only mode
coverage:
    uv run pytest tests/unit -q --cov=agentbench --cov=cli --cov-report=term-missing --cov-report=xml:coverage.xml --cov-report=html:htmlcov

# Run PR-equivalent checks locally
ci-pr:
    just lint
    just typecheck
    just coverage

# Run integration-equivalent checks locally
ci-integration:
    #!/usr/bin/env bash
    set -euo pipefail
    just start
    uv run python -m agentbench.main > runtime.log 2>&1 &
    runtime_pid=$!
    uv run python start_api.py > api.log 2>&1 &
    api_pid=$!
    trap 'kill $runtime_pid $api_pid || true' EXIT
    for i in $(seq 1 30); do
        if curl -fsS http://127.0.0.1:8000/health > /dev/null; then
            break
        fi
        sleep 2
    done
    AGENTBENCH_INTEGRATION_TEST=1 uv run pytest tests/integration/test_pipeline.py -q

# Run all pre-commit hooks against tracked files
precommit:
    uv run pre-commit run --all-files

# Remove local transient artifacts
clean:
    rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml
```

### Phase 3 notes
- `demo` runs the benchmark CLI after seeding; contributor docs must still explain that API/runtime processes and provider keys are preconditions.
- Keep recipe names stable before wiring CONTRIBUTING docs and README snippets.

## Phase 4: Test & Coverage Configuration (PRIORITY 4)
### Files
- `pyproject.toml`
- `pytest.ini` (**not created by default**)

### Decision
Keep pytest and coverage configuration in `pyproject.toml`. Do **not** add `pytest.ini` unless the executor finds a concrete tool that cannot read the existing `tool.pytest.ini_options` section. If such a blocker appears, extract the fallback `pytest.ini` template below verbatim and remove the duplicated `tool.pytest.ini_options` section in the same commit.

### Preferred `pyproject.toml` updates
```toml
[tool.pytest.ini_options]
minversion = "8.0"
asyncio_mode = "auto"
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --tb=short --strict-markers"
markers = [
  "integration: requires MongoDB, Redis, running API/runtime processes, and real provider keys",
]

[tool.coverage.run]
branch = true
source = ["agentbench", "cli"]
omit = ["tests/*", "*/tests/*"]

[tool.coverage.report]
show_missing = true
skip_covered = false
exclude_lines = [
  "pragma: no cover",
  "def __repr__",
  "raise AssertionError",
  "raise NotImplementedError",
]

[tool.coverage.xml]
output = "coverage.xml"

[tool.coverage.html]
directory = "htmlcov"
```

### Fallback `pytest.ini` template (use only if `pyproject.toml` proves insufficient)
```ini
[pytest]
minversion = 8.0
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short --strict-markers
markers =
    integration: requires MongoDB, Redis, running API/runtime processes, and real provider keys
```

### Phase 4 notes
- Coverage stays report-only: no `fail_under`, no `--cov-fail-under`, no merge blocking on percentage.
- The unit-test coverage command remains explicit in CI and `just coverage`; do not make all default test runs slower by injecting coverage into `addopts`.

## Phase 5: Documentation (PRIORITY 5)
### Files
- `CONTRIBUTING.md`
- `README.md`

### `CONTRIBUTING.md` template
````md
# Contributing

## Prerequisites
- Python 3.12+
- Docker with Compose v2
- `uv`
- `just`

## Local setup
```bash
uv sync --dev
uv run pre-commit install
just init
```

## Daily workflow
```bash
just lint
just typecheck
just test-unit
just coverage
```

## Integration testing
Integration tests are gated because they require MongoDB, Redis, the local runtime worker, the API server, and real provider API keys.

```bash
just start
# terminal 2
just runtime
# terminal 3
just api
# terminal 4
OPENAI_API_KEY=... ANTHROPIC_API_KEY=... just test-integration
```

## Pre-commit
```bash
uv run pre-commit run --all-files
```

## CI parity
- PR-safe checks: `just ci-pr`
- Gated integration checks: `just ci-integration`
````

### README badge snippet
```md
[![CI](https://github.com/<owner>/<repo>/actions/workflows/ci.yml/badge.svg)](https://github.com/<owner>/<repo>/actions/workflows/ci.yml)
```

### Phase 5 notes
- Add the CI badge only after the workflow filename is finalized as `ci.yml`.
- Do **not** add a coverage badge until coverage is published to a real backend such as Codecov or an equivalent service.

## Implementation Order
1. **Baseline config contract**: update `pyproject.toml` for strict markers + richer coverage output, add `.gitleaks.toml`, create the full `justfile` contract.
2. **PR workflow**: add `ci.yml` using the exact lint/type/unit coverage commands already proven locally.
3. **Integration workflow**: add `integration.yml` with MongoDB + Redis services, host-side API/runtime startup, readiness wait, logs, and teardown.
4. **Pre-commit**: add `.pre-commit-config.yaml` after the quality commands are stable.
5. **Docs**: add `CONTRIBUTING.md`, then add the README CI badge and CI section after filenames and command names stop moving.

## Atomic Commit Strategy
1. `chore(devx): align pytest and coverage config for CI parity`
2. `chore(security): add gitleaks config and minimal allowlist`
3. `chore(devx): add justfile command surface for local and CI workflows`
4. `ci(pr): add PR workflow for secrets, lint, typecheck, unit tests, and coverage artifacts`
5. `ci(integration): add gated integration workflow with services, readiness checks, and logs`
6. `chore(quality): add pre-commit hooks mirroring PR-safe checks`
7. `docs(ci): add contributing guide and README CI badge`

## TDD-Oriented Execution Model
- **Red**: add or update the local command first (`just lint`, `just typecheck`, `just coverage`, `just test-integration`) and confirm it fails for the right reason before editing workflow YAML.
- **Green**: make the local command pass, then wire the exact same command into GitHub Actions.
- **Refactor**: once the workflow passes, align docs and pre-commit so contributors hit the same checks locally.

## Phase-by-Phase Success Criteria
### Phase 1
- `ci.yml` validates structurally and contains the expected triggers/jobs/coverage artifact uploads.
- `integration.yml` is gated correctly and documents required secrets and readiness behavior.
- `.gitleaks.toml` is minimal and justified by real files only.

### Phase 2
- `pre-commit run --all-files` executes gitleaks, Ruff, hygiene hooks, and whole-repo mypy.

### Phase 3
- `just --list` includes all required recipes.
- `just ci-pr` matches PR CI behavior.
- `just test-integration` uses `AGENTBENCH_INTEGRATION_TEST=1` and the integration test selector.

### Phase 4
- `pyproject.toml` remains the single config source for pytest and coverage.
- Unit coverage produces `coverage.xml` and `htmlcov/` without blocking on thresholds.

### Phase 5
- `CONTRIBUTING.md` shows reproducible local setup.
- `README.md` exposes the CI badge with the final workflow filename.

## TODOs
> Implementation + Test = ONE task. Never separate.
> EVERY task MUST have: Agent Profile + Parallelization + QA Scenarios.

- [x] 1. Align pytest and coverage contract in `pyproject.toml`

  **What to do**: Keep pytest configuration in `pyproject.toml`, add `--strict-markers`, add coverage `branch = true`, XML/HTML output sections, and keep coverage report-only with no threshold. Do not create `pytest.ini` unless a real tool incompatibility is encountered during execution.
  **Must NOT do**: Do not inject coverage into default pytest `addopts`; do not add `fail_under`; do not split pytest config across two files without a blocker.

  **Recommended Agent Profile**:
  - Category: `quick` - Reason: single-file config edit with deterministic output.
  - Skills: `[]` - No special skill required.
  - Omitted: `git-master` - No git history work is needed at this stage.

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: [4, 5, 6, 7] | Blocked By: []

  **References**:
  - Pattern: `pyproject.toml:96-121` - Existing pytest and coverage configuration to extend rather than replace.
  - Pattern: `tests/integration/test_pipeline.py:17-21` - Existing integration gate must remain opt-in.
  - Pattern: `README.md:167-196` - Current testing commands and expectations that docs/CI must stay aligned with.

  **Acceptance Criteria**:
  - [ ] `pyproject.toml` remains the only active pytest/coverage config file after the change unless a documented blocker forces `pytest.ini` extraction.
  - [ ] `uv run pytest tests/unit -q --cov=agentbench --cov=cli --cov-report=xml --cov-report=html` generates `coverage.xml` and `htmlcov/` without threshold enforcement.
  - [ ] `uv run pytest -m integration --collect-only` still recognizes the `integration` marker.

  **QA Scenarios**:
  ```
  Scenario: Unit coverage config works
    Tool: Bash
    Steps: Run `uv run pytest tests/unit -q --cov=agentbench --cov=cli --cov-report=xml --cov-report=html`; then run `python -c "from pathlib import Path; assert Path('coverage.xml').exists(); assert Path('htmlcov').exists()"`
    Expected: Pytest exits 0; both coverage outputs exist.
    Evidence: .sisyphus/evidence/task-1-pyproject-coverage.txt

  Scenario: No accidental coverage gating
    Tool: Bash
    Steps: Read `pyproject.toml` and verify there is no `fail_under` key and no `--cov-fail-under` injected into pytest defaults.
    Expected: Config remains report-only.
    Evidence: .sisyphus/evidence/task-1-pyproject-coverage-error.txt
  ```

  **Commit**: YES | Message: `chore(devx): align pytest and coverage config for CI parity` | Files: [`pyproject.toml`]

- [x] 2. Add minimal `.gitleaks.toml` for repo-safe secret scanning

  **What to do**: Create `.gitleaks.toml` by extending default rules and allowlisting only files that are intentionally non-secret examples, starting with `.env.example`. Expand allowlists only if real false positives are observed and documented.
  **Must NOT do**: Do not allowlist entire directories like `tests/` or `docs/`; do not disable default rules; do not suppress findings without evidence.

  **Recommended Agent Profile**:
  - Category: `quick` - Reason: small, isolated config addition.
  - Skills: `[]` - No special skill required.
  - Omitted: `git-master` - Commit strategy is already defined elsewhere.

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: [5, 7] | Blocked By: []

  **References**:
  - Pattern: `README.md:5-6` - Existing badges show how repo metadata is surfaced publicly; secret scanning must stay conservative.
  - External: `https://github.com/gitleaks/gitleaks` - Default rules and allowlist behavior.

  **Acceptance Criteria**:
  - [ ] `.gitleaks.toml` contains `[extend] useDefault = true`.
  - [ ] Initial allowlist contains `.env.example` only, unless a false positive is captured during execution.
  - [ ] Local or CI gitleaks scan fails on real findings instead of being muted by an overbroad allowlist.

  **QA Scenarios**:
  ```
  Scenario: Config is minimal and syntactically valid
    Tool: Bash
    Steps: Run `python - <<'PY'
from pathlib import Path
text = Path('.gitleaks.toml').read_text()
assert 'useDefault = true' in text
assert '.env.example' in text
PY`
    Expected: Assertions pass.
    Evidence: .sisyphus/evidence/task-2-gitleaks-config.txt

  Scenario: Allowlist is not overbroad
    Tool: Bash
    Steps: Read `.gitleaks.toml` and verify it does not contain `tests/.*`, `docs/.*`, or a wildcard directory allowlist unless evidence explicitly justifies it in the same commit.
    Expected: Config stays narrowly scoped.
    Evidence: .sisyphus/evidence/task-2-gitleaks-config-error.txt
  ```

  **Commit**: YES | Message: `chore(security): add gitleaks config and minimal allowlist` | Files: [`.gitleaks.toml`]

- [x] 3. Add Just bootstrap and runtime recipes

  **What to do**: Create the `justfile` with `default`, `sync`, `init`, `start`, `stop`, `restart`, `status`, `logs`, `seed`, `runtime`, `api`, `demo`, and `clean`. Keep commands aligned with the current FastAPI + MongoDB + Redis architecture and local workflow described in the README.
  **Must NOT do**: Do not introduce Django-style migrations, Postgres services, or commands that assume a monolithic web container startup path.

  **Recommended Agent Profile**:
  - Category: `quick` - Reason: single-file command wrapper with deterministic shell commands.
  - Skills: `[]` - No special skill required.
  - Omitted: `git-master` - No repository history work required.

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: [4, 6, 8] | Blocked By: []

  **References**:
  - Pattern: `docker-compose.yml:1-93` - Source of truth for local MongoDB/Redis service names and container behavior.
  - Pattern: `README.md:229-267` - Existing local run instructions for seeding, runtime, and API startup.
  - Pattern: `README.md:167-196` - Existing testing commands to mirror in just recipes.

  **Acceptance Criteria**:
  - [ ] `just --list` shows the bootstrap/runtime recipes required in this task.
  - [ ] `just init` performs `uv sync --dev`, starts MongoDB + Redis, and seeds the repository.
  - [ ] `just demo` seeds the repository and runs the documented benchmark CLI flow without introducing fake one-process shortcuts.

  **QA Scenarios**:
  ```
  Scenario: Justfile exposes the required bootstrap/runtime recipes
    Tool: Bash
    Steps: Run `just --list` and verify it includes `sync`, `init`, `start`, `stop`, `restart`, `status`, `logs`, `seed`, `runtime`, `api`, `demo`, and `clean`.
    Expected: All required recipes appear.
    Evidence: .sisyphus/evidence/task-3-just-bootstrap.txt

  Scenario: No wrong-stack commands leaked in
    Tool: Bash
    Steps: Read `justfile` and verify it does not contain `manage.py`, `DATABASE_URL`, `postgres`, or `docker-compose`.
    Expected: Only AgentBench-specific commands remain.
    Evidence: .sisyphus/evidence/task-3-just-bootstrap-error.txt
  ```

  **Commit**: YES | Message: `chore(devx): add justfile command surface for local workflows` | Files: [`justfile`]

- [x] 4. Add Just quality and test recipes

  **What to do**: Extend `justfile` with `test`, `test-unit`, `test-integration`, `lint`, `format`, `typecheck`, `coverage`, `ci-pr`, `ci-integration`, and `precommit`. Ensure every recipe mirrors the exact commands the workflows will use.
  **Must NOT do**: Do not make `test` or `ci-pr` run integration tests; do not make `ci-integration` silently skip readiness requirements.

  **Recommended Agent Profile**:
  - Category: `quick` - Reason: deterministic `justfile` follow-up once the base file exists.
  - Skills: `[]` - No special skill required.
  - Omitted: `git-master` - No git-specific operations required.

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: [5, 6, 8] | Blocked By: [1, 3]

  **References**:
  - Pattern: `pyproject.toml:96-121` - Canonical pytest and coverage config.
  - Pattern: `tests/integration/test_pipeline.py:17-43` - Required gate and runtime/API assumptions.
  - Pattern: `README.md:167-196` - Existing unit/integration command surface.

  **Acceptance Criteria**:
  - [ ] `just lint` runs Ruff check + Ruff format check only.
  - [ ] `just typecheck` runs whole-repo mypy.
  - [ ] `just coverage` runs unit tests with XML + HTML coverage outputs.
  - [ ] `just test-integration` exports `AGENTBENCH_INTEGRATION_TEST=1` and targets the integration suite only.
  - [ ] `just ci-pr` mirrors PR workflow commands and excludes integration tests.

  **QA Scenarios**:
  ```
  Scenario: PR-equivalent recipes are wired correctly
    Tool: Bash
    Steps: Run `just ci-pr` in a repo with dependencies synced.
    Expected: Ruff, mypy, and unit coverage commands run in order with no integration tests.
    Evidence: .sisyphus/evidence/task-4-just-quality.txt

  Scenario: Integration recipe stays gated
    Tool: Bash
    Steps: Read `justfile` and verify `test-integration` includes `AGENTBENCH_INTEGRATION_TEST=1` and does not call `pytest -q` broadly.
    Expected: Integration remains opt-in and targeted.
    Evidence: .sisyphus/evidence/task-4-just-quality-error.txt
  ```

  **Commit**: YES | Message: `chore(devx): add justfile quality and test recipes` | Files: [`justfile`]

- [x] 5. Add PR CI workflow in `.github/workflows/ci.yml`

  **What to do**: Implement the PR-safe workflow with `secret-scan` and `quality` jobs. Use full-history checkout for gitleaks, install dependencies with `uv`, run Ruff lint, Ruff format check, whole-repo mypy, and unit tests with coverage XML/HTML artifact upload.
  **Must NOT do**: Do not run integration tests here; do not add coverage thresholds; do not call commands that differ from `just ci-pr` or the chosen local contract.

  **Recommended Agent Profile**:
  - Category: `quick` - Reason: single YAML file plus deterministic shell steps.
  - Skills: `[]` - No special skill required.
  - Omitted: `git-master` - No git history surgery required.

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: [9] | Blocked By: [1, 2, 4]

  **References**:
  - Pattern: `pyproject.toml:69-121` - Current Ruff, mypy, pytest, and coverage truth.
  - Pattern: `.sisyphus/plans/agentbench-cicd-dx-parity.md:145-250` - Approved CI template and policy decisions in this plan.
  - External: `https://github.com/gitleaks/gitleaks` - SARIF-capable secret scanning behavior.

  **Acceptance Criteria**:
  - [ ] Workflow triggers on `pull_request` and `push` to `main`.
  - [ ] `secret-scan` uses `fetch-depth: 0` and emits `gitleaks.sarif`.
  - [ ] `quality` runs Ruff, Ruff format check, whole-repo mypy, and unit coverage commands exactly once each.
  - [ ] Coverage artifacts are uploaded with `if: always()` and no threshold enforcement exists.

  **QA Scenarios**:
  ```
  Scenario: Workflow contains the required triggers and jobs
    Tool: Bash
    Steps: Read `.github/workflows/ci.yml` and verify it contains `pull_request:`, `push:`, `secret-scan:`, and `quality:`.
    Expected: All required triggers and jobs are present.
    Evidence: .sisyphus/evidence/task-5-ci-workflow.txt

  Scenario: PR workflow remains fast and non-blocking on coverage thresholds
    Tool: Bash
    Steps: Verify `.github/workflows/ci.yml` does not contain `tests/integration`, `AGENTBENCH_INTEGRATION_TEST`, or `cov-fail-under`.
    Expected: PR workflow excludes gated integration and threshold enforcement.
    Evidence: .sisyphus/evidence/task-5-ci-workflow-error.txt
  ```

  **Commit**: YES | Message: `ci(pr): add PR workflow for secrets, lint, typecheck, unit tests, and coverage artifacts` | Files: [`.github/workflows/ci.yml`]

- [x] 6. Add gated integration workflow in `.github/workflows/integration.yml`

  **What to do**: Create the separate integration workflow with `workflow_dispatch` and `push` to `main`, provision MongoDB + Redis as GitHub Actions services, export required env vars, start runtime and API processes in the background, wait for `/health`, run gated integration tests, and upload logs on failure.
  **Must NOT do**: Do not trigger this workflow on pull requests; do not rely on the current Docker Compose file for host-side service connectivity; do not skip log capture or teardown behavior.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: multi-step workflow with infra readiness and failure-handling logic.
  - Skills: `[]` - No special skill required.
  - Omitted: `git-master` - No git-specific reasoning needed.

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: [9] | Blocked By: [1, 3, 4]

  **References**:
  - Pattern: `docker-compose.yml:1-93` - Current MongoDB/Redis settings to mirror as CI env values.
  - Pattern: `tests/integration/test_pipeline.py:17-198` - Integration test expectations, API key requirement, readiness assumptions, and target selector.
  - Pattern: `README.md:204-227` - Existing integration preconditions and runtime/API split.

  **Acceptance Criteria**:
  - [ ] Workflow triggers only on `push` to `main` and `workflow_dispatch`.
  - [ ] Job provisions MongoDB + Redis with health checks and host-visible ports.
  - [ ] Job exports `AGENTBENCH_INTEGRATION_TEST=1`, `MONGODB_URI`, and `REDIS_URL`.
  - [ ] Job starts runtime + API, waits for `http://127.0.0.1:8000/health`, then runs the integration selector.
  - [ ] Job uploads `api.log` and `runtime.log` with `if: always()`.

  **QA Scenarios**:
  ```
  Scenario: Workflow is correctly gated and provisions services
    Tool: Bash
    Steps: Read `.github/workflows/integration.yml` and verify it contains `workflow_dispatch`, `push` on `main`, `services.mongodb`, `services.redis`, readiness wait, and log upload steps.
    Expected: Gated workflow shape matches the plan.
    Evidence: .sisyphus/evidence/task-6-integration-workflow.txt

  Scenario: No PR trigger or wrong-stack infra leaks in
    Tool: Bash
    Steps: Verify `.github/workflows/integration.yml` does not contain `pull_request`, `postgres`, `DATABASE_URL`, or `manage.py`.
    Expected: Workflow remains isolated and stack-correct.
    Evidence: .sisyphus/evidence/task-6-integration-workflow-error.txt
  ```

  **Commit**: YES | Message: `ci(integration): add gated integration workflow with services, readiness checks, and logs` | Files: [`.github/workflows/integration.yml`]

- [x] 7. Add `.pre-commit-config.yaml` mirroring PR-safe quality checks

  **What to do**: Add gitleaks, Ruff, generic file hygiene hooks, and whole-repo mypy to `.pre-commit-config.yaml`. Ensure the hook order matches the plan and that local hook behavior mirrors PR CI for Python quality checks.
  **Must NOT do**: Do not add extra opinionated hooks outside scope; do not narrow mypy below the whole repo; do not add fixers that CI does not tolerate without documentation.

  **Recommended Agent Profile**:
  - Category: `quick` - Reason: isolated config file with known hook set.
  - Skills: `[]` - No special skill required.
  - Omitted: `git-master` - No git history analysis required.

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: [8] | Blocked By: [1, 2]

  **References**:
  - Pattern: `pyproject.toml:69-121` - Underlying Ruff/mypy/pytest settings the hooks must respect.
  - Pattern: `.sisyphus/plans/agentbench-cicd-dx-parity.md:344-381` - Approved pre-commit template in this plan.
  - External: `https://github.com/astral-sh/ruff-pre-commit` - Hook IDs and ordering expectations.

  **Acceptance Criteria**:
  - [ ] Hook set includes gitleaks, Ruff lint/fix, Ruff format, check-yaml, check-toml, check-json, check-merge-conflict, end-of-file-fixer, trailing-whitespace, and whole-repo mypy.
  - [ ] Ruff hook appears before `ruff-format`.
  - [ ] Mypy hook uses `uv run mypy .`, `pass_filenames: false`, and `always_run: true`.

  **QA Scenarios**:
  ```
  Scenario: Hook manifest includes the expected quality gates
    Tool: Bash
    Steps: Read `.pre-commit-config.yaml` and verify each required repo/hook ID is present.
    Expected: Hook set matches the plan exactly.
    Evidence: .sisyphus/evidence/task-7-precommit.txt

  Scenario: Hook ordering and mypy scope are preserved
    Tool: Bash
    Steps: Verify the Ruff hook precedes `ruff-format`, and verify the local mypy hook uses `uv run mypy .`, `pass_filenames: false`, and `always_run: true`.
    Expected: Local hook behavior matches PR CI intent.
    Evidence: .sisyphus/evidence/task-7-precommit-error.txt
  ```

  **Commit**: YES | Message: `chore(quality): add pre-commit hooks mirroring PR-safe checks` | Files: [`.pre-commit-config.yaml`]

- [x] 8. Add `CONTRIBUTING.md` with CI-parity setup instructions

  **What to do**: Create `CONTRIBUTING.md` covering prerequisites, `uv sync --dev`, `pre-commit install`, `just init`, daily quality commands, and the gated integration workflow. Keep every command aligned with the final `justfile` names.
  **Must NOT do**: Do not document commands that do not exist; do not imply integration tests run automatically on PRs; do not mention migrations.

  **Recommended Agent Profile**:
  - Category: `writing` - Reason: contributor-facing documentation tied to established commands.
  - Skills: `[]` - No special skill required.
  - Omitted: `git-master` - Not a git-history task.

  **Parallelization**: Can Parallel: YES | Wave 3 | Blocks: [9] | Blocked By: [3, 4, 7]

  **References**:
  - Pattern: `README.md:229-267` - Existing local setup and runtime/API split.
  - Pattern: `.sisyphus/plans/agentbench-cicd-dx-parity.md:494-530` - Approved CONTRIBUTING template in this plan.
  - Pattern: `tests/integration/test_pipeline.py:32-38` - Required secrets and why integration remains gated.

  **Acceptance Criteria**:
  - [ ] `CONTRIBUTING.md` lists prerequisites (`Python 3.12+`, Docker Compose v2, `uv`, `just`).
  - [ ] `CONTRIBUTING.md` documents `uv run pre-commit install` and `just init`.
  - [ ] `CONTRIBUTING.md` clearly states that integration tests require MongoDB, Redis, API/runtime processes, and real provider keys.

  **QA Scenarios**:
  ```
  Scenario: Contributor guide matches executable commands
    Tool: Bash
    Steps: Read `CONTRIBUTING.md` and verify all documented commands exist in `justfile` or the repo command surface.
    Expected: Documentation is executable as written.
    Evidence: .sisyphus/evidence/task-8-contributing.txt

  Scenario: Guide does not misstate CI policy
    Tool: Bash
    Steps: Verify `CONTRIBUTING.md` explicitly states integration tests are gated and does not claim they run on every PR.
    Expected: Policy text matches the user-provided decisions.
    Evidence: .sisyphus/evidence/task-8-contributing-error.txt
  ```

  **Commit**: YES | Message: `docs(ci): add contributing guide for local and CI-parity workflows` | Files: [`CONTRIBUTING.md`]

- [x] 9. Update `README.md` with final CI badge and concise CI/testing guidance

  **What to do**: Add the CI badge at the top of `README.md` using the final `ci.yml` workflow path, and add a short CI/testing note that points contributors to `CONTRIBUTING.md`. Keep coverage badge out until a real publishing backend is configured.
  **Must NOT do**: Do not add a coverage badge yet; do not reference old workflow filenames; do not duplicate long setup instructions already moved to `CONTRIBUTING.md`.

  **Recommended Agent Profile**:
  - Category: `writing` - Reason: small documentation adjustment after workflow filenames stabilize.
  - Skills: `[]` - No special skill required.
  - Omitted: `git-master` - No git expertise needed.

  **Parallelization**: Can Parallel: YES | Wave 3 | Blocks: [] | Blocked By: [5, 6, 8]

  **References**:
  - Pattern: `README.md:1-7` - Current badge block to extend.
  - Pattern: `.sisyphus/plans/agentbench-cicd-dx-parity.md:532-539` - Approved badge snippet in this plan.
  - Pattern: `CONTRIBUTING.md` - New home for detailed contribution instructions.

  **Acceptance Criteria**:
  - [ ] `README.md` includes the CI badge pointing to `actions/workflows/ci.yml`.
  - [ ] README CI/testing text links readers to `CONTRIBUTING.md` for detailed setup.
  - [ ] No coverage badge is added in this phase.

  **QA Scenarios**:
  ```
  Scenario: README exposes the final CI badge
    Tool: Bash
    Steps: Read `README.md` and verify the badge URL targets `actions/workflows/ci.yml/badge.svg`.
    Expected: Badge matches the final workflow filename.
    Evidence: .sisyphus/evidence/task-9-readme-ci-badge.txt

  Scenario: README does not overclaim coverage publishing
    Tool: Bash
    Steps: Verify `README.md` does not include `codecov.io` or any coverage badge URL.
    Expected: Coverage remains report-only until a publishing backend is added later.
    Evidence: .sisyphus/evidence/task-9-readme-ci-badge-error.txt
  ```

  **Commit**: YES | Message: `docs(ci): add README badge and CI guidance` | Files: [`README.md`]

## Final Verification Wave (MANDATORY — after ALL implementation tasks)
> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.
- [x] F1. Plan Compliance Audit — oracle
- [x] F2. Code Quality Review — unspecified-high
- [x] F3. Real Manual QA — unspecified-high (+ playwright if UI)
- [x] F4. Scope Fidelity Check — deep

## Commit Strategy
- Follow the atomic sequence above; do not squash unrelated phases together.
- Keep each commit buildable and locally verifiable with the task acceptance criteria.

## Success Criteria
- PR workflow passes on a representative branch.
- Integration workflow passes when dispatched with valid secrets on `main`.
- Local developer workflow is documented, repeatable, and CI-aligned.
