"""Unit tests for analyze_node."""
import json
import pytest
from langchain_core.messages import AIMessage
from database.repositories.article_repo import compute_url_hash, insert_raw_articles_batch, insert_deduplicated_article
import uuid


SAMPLE_ANALYSIS_RESPONSE = {
    "sentiment": "positive",
    "sentiment_score": 0.65,
    "primary_topic": "national_team",
    "secondary_topics": ["match_result"],
    "players_mentioned": [{"name_ko": "손흥민", "name_en": "Son Heung-min", "club": "Tottenham"}],
    "clubs_mentioned": [],
    "officials_mentioned": [],
    "venues_mentioned": ["서울월드컵경기장"],
    "kfa_relevance_score": 8,
    "risk_flag": "opportunity",
    "risk_rationale_ko": "긍정적인 국가대표팀 성과",
    "summary_ko": "한국 국가대표팀이 평가전에서 2-0으로 승리했습니다.",
    "summary_en": "South Korea national team won 2-0 in a friendly match.",
    "key_quote": None,
}


@pytest.mark.asyncio
async def test_analyze_node_processes_new_articles(base_state, mock_haiku, mock_sonnet):
    """analyze_node should analyze articles in new_article_ids."""
    from database.repositories.pipeline_repo import create_run
    create_run(base_state["run_date"], base_state["run_uuid"])

    _url = "https://example.com/article-analyze"
    ids = insert_raw_articles_batch([(
        base_state["run_uuid"], "naver", "ko", _url, compute_url_hash(_url),
        "한국 국가대표 평가전 2-0 승리", "", "한국이 승리했다.", None,
    )])
    art_id = ids[0]
    dedup_id = insert_deduplicated_article(
        run_uuid=base_state["run_uuid"],
        canonical_article_id=art_id,
        dedup_cluster_id=str(uuid.uuid4()),
        dedup_method="url_exact",
        confidence=1.0,
        duplicate_ids=[art_id],
    )

    # Short article → uses haiku
    mock_haiku.ainvoke.return_value = AIMessage(content=json.dumps(SAMPLE_ANALYSIS_RESPONSE))

    state = {**base_state, "new_article_ids": [dedup_id], "novelty_map": {dedup_id: "new"}}
    from agents.analyze_node import run
    result = await run(state)

    assert len(result["analyzed_article_ids"]) == 1
    assert result["stage"] == "analyze"


@pytest.mark.asyncio
async def test_analyze_node_skips_continuing_articles(base_state, mock_haiku, mock_sonnet):
    """analyze_node should not process articles NOT in new_article_ids."""
    from database.repositories.pipeline_repo import create_run
    create_run(base_state["run_date"], base_state["run_uuid"])

    # No new article IDs
    state = {**base_state, "new_article_ids": [], "novelty_map": {99: "continuing"}}
    from agents.analyze_node import run
    result = await run(state)

    assert result["analyzed_article_ids"] == []
    mock_haiku.ainvoke.assert_not_called()
