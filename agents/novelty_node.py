"""Node 4: Cross-day novelty classification — prevents re-reporting unchanged stories."""
import json
import structlog
from langchain_core.messages import SystemMessage, HumanMessage
from agents.llm_client import get_org_llm
from database.repositories.article_repo import (
    get_deduplicated_articles_for_run, update_dedup_novelty, get_recent_canonical_articles
)
from database.repositories.continuity_repo import get_active_stories, upsert_story_cluster, create_new_cluster_id
from database.repositories.pipeline_repo import update_run_status
from models.state import PipelineState

logger = structlog.get_logger()

NOVELTY_BATCH_SIZE = 10


async def classify_novelty_llm(
    org: dict,
    today_articles: list[dict],
    yesterday_articles: list[dict],
) -> dict[int, tuple[str, float, str | None]]:
    """
    For each today article, compare against yesterday's articles in batches.
    Returns {today_article_id: (novelty_status, confidence, matched_story_cluster_id)}
    """
    if not yesterday_articles:
        return {a["id"]: ("new", 1.0, None) for a in today_articles}

    llm = get_org_llm(org, mode="fast")
    results: dict[int, tuple[str, float, str | None]] = {}

    yesterday_context = [
        {
            "title": a["title"],
            "snippet": (a.get("summary_from_source") or "")[:200],
            "story_cluster_id": a.get("story_cluster_id"),
        }
        for a in yesterday_articles[:30]
    ]

    for i in range(0, len(today_articles), NOVELTY_BATCH_SIZE):
        batch = today_articles[i: i + NOVELTY_BATCH_SIZE]

        prompt = f"""Compare each TODAY article against all YESTERDAY articles.
For each TODAY article, classify its novelty:
- "new": no similar story yesterday
- "developing": same ongoing story but with significant new information
- "continuing": same story, no meaningful new information added
- "resolved": story that appears to have concluded

YESTERDAY articles:
{json.dumps(yesterday_context, ensure_ascii=False, indent=2)}

TODAY articles (classify each by its index):
{json.dumps([{"index": j, "title": a["title"], "snippet": (a.get("summary_from_source") or "")[:200]} for j, a in enumerate(batch)], ensure_ascii=False, indent=2)}

Return JSON array only:
[{{"index": 0, "novelty": "new|developing|continuing|resolved", "confidence": 0.9, "matched_yesterday_index": null_or_int, "reason": "brief"}}]"""

        try:
            resp = await llm.ainvoke([
                SystemMessage(content="You classify news novelty. Return JSON only."),
                HumanMessage(content=prompt),
            ])
            text = resp.content.strip()
            try:
                classifications = json.loads(text)
            except json.JSONDecodeError:
                start = text.find("[")
                end = text.rfind("]") + 1
                classifications = json.loads(text[start:end]) if start >= 0 and end > start else []
            for cls in classifications:
                idx = cls.get("index", 0)
                if 0 <= idx < len(batch):
                    art = batch[idx]
                    novelty = cls.get("novelty", "new")
                    confidence = float(cls.get("confidence", 0.8))
                    matched_idx = cls.get("matched_yesterday_index")
                    cluster_id = None
                    if matched_idx is not None and 0 <= matched_idx < len(yesterday_context):
                        cluster_id = yesterday_context[matched_idx].get("story_cluster_id")
                    results[art["id"]] = (novelty, confidence, cluster_id)
        except Exception as e:
            logger.error("novelty_llm_error", error=str(e), exc_info=True)
            for art in batch:
                results[art["id"]] = ("new", 0.5, None)

    return results


async def run(state: PipelineState) -> dict:
    run_uuid = state["run_uuid"]
    run_date = state["run_date"]
    org_id = state["org_id"]
    org = state["org_config"]["org"]
    dedup_ids = state.get("deduplicated_article_ids", [])
    logger.info("novelty_node_start", run_uuid=run_uuid, dedup_count=len(dedup_ids))

    update_run_status(run_uuid, "filtering_novelty")

    today_articles = get_deduplicated_articles_for_run(run_uuid, org_id)
    yesterday_articles = get_recent_canonical_articles(org_id, days=7, exclude_run_uuid=run_uuid)
    active_stories = {s["story_cluster_id"]: s for s in get_active_stories(org_id, lookback_days=7)}

    novelty_map: dict[int, str] = {}
    new_article_ids: list[int] = []
    skipped_count = 0

    # Pass 1: Heuristic — same URL seen recently = continuing without change
    recent_hashes = {a["url_hash"] for a in yesterday_articles}
    heuristic_classified: set[int] = set()

    for art in today_articles:
        dedup_id = art["id"]
        if art.get("url_hash") in recent_hashes:
            novelty_map[dedup_id] = "continuing"
            update_dedup_novelty(dedup_id, "continuing", art.get("story_cluster_id"))
            skipped_count += 1
            heuristic_classified.add(dedup_id)

    # Pass 2: LLM classification for remaining articles
    unclassified = [a for a in today_articles if a["id"] not in heuristic_classified]

    if unclassified:
        llm_results = await classify_novelty_llm(org, unclassified, yesterday_articles)
        for art in unclassified:
            dedup_id = art["id"]
            novelty, confidence, matched_cluster_id = llm_results.get(dedup_id, ("new", 0.6, None))
            novelty_map[dedup_id] = novelty

            story_cluster_id = matched_cluster_id
            if novelty == "new" or not story_cluster_id:
                story_cluster_id = create_new_cluster_id()

            update_dedup_novelty(dedup_id, novelty, story_cluster_id)
            upsert_story_cluster(
                org_id=org_id,
                story_cluster_id=story_cluster_id,
                run_date=run_date,
                canonical_title=art["title"],
                novelty_status=novelty,
                article_id=art["canonical_article_id"],
                run_uuid=run_uuid,
            )

            if novelty in ("new", "developing"):
                new_article_ids.append(dedup_id)
            else:
                skipped_count += 1

    logger.info(
        "novelty_node_done",
        new=len([v for v in novelty_map.values() if v == "new"]),
        developing=len([v for v in novelty_map.values() if v == "developing"]),
        continuing=len([v for v in novelty_map.values() if v == "continuing"]),
        skipped=skipped_count,
    )

    return {
        "novelty_map": novelty_map,
        "new_article_ids": new_article_ids,
        "skipped_continuing_count": skipped_count,
        "errors": [],
        "stage": "novelty",
    }
