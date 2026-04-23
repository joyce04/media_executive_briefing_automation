"""Node 2: Collects articles from static RSS feeds + dynamic search queries."""
import asyncio
import structlog
from collectors.base import CollectedArticle
from collectors.registry import build_registry
from collectors.dynamic_search import DynamicSearchCollector
from database.repositories.article_repo import insert_raw_articles_batch, compute_url_hash
from database.repositories.pipeline_repo import update_run_status
from models.state import PipelineState

logger = structlog.get_logger()


def _is_relevant(article: CollectedArticle, relevance_terms: list[str]) -> bool:
    """Drop articles with no org-relevance signal.

    If the org has no relevance_terms configured, all articles pass through
    and the filter_node LLM scoring handles quality control downstream.
    """
    if not relevance_terms:
        return True
    text = (article.title + " " + (article.summary or "")).lower()
    return any(term in text for term in relevance_terms)


async def run(state: PipelineState) -> dict:
    run_uuid = state["run_uuid"]
    run_date = state["run_date"]
    org_id = state["org_id"]
    org_config = state["org_config"]
    generated_keywords = state.get("generated_keywords", [])

    sources = org_config.get("sources", [])
    relevance_terms = org_config.get("org", {}).get("relevance_terms", [])

    print("\n=== Search queries for", run_date, "===")
    for kw in generated_keywords:
        print(f"  [{kw.get('language','?')}] {kw.get('query','')}  ({kw.get('rationale','')})")
    print(f"  Total: {len(generated_keywords)} queries\n")

    logger.info("collect_node_start", run_uuid=run_uuid, keywords=len(generated_keywords),
                sources=len(sources))
    update_run_status(run_uuid, "collecting")

    # 1. Run all static collectors in parallel
    static_collectors = build_registry(sources)
    tasks = [c.collect() for c in static_collectors]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_articles: list[CollectedArticle] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("collector_error", collector=static_collectors[i].source_id, error=str(result))
        else:
            all_articles.extend(result)

    # 2. Run dynamic search queries
    if generated_keywords:
        dynamic = DynamicSearchCollector(
            run_uuid=run_uuid,
            run_date=run_date,
            keywords=generated_keywords,
        )
        dynamic_articles = await dynamic.collect_all()
        all_articles.extend(dynamic_articles)

    # 3. Org relevance pre-filter — only applied when org has configured terms
    before = len(all_articles)
    all_articles = [a for a in all_articles if _is_relevant(a, relevance_terms)]
    dropped = before - len(all_articles)
    if dropped:
        logger.info("relevance_prefilter", dropped=dropped, kept=len(all_articles))

    # 4. Insert into DB (URL-hash dedup is per-org via UNIQUE(org_id, url_hash))
    batch_data = [
        (
            article.source_id,
            article.source_language,
            article.url,
            compute_url_hash(article.url),
            article.title,
            None,  # body_text placeholder
            article.summary,
            article.published_at.isoformat() if article.published_at else None,
        )
        for article in all_articles
    ]

    raw_ids = insert_raw_articles_batch(org_id, batch_data) if batch_data else []

    logger.info("collect_node_done", total_fetched=before, after_relevance=len(all_articles),
                unique_inserted=len(raw_ids))
    update_run_status(run_uuid, "collecting", articles_collected=len(raw_ids))

    return {
        "raw_article_ids": raw_ids,
        "stage": "collect",
    }
