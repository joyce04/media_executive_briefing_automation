# Media Intelligence Pipeline

A multi-tenant daily-briefing service that collects news for an **Organization**, removes duplicates, decides what is genuinely new since yesterday, analyzes the surviving articles, synthesizes an executive briefing, and emails it.

This document defines the domain language used throughout the codebase. Implementation terms (TypedDict, checkpoint file, LangGraph thread, asyncio worker) are deliberately excluded — they belong in code comments, not here.

## Language

### Tenancy

**Organization**:
A real-world brand or entity that subscribes to the briefing service (e.g. KFA, Acme Corp). Owns its sources, entities, recipients, prompts, branding, schedule, and model tier. The canonical multi-tenant unit — all pipeline data is partitioned by Organization.
_Avoid_: tenant, org (code shorthand only), customer, account, workspace, client.

**Model Tier**:
The compute budget an Organization buys: `starter` (Haiku for everything), `pro` (Haiku for fast steps, Sonnet for analysis/synthesis), `enterprise` (Sonnet/Opus). Drives both quality and per-run cost.
_Avoid_: plan (a billing concept, see "Flagged ambiguities"), subscription tier.

### Configuration owned by an Organization

**Source**:
A configured place to fetch news from for an Organization — an RSS feed URL, a Google News RSS query, or an API-backed feed. Has a priority and a language.
_Avoid_: feed, channel, provider.

**Entity**:
A tracked subject the Organization wants the briefing to pay attention to. Drives both keyword generation (so search queries hunt for the Entity) and analysis (so the LLM flags mentions and elevates relevance). Has a subtype.
_Avoid_: watchlist item (the collection is the watchlist; individual ones are Entities), subject, target.

The generic Entity subtypes are:
- **Person** — an individual (executive, public figure, athlete).
- **Group** — any multi-person actor (company, team, club, federation, agency).
- **Event** — a time-bounded happening with start/end dates (tournament, conference, product launch).
- **Keyword** — a free-form concept tracker for things that aren't a Person, Group, or Event (a brand name, a campaign theme, a regulatory topic).

The current `entity_type` enum in the schema accepts `player`, `team`, `tournament`, `keyword_core`, `person` — these are the KFA tenant's specialization of Person / Group / Event / Keyword. Generalizing this taxonomy is tracked as an open question (see "Flagged ambiguities").

**Recipient**:
An email address that receives the daily briefing for an Organization. Has a role (`to` / `cc` / `bcc`).
_Avoid_: subscriber, user, contact.

**Prompt Override**:
An Organization-specific replacement for one of the default LLM system prompts (keys: `keyword_generation`, `analysis`, `synthesis`, `deduplication`). Lets an Organization shape the briefing's voice and focus without code changes.
_Avoid_: custom prompt, template, instruction.

### The article lifecycle

**Article**:
One news item identified by a normalized URL. Collected from a Source within a given Pipeline Run. Carries the source-provided title, summary, and (where available) body text.
_Avoid_: post, story (Story has a specific meaning below), item, entry, document.

**Article Cluster**:
A group of Articles collected on the same day that the pipeline judges to be the same news event (matched via URL hash, then title fingerprint, then LLM semantic comparison). Has exactly one **Canonical Article**.
_Avoid_: duplicate group, dedup cluster (code term), merge group.

**Canonical Article**:
The single Article chosen to represent its Article Cluster — every downstream step (novelty, analysis, briefing) refers to this one. Sibling duplicates are kept in the database but not analyzed.
_Avoid_: primary article, lead article, master.

**Story**:
A cross-day thread that the same news event has produced over time. A Story is born when a Canonical Article cannot be matched to any prior Story in the lookback window (7 days). It collects Canonical Articles from subsequent days that the pipeline judges to be follow-ups on the same event.
_Avoid_: storyline, thread, narrative (Narrative has its own meaning), story cluster (code term).

### Novelty (the core mechanic)

The pipeline classifies every Canonical Article against the Stories active in the last 7 days, and emits one of four **Novelty** statuses. This is what stops the daily email from repeating yesterday's news.

**NEW**:
No Story exists in the lookback window that matches this Canonical Article. A new Story is created.

**DEVELOPING**:
Matches an existing Story AND contains substantive new facts — a new quote, a new development, a new number, a new actor — that a reader who saw yesterday's briefing has not yet seen.

**CONTINUING**:
Matches an existing Story but adds no substantive new facts. Typically a cosmetic rewrite, a republish, or a recap. Shown in the email as title-only, no re-analysis.

**RESOLVED**:
The matched Story appears to have concluded based on the article's own language (verdict reached, deal signed, tournament ended). Listed for awareness only. Today this label is **LLM-assigned only** — there is no time-based auto-resolution rule (e.g. "dormant for N days").

Only **NEW** and **DEVELOPING** Canonical Articles receive full per-article analysis (sentiment, topics, entities, risk, summary). **CONTINUING** and **RESOLVED** are reported but not re-analyzed.

