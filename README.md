# Media Intelligence

![Python 3.13+](https://img.shields.io/badge/Python-3.13%2B-blue)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2%2B-purple)
![OpenRouter](https://img.shields.io/badge/OpenRouter-Claude-orange)

Automated daily executive media briefing service. Configure any organization, point it at news sources, and receive a daily AI-curated intelligence report — filtered, deduplicated, classified by novelty, analyzed for sentiment and risk, and synthesized into an executive summary — delivered by email with a PDF attachment.

Multi-tenant architecture: one database, multiple organizations, per-org model tiers, per-org scheduling.

---

## How It Works

```
Daily schedule (per org) ──────────────────────────────────────────────
                        LangGraph StateGraph (8 nodes)
  ┌────────────────────────────────────────────────────────────────────┐
  │                                                                    │
  │  [1] keyword_node    LLM generates 12–18 targeted queries         │
  │         │            from yesterday's narratives + active stories  │
  │         ▼                                                          │
  │  [2] collect_node    Configured sources + dynamic keyword search   │
  │         │            → raw_articles (age filter + SHA256 dedup)   │
  │         ▼                                                          │
  │  [3] filter_node     LLM: relevance + significance score          │
  │         │            drops articles below threshold (≥5 / ≥4)    │
  │         ▼                                                          │
  │  [4] deduplicate_node  3-pass same-day dedup                      │
  │         │            URL hash → title fingerprint → LLM semantic  │
  │         ▼                                                          │
  │  [5] novelty_node    Cross-day classification vs. last 7 days     │
  │         │            new / developing / continuing / resolved      │
  │         ▼                                                          │
  │  [6] analyze_node    Per-article intelligence (new + developing)  │
  │         │            sentiment · topics · entities · risk flag    │
  │         ▼                                                          │
  │  [7] synthesize_node Executive briefing synthesis                  │
  │         │            narratives · alerts · actions · summary      │
  │         ▼                                                          │
  │  [8] report_node     HTML email + PDF → SMTP delivery             │
  │                                                                    │
  └────────────────────────────────────────────────────────────────────┘
                SQLite  ◄──  data/media_intel.db
```

Each organization gets its own:
- News sources, entity watchlists, and LLM prompts (stored in DB)
- Report branding (primary/secondary colors, logo)
- Schedule (cron expression + timezone)
- Recipient list (To / Cc / Bcc)
- Claude model tier (starter / pro / enterprise)
- Per-org LangGraph checkpoint file

---

## Table of Contents

1. [Quickstart](#1-quickstart)
2. [Adding an Organization](#2-adding-an-organization)
3. [Report Format](#3-report-format)
4. [Environment Variables](#4-environment-variables)
5. [CLI Commands](#5-cli-commands)
6. [Model Tiers](#6-model-tiers)
7. [Project Structure](#7-project-structure)
8. [Database](#8-database)
9. [Running Tests](#9-running-tests)
10. [Cost](#10-cost)

---

## 1. Quickstart

### System dependencies (required for PDF generation)

```bash
# macOS
brew install pango libffi

# Ubuntu/Debian
sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf2.0-0
```

### Install and initialize

```bash
# 1. Clone and enter the project
git clone https://github.com/joyce04/media_executive_briefing_automation
cd media_executive_briefing_automation

# 2. Configure environment
cp .env.example .env
# Edit .env — add OPENROUTER_API_KEY, SMTP credentials, JWT_SECRET

# 3. Install dependencies (creates .venv automatically)
uv sync

# 4. Initialize the database
uv run python scripts/db_init.py

# 5. Test the pipeline in dry-run mode (no email sent)
uv run python scripts/run_pipeline.py --org <slug> --dry-run
```

### Run a pipeline manually

```bash
# Dry run — writes report files, skips email
uv run python scripts/run_pipeline.py --org acme --dry-run

# Specific date
uv run python scripts/run_pipeline.py --org acme --date 2026-04-01 --dry-run

# Send email
uv run python scripts/run_pipeline.py --org acme --date 2026-04-01
```

### Backfill a date range

```bash
uv run python scripts/backfill.py --org acme --start 2026-03-01 --end 2026-03-07 --dry-run
```

LangGraph's `thread_id = "{org_id}_{run_date}"` checkpointing means a re-run for the same date resumes from the last successfully completed node.

---

## 2. Adding an Organization

### Via script (no web UI needed)

```bash
uv run python scripts/add_org.py \
  --slug acme \
  --name "Acme Corporation" \
  --name-short ACME \
  --language en \
  --timezone "America/New_York" \
  --schedule "0 7 * * *" \
  --primary-color "#1a56db" \
  --secondary-color "#1e429f" \
  --model-tier pro
```

### Configure sources

Sources are stored in the `org_sources` table. Each source needs a `source_type` (`rss` or `google_news_rss`) and either a URL or query string.

```python
from database.repositories.org_repo import upsert_org_source, get_org_by_slug

org = get_org_by_slug("acme")
upsert_org_source(org["id"], {
    "source_id": "techcrunch_rss",
    "name": "TechCrunch",
    "source_type": "rss",
    "url": "https://techcrunch.com/feed/",
    "language": "en",
    "priority": 1,
})
upsert_org_source(org["id"], {
    "source_id": "acme_gnews",
    "name": "Google News — Acme",
    "source_type": "google_news_rss",
    "query": "Acme Corporation OR ACME Inc",
    "language": "en",
    "priority": 1,
})
```

### Configure entities (watchlist)

Entities drive the LLM's attention during analysis and synthesis. Supported `entity_type` values: `keyword_core`, `person`, `player`, `team`, `tournament`.

```python
from database.repositories.org_repo import upsert_org_entity

upsert_org_entity(org["id"], {
    "entity_type": "keyword_core",
    "name_primary": "Acme Corporation",
    "name_alt": "ACME",
    "priority": 1,
    "attributes": {"watch_reason": "primary brand monitoring"},
})
upsert_org_entity(org["id"], {
    "entity_type": "person",
    "name_primary": "Jane Smith",
    "priority": 1,
    "attributes": {"watch_reason": "CEO — flag any news mentioning her"},
})
```

### Add recipients

```python
from database.repositories.org_repo import add_org_recipient

add_org_recipient(org["id"], {"role": "to",  "name": "Leadership Team", "email": "team@acme.com"})
add_org_recipient(org["id"], {"role": "bcc", "name": "Archive",          "email": "archive@acme.com"})
```

### Custom LLM prompts (optional)

Override the default system prompts per node:

```python
from database.repositories.org_repo import upsert_org_prompt

upsert_org_prompt(org["id"], "synthesis",
    "You are the Chief Intelligence Analyst for Acme Corporation. "
    "Focus on competitive threats, partnership opportunities, and regulatory news. "
    "Return JSON only.")
```

Prompt keys: `keyword_generation`, `analysis`, `synthesis`, `deduplication`.

### Test the new org

```bash
uv run python scripts/run_pipeline.py --org acme --dry-run
```

---

## 3. Report Format

Each daily email contains:

| Section | Content |
|---------|---------|
| **Executive Summary** | 5–7 bullet points — the most important things from today |
| **Top Trending Narratives** | Up to 5 cross-article story clusters, ranked by article count and sentiment distribution |
| **NEW** | New articles not seen in the last 7 days. Full analysis: sentiment, topic, entities, summary, risk flag, relevance score |
| **DEVELOPING** | Ongoing stories with significant new information since yesterday. Same detail as NEW |
| **CONTINUING** | Stories unchanged from yesterday. Title only — no repeated analysis |
| **RESOLVED** | Stories that have concluded. Listed for awareness |

Report branding (header color, secondary color) is pulled from the org record. The PDF filename is `{org_short}_Briefing_{YYYY-MM-DD}.pdf`.

---

## 4. Environment Variables

### Required

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | OpenRouter API key (`sk-or-v1-...`) |
| `SMTP_HOST` | SMTP server hostname (e.g. `smtp.gmail.com`) |
| `SMTP_PORT` | SMTP port (typically `587` for STARTTLS) |
| `SMTP_USER` | Sender email address |
| `SMTP_PASSWORD` | SMTP password or app password |
| `JWT_SECRET` | Secret for signing JWT tokens (web UI auth) |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_PATH` | `./data/media_intel.db` | SQLite database path |
| `REPORTS_OUTPUT_DIR` | `./data/reports` | Report output directory |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `COLLECTION_MAX_AGE_HOURS` | `24` | Drop RSS entries older than N hours |
| `GOOGLE_CLIENT_ID` | — | Google OAuth client ID (web UI sign-in) |
| `GOOGLE_CLIENT_SECRET` | — | Google OAuth client secret |
| `STRIPE_SECRET_KEY` | — | Stripe API key (billing) |
| `STRIPE_WEBHOOK_SECRET` | — | Stripe webhook signing secret |
| `FRONTEND_URL` | `http://localhost:5173` | Allowed CORS origin for web UI |

---

## 5. CLI Commands

| Command | Arguments | Description |
|---------|-----------|-------------|
| `python scripts/db_init.py` | — | Create or migrate `media_intel.db` |
| `python scripts/add_org.py` | `--slug --name --name-short ...` | Create a new org |
| `python scripts/run_pipeline.py` | `--org SLUG` `--date YYYY-MM-DD` `--dry-run` | Run pipeline once |
| `python scripts/backfill.py` | `--org SLUG` `--start YYYY-MM-DD` `--end YYYY-MM-DD` `--dry-run` | Reprocess a date range |
| `python scripts/test_sources.py` | `--org SLUG` | Verify RSS sources are reachable |

---

## 6. Model Tiers

Each org has a `model_tier` that maps to a Claude model pair:

| Tier | Fast model (dedup, filter, novelty) | Smart model (analysis, synthesis) | Cost / day |
|------|--------------------------------------|----------------------------------|------------|
| `starter` | claude-haiku-4-5 | claude-haiku-4-5 | ~$0.002–0.01 |
| `pro` | claude-haiku-4-5 | claude-sonnet-4-6 | ~$0.05–0.15 |
| `enterprise` | claude-sonnet-4-6 | claude-opus-4-7 | ~$0.50–2.00 |

Set `model_tier` when creating the org or update it directly in the `organizations` table.

---

## 7. Project Structure

```
media_intel/
│
├── config/
│   └── settings.py                  # Pydantic Settings — reads .env
│
├── models/
│   ├── state.py                     # PipelineState TypedDict (org_id, org_config, ...)
│   ├── article.py                   # RawArticle, DeduplicatedArticle, ArticleAnalysis
│   ├── report.py                    # DailySynthesis, DailyReport
│   └── enums.py                     # Sentiment, TopicCategory, RiskLevel, NoveltyStatus
│
├── database/
│   ├── schema_v2.sql                # Multi-tenant DDL (20 tables)
│   ├── connection.py                # SQLite context manager (WAL mode)
│   └── repositories/
│       ├── org_repo.py              # Org CRUD, get_org_config(), API key management
│       ├── user_repo.py             # User accounts, refresh tokens
│       ├── billing_repo.py          # Plans, subscriptions (Stripe-backed)
│       ├── article_repo.py          # raw + deduplicated articles CRUD
│       ├── analysis_repo.py         # Article analyses + sentiment history CRUD
│       ├── report_repo.py           # Synthesis + generated reports CRUD
│       ├── pipeline_repo.py         # Pipeline run status tracking
│       └── continuity_repo.py       # Story continuity + keyword log CRUD
│
├── collectors/
│   ├── base.py                      # BaseCollector ABC + CollectedArticle dataclass
│   ├── rss_collector.py             # Generic feedparser RSS; after_date param
│   ├── google_news_rss.py           # Google News RSS; after_date/before_date support
│   ├── naver_news.py                # Naver Search API (Korean sources)
│   ├── dynamic_search.py            # LLM-generated keyword queries
│   ├── registry.py                  # build_registry(sources) — from org_config
│   ├── bbc_sport.py                 # BBC Sport
│   ├── guardian_football.py         # The Guardian
│   ├── yonhap.py                    # Yonhap News
│   └── fifa_news.py                 # FIFA News
│
├── agents/
│   ├── llm_client.py                # get_org_llm(org, mode) — per-org model tier routing
│   ├── keyword_node.py              # Node 1: LLM-generated search queries
│   ├── collect_node.py              # Node 2: all org sources + dynamic search
│   ├── filter_node.py               # Node 3: relevance + significance filter
│   ├── deduplicate_node.py          # Node 4: 3-pass dedup
│   ├── novelty_node.py              # Node 5: cross-day novelty classification
│   ├── analyze_node.py              # Node 6: per-article sentiment/topic/risk analysis
│   ├── synthesize_node.py           # Node 7: executive briefing synthesis
│   └── report_node.py               # Node 8: render + SMTP delivery
│
├── pipeline/
│   ├── graph.py                     # LangGraph StateGraph wiring (8 nodes)
│   ├── orchestrator.py              # run_pipeline_for_org(org_id) + compat shim
│   ├── scheduler.py                 # Legacy single-org APScheduler (superseded by multi_scheduler)
│   └── health_check.py              # HTTP /health endpoint
│
├── reports/
│   ├── generator.py                 # Builds Jinja2 context from DB state
│   ├── pdf_generator.py             # WeasyPrint HTML → A4 PDF
│   ├── email_sender.py              # SMTP delivery with HTML + PDF attachment
│   └── templates/
│       ├── email_report.html.jinja2 # Email template (org branding via {{ org.* }})
│       └── pdf_report.html.jinja2   # PDF template (org branding via {{ org.* }})
│
├── scripts/
│   ├── db_init.py                   # Initialize / migrate database
│   ├── add_org.py                   # Create a new org from CLI
│   ├── run_pipeline.py              # Run pipeline for one org
│   ├── backfill.py                  # Backfill a date range
│   ├── test_sources.py              # Verify RSS sources
│   └── migrate_to_multitenant.py    # One-time migration from single-org schema
│
├── data/
│   ├── media_intel.db               # Main SQLite database (all orgs)
│   └── checkpoints/
│       └── {org_slug}.db            # Per-org LangGraph checkpoint files
│
├── .github/workflows/
│   └── daily_pipeline.yml           # GitHub Actions: runs pipeline daily
│
└── tests/
    ├── conftest.py
    ├── unit/
    ├── integration/
    └── fixtures/
```

---

## 8. Database

All pipeline tables include an `org_id` column so a single database serves all organizations.

### Core tables

| Table | Description |
|-------|-------------|
| `organizations` | One row per org — slug, name, branding, schedule, timezone, model_tier |
| `org_sources` | News sources per org (RSS/Google News URLs and queries) |
| `org_entities` | Tracked entities per org — people, keywords, teams, tournaments |
| `org_prompts` | Custom LLM system prompts per org per pipeline node |
| `org_recipients` | Email recipients per org (To / Cc / Bcc roles) |
| `api_keys` | Hashed API keys for programmatic pipeline access |

### Pipeline tables (all include `org_id`)

| Table | Description |
|-------|-------------|
| `pipeline_runs` | One row per run — status, timestamps, article counts |
| `raw_articles` | Every collected article with URL hash for dedup |
| `deduplicated_articles` | Canonical article per same-day cluster |
| `article_analyses` | LLM output — sentiment, topics, entities, summaries, relevance score, risk flag |
| `daily_synthesis` | Executive briefing — narratives, alerts, actions, executive summary |
| `generated_reports` | Report file paths and SMTP delivery status |
| `daily_sentiment_history` | Aggregate sentiment per day for trend computation |
| `story_continuity` | Cross-day story clusters — tracks days_active, status, resolution |
| `search_keyword_log` | LLM-generated keywords and article yield per query |

### Auth and billing tables

| Table | Description |
|-------|-------------|
| `users` | User accounts (email/password or Google OAuth) |
| `user_orgs` | Many-to-many: user ↔ org with role (owner / admin / member) |
| `refresh_tokens` | JWT refresh tokens (30d TTL, httpOnly cookie) |
| `plans` | Subscription plans — starter / pro / enterprise |
| `subscriptions` | Per-org subscription status and Stripe IDs |

Per-org LangGraph checkpoints are stored in `data/checkpoints/{org_slug}.db`.

---

## 9. Running Tests

```bash
# Unit tests — all LLM calls mocked, in-memory SQLite
uv run pytest tests/unit/ -v

# Integration tests — full pipeline on fixture articles
uv run pytest tests/integration/ -v

# With coverage
uv run pytest tests/unit/ --cov=agents --cov=collectors --cov-report=term-missing
```

---

## 10. Cost

Costs are per-org per-day, driven by model tier.

| Tier | Typical cost |
|------|-------------|
| Starter (Haiku / Haiku) | $0.002–0.01 / day |
| Pro (Haiku / Sonnet) | $0.05–0.15 / day |
| Enterprise (Sonnet / Opus) | $0.50–2.00 / day |

Actual spend per run is logged in `pipeline_runs.estimated_cost_usd`.
