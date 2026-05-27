# PRD 0005 — CI for both `main` (OpenRouter) and `claude-subscription` branches

## Problem Statement

The repository now has two long-lived branches representing two LLM backends:

- **`main`** — uses OpenRouter via `langchain-openai`, gated by `OPENROUTER_API_KEY`.
- **`claude-subscription`** — uses the Claude Pro/Max OAuth subscription via `claude-agent-sdk`, with `claude -p` subprocess and `ANTHROPIC_API_KEY` as fallbacks (see ADR-0001).

CI today is configured only for `main`'s behavior:

- `.github/workflows/daily_pipeline.yml` and `.github/workflows/weekly_tactics_pipeline.yml` both run on `ubuntu-latest`, both inject `OPENROUTER_API_KEY` into the job env, and both implicitly assume `langchain-openai` is installed.
- Neither workflow has a `branches:` trigger filter; both run on whatever ref is checked out.
- There is no test job — no PR-triggered workflow that runs `pytest` against a PR before merge.
- The `claude-subscription` branch's distinct dependency set (`claude-agent-sdk`, `anthropic`, no `langchain-openai`) and distinct env contract (`LLM_BACKEND`, `ANTHROPIC_API_KEY`, optional `claude` CLI) are tested only on the developer's machine, manually.

Practical consequences:

- A change merged to `main` that breaks LLM client construction has no CI signal at all — the daily cron is the first thing to notice.
- A change merged to `claude-subscription` that breaks something cross-cutting (e.g. an `agents/novelty_node.py` refactor) likewise has no CI signal until someone manually runs the variant locally.
- A PR cannot be reviewed against the test suite. There is no green/red badge on a PR, no required check to gate merging.
- The two branches will drift in unobservable ways — exactly the failure mode ADR-0001 and the branch-strategy decision were meant to guard against.

## Solution

Two CI surfaces, separately scoped:

1. **PR-test workflow** runs on every pull request against either branch. Sets up the right backend for the target branch, runs unit tests, runs lint, runs the integration suite with the LLM client mocked. Required to pass before merge.
2. **Production-pipeline workflows** (the existing `daily_pipeline.yml` and `weekly_tactics_pipeline.yml`) are scoped to run only on `main`, since that is the deployed branch. The `claude-subscription` branch does not have a "production pipeline" — it exists as a developer-experience variant, not a deployed environment.

The PR workflow uses a matrix or branch-conditional setup to install the right dependency set and run the right test slice for whichever branch the PR targets.

## User Stories

