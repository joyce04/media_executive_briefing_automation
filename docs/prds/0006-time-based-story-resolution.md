# PRD 0006 — Time-based auto-resolution for dormant Stories

## Problem Statement

CONTEXT.md defines `RESOLVED` as one of the four **Novelty** statuses for a Canonical Article, and explicitly notes:

> RESOLVED: The matched Story appears to have concluded based on the article's own language (verdict reached, deal signed, tournament ended). Listed for awareness only. **Today this label is LLM-assigned only — there is no time-based auto-resolution rule (e.g. "dormant for N days").**

Concretely, the only way a Story today gets marked `resolved` is if `agents/novelty_node.py`'s LLM classifier looks at a single Canonical Article and the article itself contains language indicating conclusion ("the verdict was..."), at which point the LLM returns `"resolved"` for that article and `continuity_repo.upsert_story_cluster` writes that status into `story_continuity.status`.

The consequence: a Story that simply **stops being talked about** — no new articles for a week, two weeks, a month — keeps `status = 'developing'` or `'continuing'` forever. The `get_active_stories(org_id, lookback_days=7)` query in `continuity_repo.py` excludes those rows via `last_seen_date >= date('now', '-7 days')`, so the *novelty classifier* doesn't see stale Stories — but the Stories themselves accumulate as `developing`/`continuing` in the table indefinitely. Anything that reports on Story counts, durations, or status distributions (current or future dashboards, the `daily_synthesis.trending_narratives` calculation, future analytics) sees these phantom-active Stories and produces misleading numbers.

Additionally, the `RESOLVED` Story status is the natural signal an operator would expect for "a story that has gone quiet." Without it, operators (and any downstream report or dashboard) have no clean way to distinguish "ended naturally" from "still ongoing but not in today's news cycle."

## Solution

A nightly sweep marks Stories as `resolved` after they have been dormant — no new Canonical Article matched to them — for a configurable number of days. The sweep runs as a final step inside the existing pipeline (so it piggybacks on the daily cron, no new schedule needed) or as a standalone job that touches every Organization once per day.

From the operator's perspective:

- A Story that has not had a follow-up article in N days (default: 14) is automatically marked `resolved`, with `resolution_date = today` and a note in a new `resolution_reason` column distinguishing time-based from LLM-detected resolution.
- The configurable dormancy threshold lives on the Organization (`organizations.story_dormancy_resolve_days`, default 14) so different Organizations with different news cycles can tune independently.
- The next day's Briefing's `RESOLVED` section lists these auto-resolved Stories one final time (for awareness), then they drop off forever.

## User Stories

