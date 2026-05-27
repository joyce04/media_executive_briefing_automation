# PRD 0002 — Multi-tenant Organization CLI

## Problem Statement

An operator who wants to onboard a second Organization today has to open a Python REPL and call repository functions by hand:

```python
from database.repositories.org_repo import (
    create_org, upsert_org_source, upsert_org_entity,
    add_org_recipient, upsert_org_prompt,
)
org_id = create_org(slug="acme", name="Acme Corporation", ...)
upsert_org_source(org_id, source_id="acme_gnews", ...)
upsert_org_entity(org_id, entity_type="person", name_primary="Jane Smith", ...)
# ... and so on
```

The README and CLAUDE.md both promise a CLI (`scripts/add_org.py --slug --name ...`, `scripts/run_pipeline.py --org SLUG`, `scripts/backfill.py --org SLUG`, `scripts/test_sources.py --org SLUG`) that does not exist. CLAUDE.md acknowledges this explicitly:

> The README's `--org` flag and `add_org.py` are aspirational — orgs are created today by calling repository functions in `database/repositories/org_repo.py` (`upsert_org_source`, `upsert_org_entity`, `add_org_recipient`, `upsert_org_prompt`).

Today's CLI is hardwired to `org_id = 1` via a compatibility shim (`pipeline.orchestrator.run_pipeline()`) that calls `run_pipeline_for_org(1, ...)`. There is no way to run the pipeline for a second Organization from the command line, even though the underlying `run_pipeline_for_org()` already accepts an arbitrary `org_id`.

The operator's pain compounds: they cannot test a new Organization end-to-end without writing throwaway Python; they cannot operate the platform for more than one Organization without bespoke scripts; CI workflows have no clean way to run for a specific Organization.

## Solution

Make the multi-tenancy that exists in the data layer visible at the CLI. Every script that touches an Organization takes `--org SLUG` (no positional fallback to `org_id=1`); a new `scripts/add_org.py` provisions a new Organization with all the basic fields in one command and prints next-step hints; and bulk source/entity/recipient configuration accepts a YAML or JSON file so an Organization can be defined end-to-end without a Python REPL.

From the operator's perspective:

- "Onboard Acme" is one `add_org.py` command followed by either bulk-config-from-YAML or a sequence of `org-config` subcommands.
- "Run today's pipeline for Acme" is `run_pipeline.py --org acme`.
- "Backfill last week for Acme" is `backfill.py --org acme --start ... --end ...`.
- "Did Acme's sources break?" is `test_sources.py --org acme`.
- Every script with an Organization argument errors clearly when `--org` is missing or the slug does not exist.

## User Stories

