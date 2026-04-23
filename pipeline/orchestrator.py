"""Pipeline orchestrator — compiles and invokes the LangGraph pipeline."""
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import structlog
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from database.connection import init_db, get_checkpoints_path
from database.repositories.org_repo import get_org_config
from database.repositories.pipeline_repo import create_run, update_run_status
from pipeline.graph import build_graph

logger = structlog.get_logger()


def get_org_date(org_config: dict) -> str:
    """Return today's date in the org's configured timezone as YYYY-MM-DD."""
    tz = ZoneInfo(org_config["org"].get("timezone", "UTC"))
    return datetime.now(tz).strftime("%Y-%m-%d")


async def run_pipeline_for_org(
    org_id: int,
    run_date: str | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Execute the media intelligence pipeline for a specific organization.

    Args:
        org_id: Organization ID from the organizations table
        run_date: Date string YYYY-MM-DD (defaults to today in org's timezone)
        dry_run: If True, skip email delivery

    Returns:
        Final pipeline state dict
    """
    init_db()

    org_cfg = get_org_config(org_id)
    org = org_cfg["org"]

    if run_date is None:
        run_date = get_org_date(org_cfg)

    run_uuid = str(uuid.uuid4())
    logger.info("pipeline_start", org=org["slug"], run_date=run_date,
                run_uuid=run_uuid, dry_run=dry_run)

    create_run(org_id=org_id, run_date=run_date, run_uuid=run_uuid)

    # Per-org checkpoint file prevents cross-org checkpoint interference
    checkpoint_path = str(get_checkpoints_path(org["slug"]))

    initial_state: dict = {
        "org_id": org_id,
        "org_config": org_cfg,
        "run_date": run_date,
        "run_uuid": run_uuid,
        "generated_keywords": [],
        "raw_article_ids": [],
        "filtered_article_ids": None,
        "deduplicated_article_ids": [],
        "novelty_map": {},
        "new_article_ids": [],
        "skipped_continuing_count": 0,
        "analyzed_article_ids": [],
        "synthesis_id": None,
        "report_paths": {},
        "emails_sent": [],
        "errors": [],
        "stage": "init",
        "_dry_run": dry_run,
    }

    # thread_id scoped to org + date so re-runs are idempotent per org per day
    config = {"configurable": {"thread_id": f"{org_id}_{run_date}"}}

    try:
        async with AsyncSqliteSaver.from_conn_string(checkpoint_path) as checkpointer:
            graph = build_graph(checkpointer=checkpointer)
            final_state = await graph.ainvoke(initial_state, config=config)
        update_run_status(run_uuid, "completed")
        logger.info(
            "pipeline_complete",
            org=org["slug"],
            run_date=run_date,
            articles_collected=len(final_state.get("raw_article_ids", [])),
            articles_analyzed=len(final_state.get("analyzed_article_ids", [])),
            emails_sent=final_state.get("emails_sent", []),
            errors=final_state.get("errors", []),
        )
        return final_state
    except Exception as e:
        logger.error("pipeline_failed", org=org["slug"], run_date=run_date, error=str(e))
        update_run_status(run_uuid, "failed", error_message=str(e))
        raise


async def run_pipeline(run_date: str | None = None, dry_run: bool = False) -> dict:
    """Backward-compatible shim — runs the pipeline for org_id=1 (the original KFA org)."""
    return await run_pipeline_for_org(org_id=1, run_date=run_date, dry_run=dry_run)