1. As a contributor opening a PR against `main`, I want CI to run `pytest tests/unit/ -v` with `langchain-openai` installed and an `OPENROUTER_API_KEY` stub in the env, so that I get a green/red signal before merge.
2. As a contributor opening a PR against `claude-subscription`, I want CI to run `pytest tests/unit/ -v` with `claude-agent-sdk` + `anthropic` installed (no `langchain-openai`), so that the variant-specific test (`tests/unit/test_llm_client.py`) actually runs.
3. As a contributor opening any PR, I want CI to run `ruff check` and `ruff format --check`, so that lint failures are caught before merge instead of in a follow-up commit.
4. As a contributor opening any PR, I want CI to run the integration suite (`tests/integration/`) with the LLM client mocked, so that pipeline-level regressions show up at PR time.
5. As a maintainer, I want the PR workflow's required checks to block merge on either branch when any check is red, so that a broken PR cannot land.
6. As a maintainer, I want the existing `daily_pipeline.yml` and `weekly_tactics_pipeline.yml` restricted via `branches: [main]` (and explicit `workflow_dispatch` defaults to `main`), so that a `workflow_dispatch` accidental run on `claude-subscription` does not write KFA's production DB.
7. As a maintainer, I want each PR workflow run to upload `pytest --cov` HTML to GitHub Actions artifacts, so that I can drill into coverage on a specific PR without re-running locally.
8. As a contributor, I want the PR workflow to fail fast (lint before tests, unit before integration), so that obvious problems surface in seconds rather than minutes.
9. As a contributor on `claude-subscription`, I want the PR workflow to verify that `agents/llm_client.py` still implements the three-backend resolver and that `_resolve_backend()` returns the expected fallback chain when each backend is unavailable, so that ADR-0001's invariant is mechanically protected.
10. As a maintainer, I want a weekly cross-branch sync check (separate workflow, runs on a schedule) that pulls both branches and runs `git diff main..claude-subscription -- agents/ collectors/ database/ pipeline/ models/ reports/` and posts the diff as an issue comment if it touches files outside the 8 expected variant-specific files, so that drift between the shared surface of the two branches is visible.
11. As a maintainer, I want the PR workflow to be defined in a single YAML file (`.github/workflows/pr-tests.yml`) using a branch-conditional matrix, so that there is one place to read CI's contract rather than two near-duplicate files.
12. As a maintainer, I want the PR workflow's job to use `uv sync --frozen` (refuses to update the lockfile), so that lockfile drift on a PR is caught instead of papered over.
13. As a contributor, I want a `pytest --collect-only -q` step early in the PR workflow that fails immediately if any test file fails to import, so that import-only breakage is diagnosed in seconds.
14. As a maintainer, I want secrets used in CI (e.g. `OPENROUTER_API_KEY` stub for `main`'s tests, dummy `ANTHROPIC_API_KEY` for `claude-subscription`'s tests) to be repository secrets specifically scoped to the test workflow and not the production workflow, so that a leaked test secret cannot be used to bill real LLM calls.
15. As a contributor opening a PR against `main`, I want the PR workflow to **also** run on the `claude-subscription` branch automatically (as a "cross-branch impact" check) when the diff touches any file outside the 8 variant-specific files, so that I see immediately if my main-branch change broke the variant.
16. As a maintainer, I want the cross-branch impact check (story 15) to be advisory rather than blocking initially, so that we can observe how often it fires before deciding to make it required.
17. As a contributor on `claude-subscription`, I want my PR to be allowed to skip the `tactics_weekly_pipeline.yml`-related test surface if my change doesn't touch tactics files, so that variant-branch PRs are not gated on tactics correctness.
18. As a maintainer, I want a deprecation/notice in `daily_pipeline.yml` and `weekly_tactics_pipeline.yml` explaining that they are scheduled cron workflows only and PRs are tested by `pr-tests.yml`, so that a contributor reading these files understands their scope.

## Implementation Decisions

**New file: `.github/workflows/pr-tests.yml`.**

Triggers:
- `pull_request: [opened, synchronize, reopened]` against `main` and `claude-subscription`.

Jobs:
- `lint` — `uv run ruff check && uv run ruff format --check`. Fast, runs first.
- `unit-tests` — `uv sync --frozen`, `uv run pytest tests/unit/ -v --cov=agents --cov=collectors --cov=database --cov=pipeline --cov=reports --cov-report=xml --cov-report=html`. Depends on `lint`.
- `integration-tests` — `uv sync --frozen`, `uv run pytest tests/integration/ -v`. Depends on `unit-tests` (so an obvious unit failure short-circuits before the slower integration run).
- `cross-branch-impact` (advisory) — checks out the *other* branch, runs `git diff` against the PR's target, fails if any file *outside* the 8 variant-specific files differs in non-trivial ways. Implemented as a separate job that can be marked non-blocking initially.

System deps:
- All test jobs install `libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info` (WeasyPrint requires these for PDF generation, which the integration test exercises).

Env for tests:
- `OPENROUTER_API_KEY=test-stub` for `main`-branch test jobs.
- `LLM_BACKEND=api_key`, `ANTHROPIC_API_KEY=test-stub` for `claude-subscription`-branch test jobs.
- LLM client is mocked at the `get_org_llm` boundary in all unit and integration tests (per existing `conftest.py` pattern) — no real network calls.

