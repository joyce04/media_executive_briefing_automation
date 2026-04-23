"""Node 3: LLM-based relevance and significance filter.

Runs between collect_node and deduplicate_node. Uses the org's fast LLM to
batch-score every raw article on two dimensions:

  relevance    (0–10)  Is this relevant to the organization's domain?
  significance (0–10)  How newsworthy is this?

Articles scoring below MIN_RELEVANCE or MIN_SIGNIFICANCE are dropped before
deduplication, reducing noise across all downstream nodes. On any LLM failure
the batch is kept in full (fail-open).
"""
import json
import structlog
from langchain_core.messages import SystemMessage, HumanMessage
from agents.llm_client import get_org_llm
from database.repositories.article_repo import get_raw_articles_for_run
from database.repositories.pipeline_repo import update_run_status
from models.state import PipelineState

logger = structlog.get_logger()

BATCH_SIZE = 15
MIN_RELEVANCE = 5
MIN_SIGNIFICANCE = 4


async def run(state: PipelineState) -> dict:
    run_uuid = state["run_uuid"]
    org_id = state["org_id"]
    org_config = state["org_config"]
    org = org_config["org"]
    logger.info("filter_node_start", run_uuid=run_uuid, raw=len(state.get("raw_article_ids", [])))
    update_run_status(run_uuid, "filtering")

    articles = get_raw_articles_for_run(run_uuid, org_id)
    if not articles:
        return {"filtered_article_ids": [], "stage": "filter"}

    llm = get_org_llm(org, mode="fast")
    org_name = org.get("name", "the organization")
    kept_ids: list[int] = []
    dropped_count = 0

    for i in range(0, len(articles), BATCH_SIZE):
        batch = articles[i : i + BATCH_SIZE]
        batch_items = [
            {
                "id": a["id"],
                "title": a["title"],
                "snippet": (a.get("summary_from_source") or "")[:300],
                "language": a.get("source_language", "en"),
            }
            for a in batch
        ]

        prompt = f"""You are a content filter for {org_name}'s media intelligence system.

Score each article on:
- relevance (0-10): relevance to {org_name}'s domain and interests. Score 0 for articles with no connection.
- significance (0-10): newsworthiness — 10=major breaking news, 5=routine coverage, 1=trivial/promotional/purely historical.

Articles:
{json.dumps(batch_items, ensure_ascii=False, indent=2)}

Return a JSON array only, one object per article, no other text:
[{{"id": <int>, "relevance": <0-10>, "significance": <0-10>, "reason": "<brief>"}}]"""

        try:
            resp = await llm.ainvoke([
                SystemMessage(content=f"You are a strict content filter for {org_name}. Return JSON array only."),
                HumanMessage(content=prompt),
            ])
            text = resp.content.strip()
            try:
                scores = json.loads(text)
            except json.JSONDecodeError:
                start = text.find("[")
                end = text.rfind("]") + 1
                scores = json.loads(text[start:end]) if start >= 0 and end > start else []
            id_to_score = {s["id"]: s for s in scores if "id" in s}
        except Exception as exc:
            logger.error("filter_node_llm_error", batch_start=i, error=str(exc), exc_info=True)
            kept_ids.extend(a["id"] for a in batch)  # fail open
            logger.warning("filter_node_fail_open", batch_start=i, kept_unscored=len(batch))
            continue

        for article in batch:
            aid = article["id"]
            score = id_to_score.get(aid)
            if score is None:
                kept_ids.append(aid)  # not scored → keep (fail open)
                continue
            relevance = int(score.get("relevance", 0))
            significance = int(score.get("significance", 0))
            if relevance >= MIN_RELEVANCE and significance >= MIN_SIGNIFICANCE:
                kept_ids.append(aid)
            else:
                dropped_count += 1
                logger.debug(
                    "filter_dropped",
                    article_id=aid,
                    title=article["title"][:80],
                    relevance=relevance,
                    significance=significance,
                    reason=score.get("reason", ""),
                )

    logger.info(
        "filter_node_done",
        raw=len(articles),
        kept=len(kept_ids),
        dropped=dropped_count,
    )
    return {"filtered_article_ids": kept_ids, "stage": "filter"}
