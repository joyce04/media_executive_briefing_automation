# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Multi-tenant daily media intelligence briefing pipeline. One SQLite database serves multiple organizations; each org has its own sources, entity watchlist, model tier, schedule, and recipient list. Each run collects news, dedupes, classifies novelty against prior days, analyzes per-article, synthesizes an executive briefing, and emails an HTML + PDF report.

All LLM calls route through **OpenRouter** (`langchain_openai.ChatOpenAI` pointed at OpenRouter's base URL). For a sibling fork that uses `claude-agent-sdk` against a Claude Pro/Max subscription instead, see `/Users/g/workspace/kfa_daily_media_intel_local/`.

## Commands

Package management uses **`uv`** (not `pip`). Python 3.13+ required. PDF generation needs system Pango (`brew install pango libffi` on macOS).

```bash
# Install / sync dependencies
uv sync

# Initialize the DBs (daily + tactics, idempotent)
uv run python scripts/db_init.py

# Run the pipeline once (uses org_id=1 — the original KFA org via the back-compat shim)
uv run python scripts/run_pipeline.py --dry-run                       # writes files, no email
uv run python scripts/run_pipeline.py --date 2026-04-01               # specific date + send

# Backfill a date range
uv run python scripts/backfill.py --start 2026-03-01 --end 2026-03-07 --dry-run

# Verify RSS sources are reachable
uv run python scripts/test_sources.py

# Tests
uv run pytest tests/unit/ -v                                          # fast; LLMs mocked, in-memory SQLite
uv run pytest tests/integration/ -v                                   # full pipeline on fixture data
uv run pytest tests/unit/path/to/test_file.py::test_name -v           # single test
uv run pytest tests/unit/ --cov=agents --cov=collectors --cov-report=term-missing

# Lint / format (ruff configured for line-length 100, target py312)
uv run ruff check
uv run ruff format
```

**Multi-tenant runner.** The `run_pipeline.py` script wraps the legacy single-org shim (`run_pipeline()` in `pipeline/orchestrator.py`, hardcoded to `org_id=1`). To run a non-default org, call `run_pipeline_for_org(org_id, run_date, dry_run)` directly from a script or REPL. The README's `--org` flag and `add_org.py` are aspirational — orgs are created today by calling repository functions in `database/repositories/org_repo.py` (`upsert_org_source`, `upsert_org_entity`, `add_org_recipient`, `upsert_org_prompt`).

## Architecture (the parts that span multiple files)

### LangGraph 8-node DAG

Wired in `pipeline/graph.py`; entry point is `pipeline/orchestrator.py::run_pipeline_for_org(org_id)`. State shape is `PipelineState` in `models/state.py` — every node reads and writes a slice of it.

```
keyword → collect → filter → deduplicate → novelty → analyze → synthesize → report
```

Each node lives in `agents/<node_name>_node.py`. Keyword and collect produce raw articles; filter drops irrelevant ones; deduplicate does a 3-pass merge (URL hash → title fingerprint → LLM semantic); novelty classifies each survivor against the last 7 days as `new | developing | continuing | resolved` using `story_continuity`; analyze writes per-article sentiment/topic/risk for new+developing only; synthesize produces the executive briefing; report renders HTML/PDF and ships via SMTP.

### Multi-tenancy

Every pipeline table carries an `org_id`. The single DB at `data/media_intel.db` holds all orgs; per-org LangGraph checkpoints live at `data/checkpoints/{org_slug}.db`. LangGraph `thread_id = "{org_id}_{run_date}"` — re-running for the same date resumes from the last successfully completed node.

Org configuration (sources, entities, prompts, recipients, branding, model tier) lives in `org_*` tables and is loaded into `PipelineState.org_config` once per run.

### LLM routing (single chokepoint)

`agents/llm_client.py` is the **only** place that constructs LLM clients. `get_org_llm(org, mode)` consults `_MODEL_TIERS[tier][mode]` where `tier ∈ {starter, pro, enterprise}` and `mode ∈ {fast, smart}`. Touching this file affects every node. Model names are defined in `config/settings.py` as OpenRouter-prefixed strings (`anthropic/claude-...`).

### Config

`config/settings.py` is a Pydantic `BaseSettings` reading `.env`. It also exposes `_interpolate_env()` which expands `${VAR}` placeholders inside YAML config files (used for recipient lists in `config/*.yaml`).

### Where to look

| Concern | Files |
|---|---|
| Add/change a pipeline step | `agents/<node>_node.py` + `pipeline/graph.py` |
| Add a new article source type | `collectors/base.py` (BaseCollector) + new `collectors/<name>.py` + register in `collectors/registry.py` |
| Change DB schema | `database/schema_v2.sql` + repository in `database/repositories/` + run `scripts/db_init.py` |
| Change a per-org default | `org_*` tables; CLI is `scripts/add_org.py` |
| Report layout | `reports/templates/*.jinja2` + `reports/generator.py` (Jinja context) |
| Per-org prompt overrides | `org_prompts` table, loaded by each agent node via `org_repo.get_prompt(org_id, key)` |
| CI/cron | `.github/workflows/daily_pipeline.yml` |

### Test conventions

`pytest-asyncio` in **auto** mode (every `async def` test runs without a marker). Unit tests use in-memory SQLite via `conftest.py` fixtures and mock LLM clients; never hit the network. Integration tests run the full graph on canned fixture articles.

## Conventions

- `uv` for everything — never `pip install` directly.
- LLM call shape across all nodes: `await llm.ainvoke([SystemMessage(...), HumanMessage(...)])`. Don't introduce a different pattern; the LLM client shim relies on this.
- All timestamps are stored UTC in SQLite; org timezone is applied only at render/schedule time.
- Org isolation is invariant: every query that touches pipeline tables must filter by `org_id`. Repository methods enforce this.
