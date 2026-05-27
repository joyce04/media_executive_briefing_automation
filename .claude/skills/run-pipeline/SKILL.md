---
name: run-pipeline
description: Trigger one pipeline run for an organization (collect → analyze → synthesize → report). Use when the user wants to manually invoke the pipeline, test a date range, or dry-run before sending email. Defaults to the legacy single-org shim (org_id=1).
---

# Run the media intelligence pipeline

## Shape

The pipeline is an 8-node LangGraph DAG. Each invocation runs end-to-end for one org and one date. Re-running with the same `(org_id, date)` resumes from the last completed checkpoint.

## Two paths

### 1. Default org (org_id=1, via shim)

```bash
# Dry-run for today (no email, but reports written to data/reports/)
uv run python scripts/run_pipeline.py --dry-run

# Specific date with email
uv run python scripts/run_pipeline.py --date 2026-04-01
```

### 2. Non-default org (direct call to orchestrator)

The CLI doesn't accept `--org` yet. Use Python:

```bash
uv run python - <<'PY'
import asyncio
from pipeline.orchestrator import run_pipeline_for_org
state = asyncio.run(run_pipeline_for_org(org_id=2, run_date="2026-04-01", dry_run=True))
print("articles_collected:", len(state.get("raw_article_ids", [])))
print("emails_sent:", state.get("emails_sent", []))
PY
```

## Required environment

- `OPENROUTER_API_KEY` set in `.env` (or process env)
- For email sending (no `--dry-run`): `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`

## When something goes wrong

- Re-run with the same date — checkpoint resumes from the last green node.
- Inspect last run: `sqlite3 data/media_intel.db "SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT 5"`.
- Per-org checkpoint lives at `data/checkpoints/{org_slug}.db` — delete that file to force a full re-run.

## Don't

- Don't run without `--dry-run` first when testing changes — it will email recipients.
- Don't call `run_pipeline()` directly in tests; use the mocked fixtures in `tests/conftest.py`.
