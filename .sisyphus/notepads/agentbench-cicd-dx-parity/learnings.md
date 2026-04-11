# Learnings

## [2026-04-11 00:00:00] Task: session-initialization

## [2026-04-11] Task 1: align pytest/coverage contract in pyproject.toml
- Added `--strict-markers` to `[tool.pytest.ini_options] addopts` (line 103)
- Added `branch = true` to `[tool.coverage.run]` (line 114)
- Added `[tool.coverage.xml]` with `output = "coverage.xml"` (lines 124-125)
- Added `[tool.coverage.html]` with `directory = "htmlcov"` (lines 127-128)
- No `fail_under` or `--cov-fail-under` — report-only coverage as specified
- pytest-asyncio 1.3.0 deprecation warning on `asyncio_default_fixture_loop_scope` — existing config kept, not in scope
- All 330 unit tests pass with coverage reports generated successfully

## [2026-04-11] Task 2: add minimal .gitleaks.toml
- Minimal TOML with `[extend] useDefault = true` inherits all 200+ built-in rules
- Single allowlist path `\.env\.example$` — regex-anchored, dot-escaped
- No directory-wide or wildcard exclusions to maintain full scan coverage
- useDefault=true is canonical gitleaks baseline per upstream docs

## [2026-04-11] Task 3: Add Just bootstrap and runtime recipes
- justfile uses `docker compose` (v2 plugin syntax, not legacy `docker-compose`)
- `set dotenv-load := false` — dotenv not auto-loaded by just; `load_dotenv()` handled in Python
- `logs` recipe accepts variadic `*args` with default `"--tail 50 -f"`
- `init` chains sync → start (with 5s health wait) → seed
- Scope limited to bootstrap/runtime only; quality/test/ci deferred to later tasks

## [2026-04-11] Task 4: Add Just quality and test recipes
- 10 new recipes added (test, test-unit, test-integration, lint, format, typecheck, coverage, ci-pr, ci-integration, precommit)
- `test-integration` uses shell guard `if [ -z "$AGENTBENCH_INTEGRATION_TEST" ]` for hard gating (not just)
- `ci-integration` sets env var inline: `AGENTBENCH_INTEGRATION_TEST=1 uv run pytest ...`
- `ci-pr` chains lint → typecheck → coverage; no integration path
- `precommit` chains lint → format → typecheck → test-unit; all fast local checks
- Total recipe count: 23 (13 existing + 10 new)
- just `@` prefix silences command echo for shell guards (cosmetic)

## [2026-04-11] Task 7: Add .pre-commit-config.yaml
- 4 repos: gitleaks, ruff-pre-commit, pre-commit-hooks, local (mypy)
- ruff hook order critical: lint (with --fix) must precede ruff-format
- local mypy hook uses `pass_filenames: false` + `always_run: true` for whole-repo type checking
- gitleaks v8.21.2, ruff-pre-commit v0.9.6, pre-commit-hooks v5.0.0 pinned
- mypy entry is `uv run mypy .` (dot-scoped, not file-scoped)

## [2026-04-11] Task 4: Fix pass (retry)
- `coverage` was missing `--cov=cli` — added alongside `--cov=agentbench`
- `ci-integration` depended on `runtime` and `api` recipes which are foreground-blocking — rewrote as inline bash with background process launch, /health readiness loop (30 iterations × 2s = 60s), trap EXIT cleanup, and explicit AGENTBENCH_INTEGRATION_TEST=1 gating
- `ci-integration` now depends only on `sync start` (non-blocking: install deps + docker compose up)
- just shebang recipes (`#!/usr/bin/env bash`) enable multi-line shell logic within just's shebang recipe support

## [2026-04-11] Task 5: Add PR CI workflow in .github/workflows/ci.yml
- Created ci.yml with two jobs: secret-scan (gitleaks) + quality (lint/typecheck/coverage)
- Triggers: pull_request (all) + push to main
- secret-scan uses actions/checkout@v4 with fetch-depth: 0 for full-history gitleaks scan
- quality job installs uv via astral-sh/setup-uv@v4, syncs dev deps, then runs: ruff check, ruff format --check, mypy, pytest tests/unit with --cov=agentbench --cov=cli
- Coverage artifacts (coverage.xml + htmlcov/) uploaded with if: always() and 14-day retention
- Command parity maintained with justfile ci-pr recipe (lint → typecheck → coverage)
- No integration tests, no coverage thresholds, no AGENTBENCH_INTEGRATION_TEST references
- grep -F with leading dashes requires `grep -F --` to avoid option parsing

## 2026-04-11 18:09:10Z — Task 6 integration workflow
- Implemented isolated `.github/workflows/integration.yml` with triggers limited to `push` on `main` and `workflow_dispatch`.
- Mirrored readiness semantics from `just ci-integration`: background runtime/API start, `/health` polling (30x, 2s), then gated integration selector execution.
- Used GitHub `services` for MongoDB/Redis with host-published ports and health checks to support host-run Python processes.

## [2026-04-11] Task 5: Fix pass (SARIF output + upload)
- gitleaks-action args override needed: `detect --source . --report-format sarif --report-path gitleaks.sarif`
- SARIF upload via `github/codeql-action/upload-sarif@v3` guarded with `always() && hashFiles('gitleaks.sarif') != ''`
- `continue-on-error: true` ensures SARIF upload doesn't fail the job if file is empty/missing
- hashFiles guard prevents action error when no SARIF generated (clean repos)

## [2026-04-11] Task 8: Add CONTRIBUTING.md with CI-parity setup instructions
- Created CONTRIBUTING.md with 185 lines covering all required sections
- Prerequisites table: Python 3.12+, Docker Compose v2, uv, just
- Local setup: uv sync --dev, uv run pre-commit install, just init
- Daily workflow: just lint, just typecheck, just test-unit, just coverage
- Integration testing section explicitly states gated requirements (AGENTBENCH_INTEGRATION_TEST=1)
- Clear separation: runtime + API must be running for integration tests
- Pre-commit command: just precommit (chains lint → format → typecheck → test-unit)
- CI parity: just ci-pr (PR gate) and just ci-ci-integration (full stack)
- All documented commands verified against justfile - 100% match
- No migration references included as per requirements
- Evidence files created: task-8-contributing.txt, task-8-contributing-error.txt

## Task 9: README CI Badge Update (2026-04-11)

### Pattern: GitHub Actions Badge Format
- Standard format: `[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)`
- Place after existing badges, before project description
- Use same style as other badges for consistency

### Pattern: Concise Testing Section
- Add brief pointer to CONTRIBUTING.md for full details
- Keep quick reference table for immediate use
- Avoid duplicating setup instructions that belong in CONTRIBUTING

### Successful Approach
1. Read existing badge section to understand placement
2. Add CI badge on new line after license badge
3. Insert CONTRIBUTING.md reference at start of Testing section
4. Verify no coverage badge or codecov references added
