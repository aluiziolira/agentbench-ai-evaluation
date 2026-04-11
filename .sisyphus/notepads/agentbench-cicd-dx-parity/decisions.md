# Decisions

## Worktree Path Selection
- **Date**: 2026-04-11
- **Decision**: Use `/home/aluizio/aluizio-projects/worktrees/agentbench-cicd-dx-parity` as the dedicated worktree for the `agentbench-cicd-dx-parity` plan.
- **Rationale**: Follows the established convention of placing worktrees under `~/aluizio-projects/worktrees/<plan-name>`, keeping implementation work isolated from the main repo checkout. This prevents branch-switching conflicts and allows the CI/CD parity work to proceed independently.

## 2026-04-11 18:09:10Z — Task 6 integration workflow decisions
- Chose `services:` over docker-compose execution in workflow to guarantee host-visible MongoDB/Redis for API/runtime started directly on runner.
- Kept explicit selector input (`inputs.test_selector`) with default `tests/integration/test_pipeline.py` to preserve gated, targeted execution.
- Added `if: always()` to both artifact upload and process cleanup to preserve debug logs even on readiness/test failure.
