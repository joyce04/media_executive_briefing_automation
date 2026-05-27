---
name: inspect-db
description: Query the multi-tenant SQLite DB to inspect recent pipeline runs, dedup ratios, novelty distributions, and per-org article volumes. Use when debugging why a run produced unexpected output, checking that a fix improved a metric, or sanity-checking a backfill.
---

# Inspect the media intelligence database

Default location: `data/media_intel.db`. WAL mode is on, so it's safe to query while a pipeline is running.

## Recent runs across all orgs

```bash
sqlite3 -header -column data/media_intel.db "
  SELECT pr.id, o.slug, pr.run_date, pr.status, pr.articles_collected,
         pr.articles_deduplicated, pr.articles_analyzed, pr.estimated_cost_usd
  FROM pipeline_runs pr
  JOIN organizations o ON o.id = pr.org_id
  ORDER BY pr.id DESC LIMIT 20;
"
```

## Dedup ratio for an org over the last 14 days

```bash
sqlite3 -header -column data/media_intel.db "
  SELECT run_date,
         articles_collected AS raw,
         articles_deduplicated AS deduped,
         ROUND(1.0 - CAST(articles_deduplicated AS REAL) / NULLIF(articles_collected, 0), 2) AS dedup_pct
  FROM pipeline_runs
  WHERE org_id = 1 AND run_date >= date('now', '-14 days')
  ORDER BY run_date DESC;
"
```

## Novelty distribution for the latest run

```bash
sqlite3 -header -column data/media_intel.db "
  SELECT novelty_status, COUNT(*) as count
  FROM article_analyses a
  JOIN pipeline_runs pr ON pr.org_id = a.org_id AND pr.run_date = a.run_date
  WHERE pr.id = (SELECT MAX(id) FROM pipeline_runs)
  GROUP BY novelty_status
  ORDER BY count DESC;
"
```

## Failing runs in the last week with error messages

```bash
sqlite3 -header -column data/media_intel.db "
  SELECT id, org_id, run_date, started_at, error_message
  FROM pipeline_runs
  WHERE status = 'failed' AND started_at >= datetime('now', '-7 days')
  ORDER BY started_at DESC;
"
```

## Per-source article yield (which sources are dry?)

```bash
sqlite3 -header -column data/media_intel.db "
  SELECT source_id, COUNT(*) AS articles, MIN(collected_at) AS first, MAX(collected_at) AS last
  FROM raw_articles
  WHERE org_id = 1 AND collected_at >= datetime('now', '-7 days')
  GROUP BY source_id
  ORDER BY articles DESC;
"
```

## Story continuity — what's been running for ≥3 days

```bash
sqlite3 -header -column data/media_intel.db "
  SELECT story_key, days_active, status, first_seen_date, last_seen_date
  FROM story_continuity
  WHERE org_id = 1 AND days_active >= 3 AND status != 'resolved'
  ORDER BY days_active DESC LIMIT 20;
"
```

## Schema reference

`database/schema_v2.sql` is authoritative. 20 tables total: 6 org/admin, 9 pipeline, 5 auth/billing. Every pipeline table has an `org_id` column — always filter by it.

## Don't

- Don't `UPDATE` or `DELETE` from this DB to "clean up" — pipeline checkpoints and downstream reports will get out of sync. Use the orchestrator's resume mechanism instead (delete the per-org checkpoint file at `data/checkpoints/{slug}.db` to force a full re-run).
- Don't use `sqlite3 --readonly` syntax — this build of sqlite3 may not support it; the pipeline tolerates concurrent reads in WAL mode anyway.