### Outputs

**Pipeline Run**:
One end-to-end execution of the eight-node pipeline for one Organization on one date. Idempotent per (Organization, date) — re-running resumes from the last completed node.
_Avoid_: job, batch, execution.

**Briefing** (= Daily Synthesis):
The cross-article executive analysis produced once per Pipeline Run: Trending Narratives, Crisis Alerts, PR Opportunities, Competitive Intel, Recommended Actions, Executive Summary, sentiment trend. One Briefing per (Organization, date).
_Avoid_: synthesis (code term), digest, summary (Executive Summary is a sub-field).

**Trending Narrative**:
A cross-Article cluster within today's Briefing, ranked by Article count and sentiment, with up to 5 surfaced. Distinct from a **Story** — a Story is a cross-day thread; a Trending Narrative is a within-day grouping the LLM finds noteworthy. The two often overlap but are not the same thing.
_Avoid_: narrative cluster, today's stories.

**Crisis Alert**:
A flagged item within a Briefing the Organization probably needs to act on, with severity (`critical` / `high` / `medium`) and a recommended action.
_Avoid_: incident, warning.

**Recommended Action**:
A prioritized to-do attached to the Briefing, advisory in tone. Phrased as options to consider, not directives (especially in Korean output — see `agents/synthesize_node.py` for the tone rules).
_Avoid_: directive, instruction, task.

**Report**:
The rendered, delivered artifact of a Briefing — HTML email body + PDF attachment, mailed to the Organization's Recipients via SMTP. The Briefing is the content; the Report is the artifact.
_Avoid_: email (the email IS the report), output, document.

## Relationships

- An **Organization** has many **Sources**, **Entities**, **Recipients**, and **Prompt Overrides**.
- An **Organization** has exactly one **Model Tier**.
- A **Pipeline Run** belongs to one **Organization** and one date.
- A Pipeline Run produces many **Articles** → grouped into **Article Clusters** → each represented by one **Canonical Article**.
- A **Canonical Article** is assigned a **Novelty** status and (if matched) joins an existing **Story**, otherwise creates a new one.
- A **Story** spans multiple days and contains the Canonical Articles from each day's Pipeline Run that the pipeline judged to be the same event.
- A Pipeline Run produces one **Briefing**, which is rendered into one **Report** and emailed to the Organization's **Recipients**.
- A Briefing contains many **Trending Narratives**, **Crisis Alerts**, and **Recommended Actions**.

## Example dialogue

> **Dev:** "We had 40 raw **Articles** from the **Sources** today, and the email only shows 8. What happened to the rest?"
> **Domain expert:** "The filter dropped the irrelevant ones. The remaining ones got grouped into **Article Clusters** — each Cluster is one news event, the **Canonical Article** is the one we keep. Those Canonicals then get a **Novelty** check against the last 7 days' **Stories**. The **CONTINUING** and **RESOLVED** ones don't get full analysis — they're title-only in the email. Only **NEW** and **DEVELOPING** show up with the full sentiment/topic/summary treatment in the **Briefing**."
>
> **Dev:** "So if I add a new **Entity** for our CEO, what changes?"
> **Domain expert:** "Two things. The keyword node will start generating searches that include her name, so more **Articles** get pulled. And the analyze node will flag mentions of her in `players_mentioned`, plus push relevance scores up. She's a **Person** Entity — note that the schema's `entity_type` enum still says `person`, not the legacy `player` we use for athletes."

## Flagged ambiguities

- **"Plan" / "Subscription" / "User" / "ApiKey"** appear in `database/schema_v2.sql` but no code in this repo reads them. They are dead schema inherited from a sibling web-tier that does not exist in this repository. Do not treat them as part of the active domain.
- **"Org"** is universally used as a code-level shorthand for **Organization** (column names, variable names, function names). It is not a separate concept.
- **Football-specific vocabulary** (`player`, `team`, `tournament`, `match_result`, `coaching_staff`) is present in `models/enums.py::TopicCategory` and `org_entities.entity_type`. Conceptually these are tenant-specific category values that leaked into the core enum because the first Organization (KFA) is a football federation. They are **not** part of the generic domain — see ADR (pending) on extracting per-Organization topic taxonomies.
- **"Story" vs "Trending Narrative"** sound interchangeable but are not. A **Story** is a cross-day thread (lives in `story_continuity`). A **Trending Narrative** is a within-day cluster the synthesis LLM finds noteworthy (lives in `daily_synthesis.trending_narratives`). They often overlap but you cannot assume one maps to the other.
- **"Cluster"** is used in code for two unrelated groupings — same-day duplicates (`dedup_cluster_id`) and cross-day continuity (`story_cluster_id`). In domain language: the first is an **Article Cluster**, the second is a **Story**. Avoid the bare word "cluster" in conversation.
