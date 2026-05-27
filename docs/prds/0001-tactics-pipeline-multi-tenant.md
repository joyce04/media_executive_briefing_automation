# PRD 0001 — Integrate the Tactics pipeline into the multi-tenant model

## Problem Statement

An operator who runs the platform for KFA today has two parallel products to keep in sync: the daily Media-Intelligence Briefing (multi-tenant; configured in `org_*` tables; produces a `Briefing` and `Report` per Organization per day) and the weekly Tactics Intelligence pipeline (single-tenant; configured in YAML files; produces a `Tactics Weekly Synthesis` per week).

The Tactics pipeline was imported into the canonical repo in commit `7cd6da3` but **was not integrated into the multi-tenant model**. It still:

- Reads its configuration from `config/tactics_sources.yaml` and `config/tactics_recipients.yaml` instead of `org_*` tables.
- Writes to its own `tactics_*` tables without an `org_id` column.
- Runs on a single global schedule (`weekly_tactics_pipeline.yml`, Tue 06:00 KST) with no Organization context.
- Cannot be enabled or disabled per Organization — it implicitly runs for KFA only.

The operator therefore has two places to manage sources, two places to manage recipients, two CI workflows to debug, and no way to offer Tactics to a second Organization without duplicating the entire pipeline.

## Solution

The Tactics pipeline becomes a **Pipeline Kind** that any Organization can subscribe to, alongside the existing Media-Intel daily pipeline. Configuration lives in the same `org_*` tables. Each Organization can subscribe to zero or more Pipeline Kinds, each with its own schedule, recipient filter, and prompt overrides.

From the operator's perspective:

- "Add tactics for KFA" becomes one `org_pipelines` row, not a YAML file edit + CI workflow change.
- "Add tactics for a new Organization" becomes the same one row for that Organization.
- Sources for tactics live in `org_sources` with a `pipeline_kind` tag, so the existing source-management surface works for both kinds.
- The two CI workflows can either remain split (one per kind) or collapse into one matrix workflow that fans out per `(Organization, Pipeline Kind)` binding.

## User Stories

