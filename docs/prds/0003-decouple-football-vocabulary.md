# PRD 0003 — Decouple football vocabulary from the core platform

## Problem Statement

The README, the CONTEXT.md, and the `organizations` schema all describe a generic multi-tenant media-intelligence platform. The actual code is shot through with the assumption that every Organization is a football federation. CONTEXT.md flags this explicitly:

> Football-specific vocabulary (`player`, `team`, `tournament`, `match_result`, `coaching_staff`) is present in `models/enums.py::TopicCategory` and `org_entities.entity_type`. Conceptually these are tenant-specific category values that leaked into the core enum because the first Organization (KFA) is a football federation. They are not part of the generic domain — see ADR (pending) on extracting per-Organization topic taxonomies.

Concrete coupling sites today:

- `models/enums.py::TopicCategory` enumerates 14 values; 11 are football-specific (`match_result`, `transfer`, `coaching_staff`, `youth_football`, `national_team`, `player_spotlight`, `tournament_news`, `transfer_window`, etc.). Only `governance`, `sponsorship`, `controversy`, `infrastructure`, `international`, `other` are generic.
- `agents/analyze_node.py` bakes the football-specific topic list **as a literal string** into the LLM prompt's output schema (`ANALYSIS_SCHEMA`). Any non-football Organization gets back analyses that classify their news as "match_result" or "transfer_window" no matter what the article actually says.
- The analysis output schema has fixed football-shaped entity-mention fields: `players_mentioned`, `tracked_players_mentioned`, `clubs_mentioned`, `officials_mentioned`, `venues_mentioned`. A generic Organization has no equivalent for "clubs" or "venues."
- `org_entities.entity_type` accepts `'player' | 'tournament' | 'keyword_core' | 'person' | 'team'`. Three of the five are football labels.
- `agents/analyze_node.py::_build_watchlist_context` filters specifically for `entity_type in ("player", "person")`.
- `agents/synthesize_node.py::_build_entity_context` filters `entity_type in ("player", "person")` for one render path and `entity_type == "tournament"` for another. Anything outside these subtypes is invisible to the synthesis.

A second (non-football) Organization cannot be onboarded today without the LLM producing nonsensical outputs. The "multi-tenant" claim is therefore aspirational beyond the football vertical.

## Solution

Topic taxonomy and entity-rendering become per-Organization configuration. The core platform exposes a generic shape: `Person | Group | Event | Keyword` (the CONTEXT.md taxonomy) and a free-form per-Organization topic list. The football labels become KFA's specific topic taxonomy, stored as data in the KFA Organization row, not as global enums.

Concretely:

- `TopicCategory` stops being a global Python `Enum` and becomes a per-Organization list of strings stored on the `organizations` row (or in a `org_topic_taxonomy` table). The analyze-node prompt renders each Organization's taxonomy dynamically into its `ANALYSIS_SCHEMA`.
- The fixed `*_mentioned` output fields collapse into one generic `entities_mentioned` field of the shape `[{type, name, role_or_context, is_tracked}]`. The renderer (HTML/PDF email) groups these by `type` for display, using each Organization's own type vocabulary.
- `org_entities.entity_type` accepts the four generic subtypes from CONTEXT.md (`person | group | event | keyword`). The football labels (`player`, `team`, `tournament`) become per-Organization display aliases via a lightweight `org_entity_type_aliases` table, so KFA continues to see "player" labels in its briefing while a new customer sees "executive" or "competitor."
- The watchlist-context and entity-context builders in `analyze_node` and `synthesize_node` stop hardcoding subtypes and instead iterate every active Entity for the Organization, grouped by its (aliased) type.

A KFA reader sees no behavioral change in their briefing's narrative content; a new non-football customer can onboard without seeing football vocabulary in their output.

## User Stories

