# Issues

## [2026-04-11 00:00:00] Task: session-initialization

## [2026-04-11] Task 1: align pytest/coverage contract in pyproject.toml
Blocker status: None
- No blockers encountered
- pytest-asyncio 1.3.0 emits deprecation warning about `asyncio_default_fixture_loop_scope` key being moved to `pytest.ini_options` — cosmetic only, does not affect functionality

## [2026-04-11] Task 2: add minimal .gitleaks.toml
Blocker status: None
- No blockers encountered. Config created and verified on first attempt.

## [2026-04-11] Task 3: Add Just bootstrap and runtime recipes
Blocker status: None
- No blockers. Previous attempt wrote to wrong checkout; absolute-path targeting resolved.
- `just --list` confirms all 13 recipes parsed correctly.

## [2026-04-11] Task 4: Add Just quality and test recipes
Blocker status: None
- No blockers. All recipes parse and list correctly.
- just does not have native env-var gating; shell guard used for test-integration is correct approach.

## [2026-04-11] Task 7: Add .pre-commit-config.yaml
Blocker status: None
- No blockers. Config created and all 13 assertions passed on first attempt.

## [2026-04-11] Task 4: Fix pass (retry)
Blocker status: None (resolved)
- Original `coverage` recipe missing `--cov=cli` — fixed by adding both cov targets
- Original `ci-integration` depended on foreground-blocking `runtime`/`api` recipes — fixed with inline bash background process management
- Lesson: just recipe dependencies block sequentially; long-running services must be backgrounded in shebang recipes

## [2026-04-11] Task 5: Add PR CI workflow in .github/workflows/ci.yml
Blocker status: None
- No blockers. All 23 assertions passed on first attempt (after fixing grep -F escaping in test script).
- gitleaks action may require GITLEAKS_LICENSE secret for full rule set; GITHUB_TOKEN covers OSS repos