Branch-conditional setup:
- The workflow inspects `${{ github.base_ref }}` (PR target branch). If `claude-subscription`, sets `LLM_BACKEND=api_key` and ensures `claude-agent-sdk` + `anthropic` resolve (via the branch's own `pyproject.toml` / `uv.lock`). If `main`, the OpenRouter dep set resolves.

**Modified files: `.github/workflows/daily_pipeline.yml` and `.github/workflows/weekly_tactics_pipeline.yml`.**

- Add `branches: [main]` filter under each `on:` trigger.
- `workflow_dispatch` keeps working, but defaults are unchanged (the workflow file is only present on `main` to begin with — these workflow files do not exist on `claude-subscription` because the variant branch isn't a deployed environment).

Actually — the workflow files **are** on `claude-subscription` (the branch was created from `main`'s tip, so it inherits the workflow files). The PR adds `branches: [main]` and adds an explicit comment in each workflow file: "Production cron — runs only on `main`. The `claude-subscription` branch inherits this file but the `branches:` filter prevents accidental execution."

**New file: `.github/workflows/cross-branch-drift.yml` (separate workflow, weekly schedule).**

- Schedule: `0 12 * * 1` (Mondays 12:00 UTC).
- Fetches both branches; diffs the shared surface (everything except `agents/llm_client.py`, `config/settings.py`, `pyproject.toml`, `uv.lock`, `.env.example`, `README.md`, `CLAUDE.md`, `tests/unit/test_llm_client.py`, `docs/adr/0001-*`); if non-empty, opens or updates a GitHub issue labeled `drift` with the diff as a comment.
- Purpose: surfaces accidental divergence between the two branches' shared code over time.

**Required-check configuration** (branch protection settings, configured in GitHub UI, documented in `docs/ops/branch-protection.md`):

- On `main`: `lint`, `unit-tests`, `integration-tests` all required.
- On `claude-subscription`: same three required.
- `cross-branch-impact` advisory (not required) on either, pending observation period.

**What does NOT change.**

- The existing production cron schedules and their behavior.
- The existing `kfa-pipeline` / `kfa-tactics-pipeline` entry points.
- The `conftest.py` test fixtures or the LLM mocking pattern.
- The branch model itself (`main` ↔ `claude-subscription`).

## Testing Decisions

A good test of a CI workflow change is to push it to a throwaway branch and watch the result, not to write a unit test of the YAML. The "tests" for this PRD are operational: confirm the workflow runs, runs in the expected order, exits with the expected code, posts expected statuses.

**Validation plan:**

- Push `pr-tests.yml` to a throwaway branch; open a no-op PR against `main`; assert all three jobs run and pass.
- Push the same to a throwaway branch of `claude-subscription`; open a no-op PR; assert all three jobs run, the LLM-client test passes against the SDK backend, and the OpenRouter-specific test is skipped or absent (it shouldn't exist on this branch).
- Push a deliberately broken commit (e.g. `import nonexistent`) to a PR; assert `unit-tests` fails fast and `integration-tests` does not run.
- Push a deliberately drifting commit to `main` that modifies `agents/novelty_node.py` without touching `claude-subscription`; assert the weekly drift workflow opens an issue on the next Monday run (or manually trigger it).

**Prior art:** the two existing workflow files are the closest analog for system deps, secret injection, and `uv` usage; the new PR workflow should mirror their setup pattern.

## Out of Scope

- Parallelizing the test suite across multiple workers (e.g. `pytest-xdist`). Optimization, not correctness; revisit if PR feedback exceeds 5 minutes.
- A multi-Python-version matrix (3.13, 3.14). The project targets 3.13+; no second version is supported today.
- Cross-OS testing (macOS, Windows). Production runs on Linux; PRs only need to verify Linux. macOS-only WeasyPrint quirks are a developer-machine concern, not a CI one.
- Container-based testing (a `docker compose` reproduction of prod). The pipeline is single-process Python; the marginal value of containerizing the test environment is low here.
- Performance / latency regression tests. The pipeline's runtime is dominated by LLM calls (mocked in tests), so wall-clock CI time isn't a useful regression signal.
- Auto-merging PRs that pass all checks. Out of scope; reviewer judgment is still required.
- A separate "release" workflow. There are no semver releases of this codebase — it's a continuously-deployed pipeline. CI is the deployment.

## Further Notes

- The cross-branch drift workflow is the cheapest mechanism I can think of to mechanically enforce "fixes to the shared surface go on `main`, then merge to `claude-subscription`." Without it, a contributor making a small fix on `claude-subscription` (more convenient if they're already there) will not realize until weeks later that they branched from a stale base.
- The "8 variant-specific files" list referenced in stories 10, 11, 15 and in the drift workflow's exclude list is the same one captured in the `claude-subscription` introduction commit message. Maintaining this list as a checked-in constant (e.g. `.github/variant-files.txt`) is preferable to repeating it in three workflow files; the drift workflow loads it once.
- This PRD sits independently of PRD 0001, 0002, 0003, 0004. None depends on it; it doesn't depend on any of them. Ship when convenient.