1. As an operator at KFA, I want Stories that have not been matched by a new Canonical Article in 14 days to be automatically marked `resolved`, so that my `story_continuity` table reflects current reality rather than accumulating zombie Stories.
2. As an operator, I want the dormancy threshold to be a per-Organization setting (`organizations.story_dormancy_resolve_days`), so that fast-moving news cycles (sports) and slow-moving ones (regulatory) can tune independently.
3. As an operator, I want a sensible default for the dormancy threshold (14 days), so that the platform behaves sanely for a freshly-onboarded Organization without explicit tuning.
4. As an operator, I want time-based and LLM-based resolutions distinguished in the database (`story_continuity.resolution_reason TEXT` with values `'llm_detected'` or `'dormant'`), so that I can report on why each Story ended.
5. As an operator, I want the daily Briefing's `RESOLVED` section to include time-based auto-resolutions for the first day they are resolved (so the operator sees the closure), and to drop them from the section on subsequent days, so that the email is not noisy with re-listed resolved Stories.
6. As an operator, I want auto-resolution to set `story_continuity.resolution_date` to the day the sweep ran (not the day the Story last appeared), so that audit queries can distinguish "when did we decide it ended" from "when did we last see it."
7. As an operator, I want the auto-resolution sweep to be idempotent — running it twice on the same day produces no changes on the second run — so that re-running the daily pipeline is safe.
8. As a developer, I want the sweep to be a deep, testable module `StoryResolver` (or `auto_resolve_dormant_stories(org_id, run_date, threshold_days)`) with no LLM dependency, no I/O outside the SQLite connection, and a return value of the resolved Story IDs and titles for reporting, so that the sweep is trivially unit-testable.
9. As a developer, I want the sweep to run inside the pipeline (as a final step after `report_node` or between `novelty_node` and `analyze_node`), so that it executes exactly once per Organization per day without a separate cron.
10. As an operator, I want the LLM-based resolution path (the existing one in `novelty_node`) to continue to work and to overwrite a dormant-resolution on the same Story if the LLM later detects a conclusion article, so that the more specific signal wins.
11. As an operator, I want a CLI command `scripts/list_dormant_stories.py --org SLUG --threshold-days N` (depends on PRD 0002) to preview which Stories would be auto-resolved before changing the threshold, so that tuning is not blind.
12. As an operator running a backfill, I want the sweep to skip when running for a historical date older than today (the dormancy check should not run during backfills), so that re-processing 2025's data does not retroactively resolve Stories that an operator already classified.
13. As an operator, I want a one-shot "purge" CLI (`scripts/resolve_dormant_now.py --org SLUG --threshold-days N --dry-run`) to clean up the existing zombie Story backlog when the feature first lands, so that the new sweep starts from a sane state instead of resolving thousands of Stories on the first run.
14. As a developer, I want the database migration to add `story_continuity.resolution_reason TEXT` (NULL allowed) and back-fill `resolution_reason = 'llm_detected'` for every row that already has a non-NULL `resolution_date`, so that historical data is correctly attributed.
15. As a developer, I want the database migration to add `organizations.story_dormancy_resolve_days INTEGER NOT NULL DEFAULT 14`, so that existing Organizations get the default value without manual update.
16. As an operator, I want the structured log emitted by the sweep to include `(org_id, swept_count, resolved_ids[:10])`, so that the daily run's observability surface tells me how many Stories closed and which ones (capped to avoid log spam).
17. As an operator, I want the daily Briefing to NOT mention a time-based resolution as a "Trending Narrative" or "Crisis Alert" (these are forward-looking signals), so that closure is reported as closure, not as new activity.
18. As an operator, I want the sweep to refuse to resolve a Story that was created today (i.e. `first_seen_date == today`), since such a Story has not had time to develop, so that a single-article Story is not immediately marked dormant by an off-by-one threshold bug.

## Implementation Decisions

**Schema changes** (single PR):

```sql
ALTER TABLE story_continuity
  ADD COLUMN resolution_reason TEXT;
  -- 'llm_detected' | 'dormant' | NULL (not yet resolved)

-- Back-fill: every existing resolved Story is presumed LLM-detected
UPDATE story_continuity
  SET resolution_reason = 'llm_detected'
  WHERE resolution_date IS NOT NULL AND resolution_reason IS NULL;

ALTER TABLE organizations
  ADD COLUMN story_dormancy_resolve_days INTEGER NOT NULL DEFAULT 14;
```

**New module: `agents/story_resolver.py` (or `pipeline/story_resolver.py`).**

```python
# Sketch (final shape TBD)
def auto_resolve_dormant_stories(
    org_id: int,
    today: date,
    threshold_days: int,
) -> list[dict]:
    """
    Mark Stories as resolved if their last_seen_date is older than
    (today - threshold_days) AND status != 'resolved' AND first_seen_date < today.

    Returns a list of dicts: {story_cluster_id, canonical_title, last_seen_date, days_dormant}
    for inclusion in the day's Briefing as one-time RESOLVED entries.

    Idempotent: running twice on the same day produces no new resolutions.
    """
```

Pure SQL inside; no LLM, no network, no other agent dependencies. Trivially unit-testable.

**Pipeline integration.**

Adding a 9th node is overkill for an idempotent SQL-only sweep. Two cleaner options:

- **Option A**: call `auto_resolve_dormant_stories()` from the existing `novelty_node`'s entry point, just after the LLM classification phase. The two resolution paths (LLM and dormancy) are then co-located, which makes the precedence rule ("LLM wins over dormancy if both fire on the same Story on the same day") easy to enforce by ordering: LLM runs first; dormancy fills in the rest.
- **Option B**: call it from `synthesize_node`'s entry point, just before the Briefing is composed, so the resolved-list is available to the synthesis prompt as "Stories that closed today."

Recommendation: **Option A** for the resolution itself (semantically belongs to novelty classification), with a small read-back in `synthesize_node` to pull the day's resolved-by-dormancy list for the `RESOLVED` section of the Briefing.

**Backfill guard.** The sweep refuses to run when `today < date.today(KST)` — i.e. when the pipeline is being run for a historical date during a backfill. Implemented as a precondition check in the resolver itself.

**Cleanup script for first-run backlog.**