1. As an operator, I want to subscribe an Organization to the Tactics pipeline by inserting one row in `org_pipelines`, so that onboarding new tactics customers does not require code or YAML changes.
2. As an operator, I want to unsubscribe an Organization from the Tactics pipeline by flipping `is_active` on its `org_pipelines` row, so that turning off the product is reversible and audited.
3. As an operator, I want each Organization's Tactics schedule to come from its `org_pipelines.schedule_cron`, so that different Organizations can receive weekly briefings on different days.
4. As an operator, I want Tactics-pipeline Sources to live in `org_sources` with a `pipeline_kind` filter, so that I can manage sources for all of an Organization's pipelines from the same table.
5. As an operator, I want Tactics-pipeline Recipients to live in `org_recipients` with a `pipeline_kind` filter, so that an Organization can send the weekly Tactics briefing to a different distribution list than its daily Media-Intel briefing.
6. As an operator, I want Tactics prompts to live in `org_prompts` keyed by `(org_id, prompt_key)` where the keys are namespaced (e.g. `tactics.analysis`, `tactics.synthesis`), so that prompt overrides do not collide between pipeline kinds.
7. As an operator, I want the `tactics_*` tables (`tactics_pipeline_runs`, `tactics_raw_articles`, `tactics_deduplicated_articles`, `tactics_article_analyses`, `tactics_weekly_synthesis`) to carry an `org_id` column, so that one Organization's tactics output is never visible to another.
8. As an operator, I want a per-Organization Tactics checkpoint file at `data/checkpoints/{org_slug}_tactics.db`, so that the LangGraph resumability that ADR-0002 gives the daily pipeline also applies to the tactics pipeline.
9. As an operator, I want a single runner entry point that dispatches on Pipeline Kind (e.g. `run_pipeline_for_org(org_id, pipeline_kind, run_date)`), so that I do not need to remember two separate CLI scripts.
10. As an operator, I want the existing `kfa-tactics-pipeline` script to continue working during the migration (delegate internally to the new runner with KFA's org_id), so that the weekly cron does not break during the rollout.
11. As an operator, I want the YAML-based tactics config to be migrated to `org_*` rows by a one-shot migration script, so that the cutover does not require manual data entry.
12. As an operator, I want the migration script to be idempotent and dry-run-able, so that I can preview the rows it will create before committing.
13. As an Organization receiving the Tactics briefing, I want my weekly briefing's branding (header color, secondary color, logo) to come from my `organizations` row, so that the Tactics email is visually consistent with my daily Media-Intel email.
14. As an Organization receiving both briefings, I want the LLM-tier (`organizations.model_tier`) to apply to both pipelines, so that I am not paying enterprise rates for one and starter rates for the other.
15. As a developer, I want a `PipelineKind` registry (a single source of truth: `media_daily`, `tactics_weekly`) that names the available kinds and their DAG / cadence specs, so that adding a third kind in the future is a registry entry rather than a code search-and-replace.
16. As a developer, I want each Pipeline Kind's DAG to compile from a `PipelineSpec` (node sequence, checkpoint suffix, output table family), so that there is one path from "what kind am I running" to "what nodes execute."
17. As a developer, I want a single `OrgPipelineBinding` repository method to read all active bindings (used by the scheduler to know what to run when), so that the scheduler does not query `org_pipelines` directly.
18. As a developer, I want `org_sources.pipeline_kind` and `org_recipients.pipeline_kind` to be NULLABLE — NULL meaning "applies to all kinds this Organization subscribes to" — so that an Organization can either share a Source across kinds or scope it to one.
19. As a developer, I want a `tactics_*` → `tactics_pipeline_runs.org_id`-keyed migration with a back-fill of `org_id = 1` (KFA) for all existing rows, so that historical Tactics data is preserved and queryable under the new model.
20. As an operator, I want the weekly CI workflow to remain green throughout the migration (PR-by-PR, behind a feature flag if needed), so that the daily-deployed branch is never broken.
21. As an operator, I want the legacy `config/tactics_sources.yaml` and `config/tactics_recipients.yaml` files removed only after the migration is verified and the cron has run successfully in the new model for at least one week, so that we keep a rollback path.

## Implementation Decisions

**Pipeline Kind registry.** Introduce a `PipelineKind` value class registered at module import in `pipeline/kinds.py`. Each entry binds: a slug (`media_daily`, `tactics_weekly`); the DAG-build callable (today: `pipeline.graph.build_graph` for media, `pipeline.tactics_graph.build_tactics_graph` for tactics); the checkpoint-file suffix; the analysis-table family name; and the cadence the scheduler should default to if `org_pipelines.schedule_cron` is unset.

**Schema additions.**

A new table:

```sql
CREATE TABLE org_pipelines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id          INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    pipeline_kind   TEXT NOT NULL,                           -- 'media_daily' | 'tactics_weekly'
    schedule_cron   TEXT,                                    -- NULL = use kind's default
    is_active       BOOLEAN NOT NULL DEFAULT 1,
    created_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    UNIQUE(org_id, pipeline_kind)
);
```

Column additions on existing tables:

- `org_sources.pipeline_kind TEXT` (nullable; NULL = applies to all kinds the org subscribes to).
- `org_recipients.pipeline_kind TEXT` (nullable; same semantics).
- `org_prompts` — no schema change; prompt keys become namespaced strings (`tactics.analysis`, `tactics.synthesis`); the existing daily keys remain unchanged (`analysis`, `synthesis`, `keyword_generation`, `deduplication`) so this is an additive convention.
- Every `tactics_*` table gains `org_id INTEGER NOT NULL REFERENCES organizations(id)` plus an `idx_tactics_*_org` index. Existing rows back-fill to `org_id = 1`.

**Runner unification.** Add `run_pipeline_for_org(org_id, pipeline_kind, run_date=None, dry_run=False)` in `pipeline/orchestrator.py`. The existing single-arg `run_pipeline_for_org(org_id, ...)` becomes a thin wrapper that defaults `pipeline_kind="media_daily"` and is retained for compatibility. The legacy `kfa-tactics-pipeline` script becomes a thin wrapper calling the new runner with `(org_id=1, pipeline_kind="tactics_weekly")`.

**Tactics repository update.** `database/repositories/tactics_repo.py` gains an `org_id` parameter on every read/write method, enforced the same way as `org_repo`/`article_repo` enforce it for the media tables. There is no new `org_tactics_repo.py` — the existing repository takes over the multi-tenant role.

**Sources adapter.** A bootstrap helper reads `org_sources` filtered by `(org_id, pipeline_kind="tactics_weekly")` and constructs the same in-memory shape today's `_load_tactics_sources_yaml()` produces, so the tactics nodes do not need to change their collection contract.

**Migration script** at `scripts/migrate_tactics_to_multitenant.py`:
1. For KFA's `org_id`, read `config/tactics_sources.yaml` and upsert each entry into `org_sources` with `pipeline_kind = "tactics_weekly"`.
2. Read `config/tactics_recipients.yaml` similarly into `org_recipients`.
3. Insert an `org_pipelines` row `(org_id=1, pipeline_kind="tactics_weekly", schedule_cron="0 21 * * 1")`.
4. Run an `ALTER TABLE` for every `tactics_*` table to add `org_id`, back-filling to 1.
5. Idempotent (`INSERT OR IGNORE`, `ALTER TABLE IF NOT EXISTS` analogues), supports `--dry-run`.

**Cadence enforcement.** Add a precondition check at runner entry: if `pipeline_kind="tactics_weekly"`, `run_date` must be a Tuesday (or the first run after the previous Tuesday) — otherwise emit a clear error rather than producing a half-week analysis.

**CI workflows.** Keep `daily_pipeline.yml` and `weekly_tactics_pipeline.yml` as two files for now (different cron expressions, different timeout values). Both now invoke the unified runner with their respective Pipeline Kinds. A future PRD may consolidate into a matrix workflow.

**What does NOT change.**

- The 8-node Media-Intel DAG (`keyword → collect → filter → deduplicate → novelty → analyze → synthesize → report`) stays as-is.
- The Tactics 6-node DAG (no keyword, no novelty) stays as-is.
- Novelty/Story tracking does not extend to Tactics — those concepts are designed for daily news and are not meaningful for weekly tactical analysis.
- `CONTEXT.md` definitions of Article, Article Cluster, Canonical Article apply to both kinds (the data shapes are similar enough). Tactics introduces no new domain terms.

## Testing Decisions

A good test in this codebase asserts external behavior — what an operator or downstream node observes — and not internal call shapes. Concretely: tests that mock the LLM client and assert that, given a fixture set of articles and a configured Organization, the pipeline produces the expected row counts in the right tables for the right `org_id`. Tests that assert "function X was called Y times" are not what we want here; they break on refactors that don't change behavior.

**Modules to test:**

- `PipelineKind` registry — given a slug, returns the right `PipelineSpec`; unknown slugs raise a clear error. (Pure unit test; fast.)
- `OrgPipelineBinding` repository — read/write/list-active are correct under `org_id` filtering; cross-org reads return empty. (Unit test against in-memory SQLite via `conftest.py` fixture.)
- Sources adapter (`org_sources` → tactics-collector input) — given a seeded `org_sources` with `pipeline_kind="tactics_weekly"`, produces the same in-memory shape `_load_tactics_sources_yaml()` produces from the equivalent YAML. (Unit test with both inputs side-by-side; pin the YAML version at the time of test write.)
- Migration script — running it twice produces the same DB state as running it once (idempotent); `--dry-run` produces no writes. (Integration test against a fresh in-memory DB.)
- Unified runner dispatch — `run_pipeline_for_org(org_id=1, pipeline_kind="tactics_weekly")` writes to `tactics_*` tables; `run_pipeline_for_org(org_id=1, pipeline_kind="media_daily")` writes to media tables; neither leaks rows into the other family. (Integration test, full DAG, mocked LLM.)

**Prior art:** existing `tests/integration/test_pipeline_e2e.py` runs the full media DAG against canned fixture articles and asserts row counts — the tactics integration test should mirror this exactly. Existing `tests/unit/test_*` files in this repo all use in-memory SQLite via `conftest.py` and mock `agents.llm_client.get_org_llm`, which is the pattern to follow.

## Out of Scope

- Building a web UI for managing `org_pipelines` rows. Today's interface is repository calls or direct SQL; the UI is a separate PRD when/if the auth/billing schema is built out.
- Consolidating the two CI workflows into a matrix workflow.
- Adding additional Pipeline Kinds beyond `media_daily` and `tactics_weekly` (e.g. a "monthly competitive intel" kind). Once the registry exists, this is one entry, but not a goal of this PRD.
- Removing the `tactics_*` table family by folding analysis output into a unified `article_analyses` with a JSON `extras` column. The two pipelines have meaningfully different output shapes; forcing a single table costs more clarity than it saves storage. Revisit if a third kind appears that overlaps both shapes.
- Extending Novelty/Story concepts to Tactics. Discussed and rejected in CONTEXT.md.
- Changing the Tactics output language (currently Korean-only). Per-Organization language is already in `organizations.language_primary`; honoring it in the Tactics synthesis is its own follow-up.

## Further Notes

- This PRD assumes ADR-0002 (shared DB + per-Organization checkpoint files) extends naturally to Tactics. Per-Organization tactics checkpoints live at `data/checkpoints/{org_slug}_tactics.db`.
- An ADR is worth writing alongside this implementation: "Per-Organization subscription to multiple Pipeline Kinds via `org_pipelines`," because the alternative ("one Organization = one pipeline, fork the Organization for each pipeline kind") is a real path that a future engineer might propose if the rationale isn't recorded.
- The KFA tenant currently runs both pipelines. Migration order matters: introduce the registry + schema changes + repository updates first behind a no-op (everything still reads YAML), then flip the cron job to read from `org_*` once the migration script has been run and verified. Keep YAML files in-place for one full week after cutover for rollback.
- See ADR-pending on decoupling football vocabulary (PRD 0003) — that work overlaps with the per-Organization prompt overrides this PRD introduces and the two PRDs should be sequenced carefully.
