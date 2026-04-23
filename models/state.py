from typing import TypedDict, Annotated
import operator


class PipelineState(TypedDict):
    # Multi-tenancy
    org_id: int
    org_config: dict  # {org, sources, entities, prompts, recipients} from org_repo.get_org_config()

    # Run identification
    run_date: str           # "YYYY-MM-DD" in org's timezone
    run_uuid: str           # UUID4 for this execution

    # Node 1: keyword_node output
    generated_keywords: list[dict]  # [{"query": str, "language": "ko"|"en", "source": str, "rationale": str}]

    # Node 2: collect_node output
    raw_article_ids: list[int]      # IDs written to raw_articles table

    # Node 3: filter_node output
    filtered_article_ids: list[int] | None  # None = filter hasn't run; [] = all dropped; [ids] = passed

    # Node 4: deduplicate_node output
    deduplicated_article_ids: list[int]   # IDs written to deduplicated_articles table

    # Node 5: novelty_node output
    novelty_map: dict[int, str]     # {dedup_article_id: "new"|"developing"|"continuing"|"resolved"}
    new_article_ids: list[int]      # dedup IDs to analyze (new + developing only)
    skipped_continuing_count: int   # articles filtered as unchanged

    # Node 6: analyze_node output
    analyzed_article_ids: list[int]  # IDs written to article_analyses table

    # Node 7: synthesize_node output
    synthesis_id: int | None        # ID written to daily_synthesis table

    # Node 8: report_node output
    report_paths: dict[str, str]    # {"html": "/path/...", "pdf": "/path/..."}
    emails_sent: list[str]          # recipient addresses confirmed sent

    # Observability
    errors: Annotated[list[str], operator.add]  # accumulated error messages
    stage: str                      # current stage name
    _dry_run: bool                  # skip email delivery when True