`scripts/resolve_dormant_now.py --org SLUG --threshold-days N [--dry-run]`:

1. Resolves the resolver against the org's current settings (or `--threshold-days` override).
2. With `--dry-run`, prints the would-be-resolved Story list and exits.
3. Without `--dry-run`, applies the resolution as a single `UPDATE ... WHERE` statement and logs the result.

Run once per Organization at deploy time to clean up the zombie backlog accumulated to date.

**Default value choice (14 days).** Picked on the principle that a news Story unmentioned for two weeks is, for KFA's domain (football), almost certainly done. Other Organizations can tune. The default is not load-bearing — it can be revisited based on operator feedback.

**Precedence rule.** If an LLM-based resolution and a time-based resolution would both apply to the same Story on the same day (e.g. an article with conclusion language arrives 15 days after the Story last appeared), the LLM-based one wins — `resolution_reason = 'llm_detected'`. The resolver running second sees `status = 'resolved'` already and does nothing.

**What does NOT change.**

- The four-status Novelty taxonomy (`new | developing | continuing | resolved`).
- The LLM-based resolution path in `novelty_node`.
- The `get_active_stories(org_id, lookback_days=7)` query that the novelty classifier uses to know what Stories exist — this query continues to filter by `last_seen_date >= ...`, so once a Story is resolved it stops being seen anyway.
- The synthesis prompt or output schema, beyond the addition of the day-of-resolution entries to the `RESOLVED` section.

## Testing Decisions

A good test of this resolver asserts the SQL effect on a controlled DB state. Set up a `story_continuity` with a known mix of dormant and active rows, call the resolver, assert exactly the right rows changed and the right values were written. No LLM mocking needed (the resolver doesn't call any).

**Modules to test:**

- `auto_resolve_dormant_stories()` — given a seeded DB with stories at varying `last_seen_date` values (today, today-1, today-13, today-14, today-15, today-100), with the threshold set to 14, only rows where `last_seen_date <= today-15` (strictly older than threshold) are resolved; rows where `first_seen_date == today` are excluded; idempotent on second run. (Unit test, in-memory SQLite.)
- Precondition guard — calling with `today < date.today()` raises; calling with `today == date.today()` proceeds. (Unit test.)
- Migration script — adds the two columns; back-fill of `resolution_reason = 'llm_detected'` is correct; existing data is untouched outside those two columns. (Integration test against a copy of prod-shape DB.)
- Pipeline integration — running the full DAG produces a Briefing whose `RESOLVED` section contains the day's auto-resolved Story titles. (Integration test, mocked LLM.)
- Cleanup script — `--dry-run` writes nothing; without it, the backlog is resolved; structured log includes counts. (Integration test, in-memory DB.)

**Prior art:** `tests/unit/test_novelty.py` exercises `continuity_repo` against in-memory SQLite — the new resolver tests mirror this pattern exactly.

## Out of Scope

- Re-opening a previously-resolved Story if a new article matches it weeks later. Today the novelty classifier would treat the new article as `NEW` (since `get_active_stories` excludes resolved Stories from the matching set) and start a fresh Story. That behavior is preserved; designing "Story re-opening" is its own PRD if operators report wanting it.
- Configurable resolution-reason values beyond `llm_detected` / `dormant`. Two values is enough.
- Surfacing resolution data in any analytics dashboard. There is no dashboard today; when one is built, it can read the new column.
- A "dormant warning" mechanism (e.g. surface Stories that will be auto-resolved tomorrow). Niche; revisit if operator feedback asks for it.
- Per-Story override of the dormancy threshold (e.g. "this election Story shouldn't auto-close even if it goes quiet for a month"). Per-Org tuning is enough for now; revisit if needed.

## Further Notes

- This PRD is the smallest of the seven and has no cross-PRD dependencies. It can ship in a single PR within a week.
- The CONTEXT.md note about RESOLVED being "LLM-assigned only" gets updated by this PR to read "LLM-assigned OR time-based auto-resolution after N days dormant (per-Organization configurable, default 14)."
- The `resolution_reason` column is a small but useful audit hook — once you have it, every "why did this Story close?" question becomes a one-column read instead of an LLM rerun or a heuristic. Worth the column.
- The cleanup script (`resolve_dormant_now.py`) is the operational equivalent of a one-shot data migration. It's a script rather than a migration because re-running it later (after the cron has been running for months) is occasionally useful when the threshold changes; folding it into the migration would make that awkward.
