from typing import TypedDict, Annotated
import operator


class TacticsPipelineState(TypedDict):
    # Run identification
    week_start: str                              # "YYYY-MM-DD" — Tuesday 7 days prior (KST)
    week_end: str                                # "YYYY-MM-DD" — Monday before the run (KST)
    run_uuid: str                                # UUID4 for this execution

    # Node 1: collect_node output
    raw_article_ids: list[int]                   # IDs written to tactics_raw_articles

    # Node 2: filter_node output
    filtered_article_ids: list[int] | None       # None = filter hasn't run; [] = all dropped

    # Node 3: deduplicate_node output
    deduplicated_article_ids: list[int]          # IDs written to tactics_deduplicated_articles

    # Node 4: analyze_node output
    analyzed_article_ids: list[int]              # IDs written to tactics_article_analyses

    # Node 5: synthesize_node output
    synthesis_id: int | None                     # ID written to tactics_weekly_synthesis

    # Node 6: report_node output
    report_paths: dict[str, str]                 # {"html": "/path/...", "pdf": "/path/..."}
    emails_sent: list[str]                       # recipient addresses confirmed sent

    # Observability
    errors: Annotated[list[str], operator.add]   # accumulated error messages
    stage: str                                   # current stage name
    _dry_run: bool                               # skip email delivery when True