1. As an operator onboarding a non-football Organization, I want to set a topic taxonomy that fits my domain (e.g. `product_launch | regulatory_news | competitor_move | executive_change | partnership | crisis | other`), so that the analyses I receive use my own categories instead of football ones.
2. As an operator, I want the topic taxonomy to live in the Organization's row (or its own table) and be editable without code changes, so that I can refine it as I observe how the LLM uses it.
3. As an operator, I want a sensible **default** generic taxonomy used when an Organization sets none (`announcement | strategic_move | financial | regulatory | personnel | partnership | controversy | other`), so that the platform works out of the box for a new tenant.
4. As an operator at KFA, I want my existing football taxonomy preserved exactly as-is post-migration, so that historical comparisons remain valid and Korean briefing readers see the same categories they did yesterday.
5. As an operator, I want each Organization to declare entity-type display aliases (e.g. `{person: "executive", group: "company", event: "campaign"}`), so that the briefing's section headings and prose use my own vocabulary.
6. As an operator, I want the analysis output's `entities_mentioned` field to be a generic shape `[{type, name, role_or_context, is_tracked}]`, so that the analysis no longer presupposes football-specific roles like "club" or "venue."
7. As an operator at KFA, I want the existing `players_mentioned` / `clubs_mentioned` / `officials_mentioned` / `venues_mentioned` data preserved as a history view but new analyses write to the generic `entities_mentioned` shape, so that old reports continue to render and new ones use the better model.
8. As a developer, I want the analyze-node prompt to render the Organization's topic list dynamically (templated), so that adding a topic value never requires code or prompt edits.
9. As a developer, I want a deep, testable module `OrgTaxonomy` that encapsulates "given an Organization, return its topic list, entity-type list, and entity-type display aliases" with a fallback to platform defaults, so that every callsite (`analyze_node`, `synthesize_node`, `reports/generator.py`) goes through one interface.
10. As a developer, I want `TopicCategory` removed from `models/enums.py` (or downgraded to a documentation-only `Literal[...]` for the default taxonomy) so that there is no global enum tempting future code to assume the platform's domain.
11. As an operator, I want a schema migration that adds the new fields (`organizations.topic_taxonomy`, `organizations.entity_type_aliases`, `article_analyses.entities_mentioned`) and back-fills KFA's row with the existing football values, so that no manual data entry is required for the cutover.
12. As an operator, I want the migration to keep the old columns (`players_mentioned`, `clubs_mentioned`, `officials_mentioned`, `venues_mentioned`) read-only-but-present for one release cycle, so that any reporting query referring to them does not break overnight.
13. As an operator at KFA, I want the email and PDF templates to continue rendering the same section headings ("Players Mentioned," "Clubs Mentioned," etc.) by reading from `entity_type_aliases`, so that the visual output is unchanged for KFA recipients.
14. As an operator at a non-football Organization, I want the email template to render section headings using my own aliases (e.g. "Executives Mentioned," "Companies Mentioned"), so that my briefing reads naturally.
15. As a developer, I want a snapshot test fixture that captures KFA's rendered analyze-node prompt before and after the refactor, so that we can prove the prompt sent to the LLM for KFA is byte-identical post-migration (i.e. no behavioral drift for the existing tenant).
16. As a developer, I want a paired integration test that runs the full pipeline for a new fixture Organization with a non-football taxonomy and asserts that the analyses come back with topics from that taxonomy (not from the football one), so that the decoupling is observably correct.
17. As an operator, I want every prompt-rendering site to refuse to run if an Organization has neither a custom taxonomy nor accepted the platform default, with a clear error pointing to the configuration step, so that "blank taxonomy" never silently produces garbage analyses.
18. As an operator, I want a `scripts/org_config.py --org SLUG set-taxonomy` subcommand (depends on PRD 0002) to edit an Organization's topic taxonomy from the CLI, so that I do not need to write SQL.
19. As a developer, I want this PRD's schema changes to be **additive only** (new columns, new optional table) in the first PR, with the read paths switched over in a second PR and the deprecated columns dropped in a third PR, so that a botched deploy is recoverable without a DB restore.
20. As a developer, I want an ADR (pending: ADR-0003 or similar) recording the per-Organization-taxonomy decision and the rejected alternatives (a single richer global enum; a multi-vertical pre-baked enum set), so that the rationale is preserved alongside the code.

## Implementation Decisions

**Schema changes** (additive in PR 1).

```sql
-- New columns on organizations
ALTER TABLE organizations ADD COLUMN topic_taxonomy TEXT NOT NULL DEFAULT '[]';
  -- JSON array of strings: ["match_result", "transfer", ...] for KFA;
  -- []-default falls through to platform-default taxonomy at read time.

ALTER TABLE organizations ADD COLUMN entity_type_aliases TEXT NOT NULL DEFAULT '{}';
  -- JSON object: {"person": "executive", "group": "company", "event": "campaign", "keyword": "topic"}
  -- {}-default uses generic labels at render time.

-- New column on article_analyses
ALTER TABLE article_analyses ADD COLUMN entities_mentioned TEXT NOT NULL DEFAULT '[]';
  -- JSON: [{"type": "person|group|event|keyword", "name": "...",
  --         "role_or_context": "...", "is_tracked": true|false}]

-- org_entities.entity_type stays as a TEXT column but the allowed values
-- expand to include the four generic subtypes. No data migration needed
-- on existing rows — KFA's 'player'/'team'/'tournament' rows are aliased
-- via organizations.entity_type_aliases at read time. A future PR may
-- convert them to canonical 'person'/'group'/'event' rows with the alias
-- preserved only in the display layer.
```