1. As an operator, I want `scripts/add_org.py --slug --name --name-short --language --timezone --schedule --primary-color --secondary-color --model-tier` to create an Organization row in one command, so that onboarding does not require a Python REPL.
2. As an operator, I want `add_org.py` to refuse to create an Organization with a slug that already exists (unless `--update` is passed), so that re-running the command does not silently overwrite production configuration.
3. As an operator, I want `add_org.py --update` to update mutable fields of an existing Organization, so that I can rotate branding or change schedules without dropping the row.
4. As an operator, I want `add_org.py` to print the newly created `org_id`, the resulting checkpoint file path, and the next commands I should run (configure sources, configure recipients, run dry-run), so that I am not left guessing what to do next.
5. As an operator, I want `add_org.py --from-yaml path/to/config.yaml` to provision an Organization, its Sources, Entities, Recipients, and Prompt Overrides from a single declarative file, so that I can version-control an Organization's full configuration in git.
6. As an operator, I want the YAML schema for `--from-yaml` to be documented in `docs/cli/org-config-schema.md` with a complete worked example, so that operators do not have to read source code to write a config file.
7. As an operator, I want `scripts/run_pipeline.py --org SLUG` to be the only supported way to invoke the runner, so that I cannot accidentally run for the wrong Organization by relying on a default.
8. As an operator, I want `run_pipeline.py` without `--org` to fail with a clear message listing the active Organizations and example commands, so that the failure is self-correcting rather than cryptic.
9. As an operator, I want `scripts/backfill.py --org SLUG --start --end` to accept the same `--org` semantics as `run_pipeline.py`, so that the CLI surface is consistent.
10. As an operator, I want `scripts/test_sources.py --org SLUG` to fetch every active Source for the given Organization and report status (HTTP code, items returned, parse errors), so that I can diagnose source failures without running the whole pipeline.
11. As an operator, I want `scripts/list_orgs.py` (or equivalent — could be a subcommand) to print active Organizations with their slug, name, model_tier, schedule, recipient count, and last successful run date, so that I can see at a glance what the platform is running for whom.
12. As an operator, I want a `scripts/org_config.py --org SLUG` subcommand surface for managing sub-configuration (add-source, remove-source, list-sources, add-entity, list-entities, add-recipient, list-recipients, set-prompt, list-prompts), so that I do not have to write Python to make small per-Organization changes.
13. As an operator, I want every Organization-mutating subcommand to print the diff between the old and new state before applying (unless `--yes` is passed), so that I cannot fat-finger a destructive change.
14. As an operator running CI, I want the pipeline scripts to accept `--org` from an environment variable (`ORG_SLUG`) as a fallback when the flag is omitted, so that GitHub Actions matrix jobs can set `ORG_SLUG` once at the job level rather than passing it on every step.
15. As an operator, I want the compatibility shim `pipeline.orchestrator.run_pipeline()` (hardcoded to `org_id=1`) marked deprecated and removed once all callers are migrated, so that there is no implicit-Organization code path left.
16. As an operator, I want `add_org.py` to refuse invalid input (malformed cron expression, unknown timezone, unknown model_tier, non-hex color) at parse time with a clear error, so that bad rows never reach the database.
17. As an operator, I want `add_org.py` to optionally create an initial API key (`--with-api-key`) and print it once, so that programmatic access can be enabled at provisioning time.
18. As an operator, I want every script to read `DATABASE_PATH` from `.env` the same way the runner does, so that I can point the CLI at a staging DB by setting one environment variable.
19. As a developer, I want a single `cli/org_args.py` helper that adds the `--org SLUG` flag, resolves the slug to `org_id`, and surfaces the "not found" error consistently, so that the four scripts do not duplicate parsing logic.
20. As a developer, I want the YAML-config loader for `--from-yaml` to live in `scripts/_org_config_loader.py` and be testable in isolation against a fixture file, so that the loader can be reused by the future tactics-migration script (PRD 0001) and any future Web UI.
21. As an operator, I want `add_org.py --dry-run` to print the SQL it would execute without writing anything, so that I can preview Organization creation against production data safely.
22. As an operator, I want `add_org.py` and the org_config subcommands to refuse to run if the database does not exist or has not been initialized (`uv run python scripts/db_init.py` not yet executed), with a clear error, so that there is no path to "wrote to a non-existent file" confusion.
23. As an operator running multi-Organization production, I want a `scripts/run_all_orgs.py` (or equivalent) that iterates active Organizations and runs each pipeline sequentially with per-Organization error isolation (one Organization's failure does not stop the others), so that I have a single cron entry point.

## Implementation Decisions

**New scripts.**
- `scripts/add_org.py` — create or update an Organization, optionally with bulk sources/entities/recipients/prompts from `--from-yaml`.
- `scripts/list_orgs.py` — print active Organizations and headline metrics.
- `scripts/org_config.py` — sub-subcommand surface for sources/entities/recipients/prompts CRUD.
- `scripts/run_all_orgs.py` — sequential per-Organization runner for cron.

**Modified scripts.**
- `scripts/run_pipeline.py` — add required `--org SLUG`; remove implicit `org_id=1` path; on missing flag, print available slugs and exit non-zero.
- `scripts/backfill.py` — same `--org SLUG` semantics; iterate dates per Organization (or expand to multi-Organization later — out of scope here).
- `scripts/test_sources.py` — accept `--org SLUG`; iterate `org_sources` for that Organization.

**Shared helper module.**

`scripts/_org_args.py` (private module, leading underscore) exposes:

- `add_org_argument(parser)` — adds `--org SLUG` to an `argparse.ArgumentParser`, with `ORG_SLUG` env-var fallback.
- `resolve_org(args) -> dict` — returns the full Organization row, raising a `click`-style typed error with the list of valid slugs when not found.

Every CLI script imports from this helper so the error message and slug-resolution behavior is identical across the suite.

**YAML schema for `--from-yaml`.**

```yaml
organization:
  slug: acme
  name: "Acme Corporation"
  name_short: ACME
  language_primary: en
  timezone: "America/New_York"
  schedule_cron: "0 7 * * *"
  primary_color: "#1a56db"
  secondary_color: "#1e429f"
  model_tier: pro

sources:
  - source_id: techcrunch_rss
    name: TechCrunch
    source_type: rss
    url: "https://techcrunch.com/feed/"
    language: en
    priority: medium
  - source_id: acme_gnews
    name: "Google News — Acme"
    source_type: google_news_rss
    query: "Acme Corporation OR ACME Inc"
    language: en
    priority: high

entities:
  - entity_type: keyword_core
    name_primary: Acme Corporation
    name_alt: ACME
    priority: 1
    attributes: { watch_reason: "primary brand monitoring" }

recipients:
  to:  [{ name: "Leadership Team", email: "team@acme.com" }]
  cc:  []
  bcc: [{ name: "Archive", email: "archive@acme.com" }]

prompts:
  synthesis: |
    You are the Chief Intelligence Analyst for Acme Corporation.
    Focus on competitive threats, partnership opportunities, and regulatory news.
    Return JSON only.
```

The loader applies idempotently — re-running on the same file produces the same DB state. Source/entity/recipient/prompt sections are each optional.

**Deprecation path for `run_pipeline()` shim.**

`pipeline.orchestrator.run_pipeline()` (no args) is the back-compat shim hardcoded to `org_id=1`. It will be:

1. Marked with `@deprecated("Use run_pipeline_for_org(org_id) directly")` in the same PR that updates the CLI scripts.
2. Removed two PRs later, after CI for both `main` and `claude-subscription` branches passes on the new CLI surface.

**Cron entry point for multi-Organization production.**

`scripts/run_all_orgs.py --pipeline-kind PK` (PK defaults to `media_daily`) iterates `get_all_active_orgs()` and invokes `run_pipeline_for_org(org_id=..., pipeline_kind=PK)`. Per-Organization exception isolation: each Organization runs in its own try/except, errors are logged structurally but do not abort the loop, and the script exits non-zero if any Organization failed (so the cron job alerts).

This script depends on PRD 0001 landing the `pipeline_kind` parameter on `run_pipeline_for_org()`. If 0001 has not landed, `run_all_orgs.py` ships without `--pipeline-kind` and always runs the media-daily DAG.

**What does NOT change.**

- `pipeline/orchestrator.py::run_pipeline_for_org()` — already correct; it's the CLI that's broken.
- `database/repositories/org_repo.py` — already has the necessary CRUD; CLI is a thin wrapper over it.
- `scripts/db_init.py` — unaffected.

## Testing Decisions

A good CLI test in this codebase invokes the script's `cli()` callable directly (via Python, not via subprocess) with a constructed args namespace, asserts on the database state afterward, and on the structured logs / exit code. Subprocess-based tests are fine for the end-to-end smoke check but slow and don't pinpoint failures.

**Modules to test:**

- `scripts/_org_args.py` — `resolve_org()` returns the expected row for a known slug; raises with the slug list for an unknown slug; reads from `ORG_SLUG` env var when `--org` is absent. (Unit test against in-memory DB; fast.)
- YAML loader (`scripts/_org_config_loader.py`) — given a fixture YAML file, produces the expected SQL writes (use the existing in-memory DB pattern from `tests/conftest.py`); idempotent on second run; partial sections OK; malformed sections produce typed errors. (Unit test with fixture file.)
- `add_org.py` — happy path creates the row; `--update` updates mutable fields; existing slug without `--update` exits non-zero; `--dry-run` writes nothing; `--with-api-key` returns a key once. (Unit-style test calling `cli()` directly.)
- `run_pipeline.py` — missing `--org` exits non-zero with the slug-list message; valid `--org` invokes `run_pipeline_for_org` with the resolved `org_id` (mock the orchestrator; we are testing the CLI, not the pipeline). (Unit test.)
- `run_all_orgs.py` — one Organization's failure does not abort the loop; aggregate exit code is non-zero iff any Organization failed; structured logs include `(org_slug, success/fail, error)` per Organization. (Integration-ish test; mock the orchestrator to throw for one specific Organization.)

**Prior art:** `tests/conftest.py` already provides the in-memory SQLite fixture and the org-creation helper. The CLI tests should use the same fixture and assert on the same kind of "DB state after" predicates the existing repository tests use.

## Out of Scope

- A full TUI or web UI for Organization management. CLI only.
- API-tier endpoints (`POST /orgs`, etc.) that would let a hosted SaaS frontend create Organizations. The CLI is operator-facing, not customer-facing.
- Automatic schedule installation in a system cron table when an Organization is created. The operator still wires up `schedule_cron` to GitHub Actions / their cron of choice — `add_org.py` only stores the cron expression in the row.
- Multi-Organization parallel execution in `run_all_orgs.py`. Sequential only for now; parallelism is a future PRD if the per-Organization runtime grows.
- Validation that the operator's chosen cron expression actually falls on a day the corresponding Pipeline Kind expects (e.g. Tuesday for `tactics_weekly`). That validation lives inside the runner (PRD 0001) and is not the CLI's responsibility.
- Migration of the existing KFA YAML configs (`config/sources.yaml`, `config/players.yaml`, etc.) to `org_*` rows via the new YAML loader. The KFA rows already exist in the DB from the multi-tenant initialization; the legacy YAMLs are dead.

## Further Notes

- The CLAUDE.md note about the "aspirational" `--org` flag should be deleted in the same PR that lands this PRD, so the docs and the code stop disagreeing.
- This PRD is mostly thin wiring on top of `org_repo.py`. The non-trivial work is the YAML schema, the loader's idempotency contract, and the CLI ergonomics (clear error messages, env-var fallback, `--dry-run`).
- Sequencing with other PRDs: this PRD does not depend on PRD 0001 (tactics multi-tenant) or PRD 0003 (football vocabulary decoupling), and can ship first. `run_all_orgs.py --pipeline-kind` becomes useful only once PRD 0001 lands.
- The `scripts/_org_config_loader.py` module is intentionally designed to be the same loader the tactics migration (PRD 0001) and any eventual Web-UI's "import org" feature would use. Build it once, reuse it.
