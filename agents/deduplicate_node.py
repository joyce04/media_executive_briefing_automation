"""Node 3: 3-pass same-day deduplication (URL hash → title fingerprint → LLM semantic)."""
import json
import uuid
import re
import structlog
from collections import defaultdict
from langchain_core.messages import SystemMessage, HumanMessage
from agents.llm_client import get_org_llm
from database.repositories.article_repo import (
    get_raw_articles_for_run, insert_deduplicated_article
)
from database.repositories.pipeline_repo import update_run_status
from models.state import PipelineState

logger = structlog.get_logger()


def normalize_title(title: str) -> set[str]:
    """Normalize title to a set of meaningful tokens for fingerprinting."""
    title = title.lower()
    title = re.sub(r"[^\w\s가-힣]", " ", title)
    tokens = set(t for t in title.split() if len(t) > 1)
    return tokens


def title_overlap_ratio(tokens_a: set[str], tokens_b: set[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


async def llm_are_same_story(org: dict, title_a: str, snippet_a: str,
                              title_b: str, snippet_b: str) -> tuple[bool, float]:
    """Ask the org's fast LLM if two articles are about the same event."""
    llm = get_org_llm(org, mode="fast")
    prompt = f"""Are these two news articles about the same event?
A: {title_a[:200]} — {(snippet_a or '')[:200]}
B: {title_b[:200]} — {(snippet_b or '')[:200]}

Return JSON only: {{"same_story": true/false, "confidence": 0.0-1.0, "reason": "brief reason"}}"""
    try:
        resp = await llm.ainvoke([
            SystemMessage(content="You are a news deduplication expert. Return JSON only."),
            HumanMessage(content=prompt),
        ])
        text = resp.content.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            data = json.loads(text[start:end]) if start >= 0 else {}
        return data.get("same_story", False), float(data.get("confidence", 0.5))
    except Exception as e:
        logger.error("llm_dedup_error", error=str(e), exc_info=True)
    return False, 0.0


async def run(state: PipelineState) -> dict:
    run_uuid = state["run_uuid"]
    org_id = state["org_id"]
    org = state["org_config"]["org"]
    logger.info("dedup_node_start", run_uuid=run_uuid)
    update_run_status(run_uuid, "deduplicating")

    all_raw = get_raw_articles_for_run(run_uuid, org_id)
    filtered_ids_state = state.get("filtered_article_ids")
    if filtered_ids_state is not None:
        filtered_ids = set(filtered_ids_state)
        raw_articles = [a for a in all_raw if a["id"] in filtered_ids]
    else:
        raw_articles = all_raw

    if not raw_articles:
        logger.warning("dedup_no_articles")
        return {"deduplicated_article_ids": [], "stage": "deduplicate"}

    # Pass 2: Title fingerprint dedup
    clusters: list[list[dict]] = []
    assigned: set[int] = set()

    for i, article_a in enumerate(raw_articles):
        if article_a["id"] in assigned:
            continue
        cluster = [article_a]
        tokens_a = normalize_title(article_a["title"])
        for j, article_b in enumerate(raw_articles):
            if i == j or article_b["id"] in assigned:
                continue
            tokens_b = normalize_title(article_b["title"])
            if title_overlap_ratio(tokens_a, tokens_b) >= 0.80:
                cluster.append(article_b)
                assigned.add(article_b["id"])
        assigned.add(article_a["id"])
        clusters.append(cluster)

    # Pass 3: LLM semantic dedup for near-duplicate solos
    solo_articles = [c[0] for c in clusters if len(c) == 1]
    merged_ids: dict[int, int] = {}

    if len(solo_articles) > 1:
        token_index: dict[str, list[int]] = defaultdict(list)
        for art in solo_articles:
            for tok in normalize_title(art["title"]):
                token_index[tok].append(art["id"])

        pair_scores: dict[tuple[int, int], int] = defaultdict(int)
        for token, ids in token_index.items():
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    key = (min(ids[i], ids[j]), max(ids[i], ids[j]))
                    pair_scores[key] += 1

        candidate_pairs = [(a, b) for (a, b), score in pair_scores.items() if 2 <= score < 5]
        art_by_id = {a["id"]: a for a in solo_articles}

        for (id_a, id_b) in candidate_pairs[:50]:
            if id_a in merged_ids or id_b in merged_ids:
                continue
            art_a = art_by_id.get(id_a)
            art_b = art_by_id.get(id_b)
            if not art_a or not art_b:
                continue
            same, confidence = await llm_are_same_story(
                org,
                art_a["title"], art_a.get("summary_from_source", ""),
                art_b["title"], art_b.get("summary_from_source", ""),
            )
            if same and confidence > 0.7:
                merged_ids[id_b] = id_a
                logger.debug("llm_dedup_merged", a=id_a, b=id_b, confidence=confidence)

    # Rebuild clusters with LLM merges
    art_by_id_all = {a["id"]: a for a in raw_articles}
    dedup_ids = []

    for cluster in clusters:
        if len(cluster) == 1 and cluster[0]["id"] in merged_ids:
            continue
        canonical = cluster[0]
        extras = [
            art_by_id_all[bid]
            for bid, cid in merged_ids.items()
            if cid == canonical["id"] and bid in art_by_id_all
        ]
        full_cluster = cluster + extras
        all_ids = [a["id"] for a in full_cluster]
        method = "title_fingerprint" if len(full_cluster) > 1 else "url_exact"
        dedup_id = insert_deduplicated_article(
            org_id=org_id,
            run_uuid=run_uuid,
            canonical_article_id=canonical["id"],
            dedup_cluster_id=str(uuid.uuid4()),
            dedup_method=method,
            confidence=1.0,
            duplicate_ids=all_ids,
        )
        dedup_ids.append(dedup_id)

    update_run_status(run_uuid, "deduplicating", articles_deduplicated=len(dedup_ids))
    logger.info("dedup_node_done", clusters=len(dedup_ids), raw=len(raw_articles))
    return {"deduplicated_article_ids": dedup_ids, "stage": "deduplicate"}