**`OrgTaxonomy` module** (`models/taxonomy.py` or `agents/org_taxonomy.py`).

```python
# Pseudo-interface (not final)
class OrgTaxonomy:
    @classmethod
    def for_org(cls, org: dict) -> "OrgTaxonomy": ...

    def topic_list(self) -> list[str]: ...
    # Returns the org's custom list if set, else PLATFORM_DEFAULT_TOPICS.

    def alias_for(self, generic_type: str) -> str: ...
    # 'person' -> 'executive' for non-football; 'person' -> 'person' if no alias.

    def section_heading(self, generic_type: str, plural: bool = True) -> str: ...
    # Used by report templates: e.g. "Executives Mentioned" or "Players Mentioned".

    def topic_schema_string(self) -> str: ...
    # The "|"-joined string the analyze_node injects into ANALYSIS_SCHEMA.
```

The class is constructed once per Pipeline Run and passed (or readable via `state["org_config"]`) into every node that renders prompts or report text. It is the **only** module that knows about the platform-default taxonomy values.

**Platform defaults.** A constant `PLATFORM_DEFAULT_TOPICS` (in `config/defaults.py` or similar) lists the generic taxonomy: `["announcement", "strategic_move", "financial", "regulatory", "personnel", "partnership", "controversy", "other"]`. Used only when an Organization explicitly accepts defaults — never silently.

**`ANALYSIS_SCHEMA` becomes a function.**

```python
# In agents/analyze_node.py
def build_analysis_schema(taxonomy: OrgTaxonomy) -> str:
    return f"""{{
      "sentiment": "positive|neutral|negative",
      ...
      "primary_topic": "{taxonomy.topic_schema_string()}",
      "secondary_topics": ["topic1"],
      "entities_mentioned": [
        {{"type": "person|group|event|keyword",
          "name": "Name",
          "role_or_context": "...",
          "is_tracked": true|false}}
      ],
      ...
    }}"""
```

The literal football enum string disappears.

**Watchlist context builders.** `_build_watchlist_context` (in `analyze_node`) and `_build_entity_context` (in `synthesize_node`) iterate the full entity list for the Organization, group by canonical generic type (`person | group | event | keyword`), and render each group using `taxonomy.section_heading(type)`. No hardcoded entity-type filters.

**Report templates** (`reports/templates/email_report.html.jinja2`, `pdf_report.html.jinja2`). Replace hardcoded `{% for p in players_mentioned %}` and friends with a loop over `entities_mentioned` grouped by type, with section headings from `taxonomy.section_heading()`. The Jinja context object exposes the `OrgTaxonomy` instance.

**Read-path migration for old `*_mentioned` fields.** A small adapter in `reports/generator.py` reads `article_analyses.entities_mentioned` if non-empty, otherwise falls back to assembling the same shape from the legacy `players_mentioned` / `clubs_mentioned` / `officials_mentioned` / `venues_mentioned` columns. This preserves historical reports' renderability for one release cycle.

**KFA seed values** for the migration:

```yaml
organizations[id=1].topic_taxonomy:
  - match_result
  - transfer
  - coaching_staff
  - governance
  - youth_football
  - national_team
  - sponsorship
  - controversy
  - infrastructure
  - international
  - player_spotlight
  - tournament_news
  - transfer_window
  - other

organizations[id=1].entity_type_aliases:
  person:  player        # KFA's 'person' entities are players
  group:   team          # KFA's 'group' entities are teams (clubs)
  event:   tournament    # KFA's 'event' entities are tournaments
  keyword: keyword       # no alias
```

This preserves KFA's prompt and rendering behavior exactly.

**Rollout sequence** (three PRs).

1. **PR 1** — schema additions; `OrgTaxonomy` module; migration script populates KFA's row with the seed values above; no production code reads the new fields yet. CI green, KFA pipeline unchanged.
2. **PR 2** — `analyze_node`, `synthesize_node`, `reports/generator.py`, templates switched to read from `OrgTaxonomy`. Snapshot test asserts KFA's rendered prompt is byte-identical to the pre-migration version. CI green, KFA pipeline behavior unchanged.
3. **PR 3** — drop the now-dead `players_mentioned` / `clubs_mentioned` / `officials_mentioned` / `venues_mentioned` columns from `article_analyses`. Drop `TopicCategory` enum from `models/enums.py`. Update CONTEXT.md to remove the "flagged ambiguity" note.

