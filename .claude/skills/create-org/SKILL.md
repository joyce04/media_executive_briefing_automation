---
name: create-org
description: Create a new organization in the multi-tenant DB and seed its sources, entities, recipients, and prompt overrides via database/repositories/org_repo.py functions. Use when the user wants to add a customer/tenant, copy an org for testing, or seed a new pipeline target. There is no add_org.py CLI script — this skill is the canonical path.
---

# Create a new org

## What gets created

A new org needs rows in **6 tables**: `organizations`, `org_sources` (≥1), `org_entities` (≥1), `org_recipients` (≥1 with role=`to`), optionally `org_prompts`, and a row in `subscriptions` if the billing pathway matters for testing.

The org's `model_tier` ∈ `{starter, pro, enterprise}` controls which Claude model `get_org_llm()` returns (see `agents/llm_client.py::_MODEL_TIERS`).

## Template

```bash
uv run python - <<'PY'
from database.connection import init_db
from database.repositories.org_repo import (
    create_org, upsert_org_source, upsert_org_entity,
    add_org_recipient, upsert_org_prompt, get_org_by_slug,
)

init_db()

# 1. Create the org
org_id = create_org({
    "slug": "acme",
    "name": "Acme Corporation",
    "name_short": "ACME",
    "language": "en",
    "timezone": "America/New_York",
    "schedule_cron": "0 7 * * *",
    "primary_color": "#1a56db",
    "secondary_color": "#1e429f",
    "model_tier": "pro",
})

# 2. Add at least one source (RSS or Google News search)
upsert_org_source(org_id, {
    "source_id": "techcrunch_rss",
    "name": "TechCrunch",
    "source_type": "rss",
    "url": "https://techcrunch.com/feed/",
    "language": "en",
    "priority": 1,
})

upsert_org_source(org_id, {
    "source_id": "acme_gnews",
    "name": "Google News — Acme",
    "source_type": "google_news_rss",
    "query": "Acme Corporation OR ACME Inc",
    "language": "en",
    "priority": 1,
})

# 3. Add watchlist entities (drives LLM attention in analyze + synthesize nodes)
upsert_org_entity(org_id, {
    "entity_type": "keyword_core",
    "name_primary": "Acme Corporation",
    "name_alt": "ACME",
    "priority": 1,
    "attributes": {"watch_reason": "primary brand monitoring"},
})

# 4. Add recipients (at least one role=to is required for delivery)
add_org_recipient(org_id, {"role": "to", "name": "Leadership", "email": "team@acme.com"})

# 5. (Optional) override default prompts per node
upsert_org_prompt(org_id, "synthesis",
    "You are the Chief Intelligence Analyst for Acme. Focus on competitive moves and regulatory news. Return JSON only.")

# 6. Verify and test
org = get_org_by_slug("acme")
print("Created org_id =", org["id"], "slug =", org["slug"], "tier =", org["model_tier"])
PY
```

## Then test the new org

```bash
uv run python - <<'PY'
import asyncio
from pipeline.orchestrator import run_pipeline_for_org
asyncio.run(run_pipeline_for_org(org_id=<new_id>, dry_run=True))
PY
```

## Valid entity_type values

`keyword_core`, `person`, `player`, `team`, `tournament`. Anything else may be silently dropped by the analyzer.

## Valid prompt keys

`keyword_generation`, `analysis`, `synthesis`, `deduplication`. Falls back to the default in `agents/<node>_node.py` if no row exists for the org.

## Don't

- Don't insert into these tables with raw SQL — use the repository functions, which enforce schema invariants and JSON serialization.
- Don't reuse a `slug` — `organizations.slug` is unique. `create_org()` will raise.