**ADR.** Write ADR-0003 (Per-Organization topic taxonomy and entity-type aliases) alongside PR 1. Records the decision, the rejected alternatives (a single richer global enum; pre-baked verticals), and the migration consequence (KFA prompt frozen as a snapshot test to prevent drift during refactor).

**What does NOT change.**

- The 8-node Media-Intel DAG.
- The Novelty / Story mechanics.
- The CONTEXT.md generic Entity subtype taxonomy itself (`Person | Group | Event | Keyword`) — that was already chosen in CONTEXT.md.
- The Korean-tone advisory in `synthesize_node` — that is `language_primary`-driven, not football-driven.

## Testing Decisions

A good test here asserts that **the LLM prompt sent for KFA is byte-identical pre- and post-refactor** (snapshot test on the rendered prompt string), and that a **non-football fixture Organization gets back analyses using its own taxonomy** (integration test on the full pipeline with a mocked LLM that echoes the prompt back so we can verify what was sent).

**Modules to test:**

- `OrgTaxonomy` — given an Organization row with custom taxonomy, returns it; with empty taxonomy, returns `PLATFORM_DEFAULT_TOPICS`; `alias_for` falls through to the input type when no alias is set; `section_heading` correctly pluralizes (or uses a configured plural). (Unit test, no DB needed — pass an Organization dict.)
- `build_analysis_schema(taxonomy)` — produces the expected schema string for KFA (snapshot fixture), produces a different schema string for a non-football fixture Org (snapshot fixture). (Unit test.)
- `analyze_node` end-to-end — mock LLM that records the prompt; assert the prompt sent for KFA matches the pre-refactor snapshot; assert the prompt sent for a non-football fixture Org contains only the new taxonomy values. (Integration test.)
- Report renderer — KFA's rendered HTML has section heading "Players Mentioned" (alias-driven), non-football fixture Org has "Executives Mentioned." (Snapshot test on rendered HTML.)
- Migration script — running it produces the expected KFA seed row; running it twice is idempotent; dry-run produces no writes. (Integration test against in-memory DB.)

**Prior art:**

- `tests/unit/test_analysis.py` already mocks `agents.llm_client.get_org_llm` and asserts on parsed analysis output — extend with prompt-capture instead of just response-mocking.
- `tests/integration/test_pipeline_e2e.py` runs the full DAG against canned fixtures — duplicate this with a second fixture Organization that has a non-football taxonomy, and add a parameterized loop over both Orgs.
- No snapshot-testing infrastructure exists yet in this repo. Adding `syrupy` or `pytest-snapshot` is the lightest-weight option (one new dev-dep, conventional pattern); call it out in PR 1.

## Out of Scope

- Letting Organizations override the four generic entity subtypes themselves (`person | group | event | keyword`). Aliases for *display* are in scope; renaming the canonical type list is not.
- Per-Organization custom analysis output fields beyond the generic `entities_mentioned`. If an Organization wants article-level "regulatory_jurisdiction" or "stock_ticker," that is a separate per-Org JSON column or future feature; this PRD doesn't make that pluggable.
- Migrating the Tactics pipeline to use `OrgTaxonomy`. Tactics has its own output schema (formations, concepts, leagues) that is separately football-specific and should follow its own decoupling PRD if and when a non-football tactics use case appears.
- Multi-language category names (e.g. a Korean operator may want their categories surfaced as Korean strings in the briefing). The taxonomy is a list of stable identifier strings; the human-readable label per locale is a future concern.
- Pre-baked "industry" taxonomy templates (Finance, Tech, Healthcare). Operators write their own list; a templates feature is a follow-up if onboarding friction is observed.

## Further Notes

- This PRD is intentionally invasive: it touches the schema, two of the eight pipeline nodes, the report generator, and both Jinja templates. The three-PR rollout with snapshot tests is the protection against regression on the live KFA tenant.
- The snapshot test on KFA's prompt is the most important single assertion in this body of work. If post-refactor the rendered prompt differs from pre-refactor for KFA (even by whitespace), the LLM's outputs could drift in subtle ways that operators only notice via a worse briefing weeks later. Pin the snapshot in PR 2 and treat changes to it as load-bearing decisions, not refactor artifacts.
- ADR-0003 (proposed) and this PRD ship together. The CONTEXT.md "Flagged ambiguity" entry referencing the pending ADR is the explicit IOU this PRD pays off.
- Sequencing: this PRD can ship independently of PRD 0001 (tactics multi-tenant) and PRD 0002 (CLI). It does benefit from PRD 0002 landing first because the new `--org` flag makes it much easier to test against a second (non-football) fixture Org without REPL gymnastics.
