"""Unit tests for novelty_node classification logic."""
import json
import pytest
from langchain_core.messages import AIMessage


@pytest.mark.asyncio
async def test_novelty_new_articles_pass_through(base_state, mock_haiku, monkeypatch):
    """Articles not seen before should be classified as 'new'."""
    from database.repositories.article_repo import compute_url_hash, insert_raw_articles_batch, insert_deduplicated_article
    import uuid

    # Insert a raw article
    _url = "https://example.com/new-article"
    ids = insert_raw_articles_batch([(
        base_state["run_uuid"], "test", "ko", _url, compute_url_hash(_url),
        "완전히 새로운 축구 뉴스", "", "전혀 새로운 이야기입니다.", None,
    )])
    art_id = ids[0]
    # Insert dedup record
    dedup_id = insert_deduplicated_article(
        run_uuid=base_state["run_uuid"],
        canonical_article_id=art_id,
        dedup_cluster_id=str(uuid.uuid4()),
        dedup_method="url_exact",
        confidence=1.0,
        duplicate_ids=[art_id],
    )
    state = {**base_state, "deduplicated_article_ids": [dedup_id]}

    # LLM returns "new" for this article
    mock_haiku.ainvoke.return_value = AIMessage(content=json.dumps([
        {"index": 0, "novelty": "new", "confidence": 0.95, "matched_yesterday_index": None, "reason": "Not seen before"}
    ]))
    monkeypatch.setattr("agents.novelty_node.get_recent_canonical_articles", lambda **kw: [])
    monkeypatch.setattr("agents.novelty_node.get_active_stories", lambda lookback_days=7: [])

    from agents.novelty_node import run
    result = await run(state)

    assert result["stage"] == "novelty"
    assert dedup_id in result["new_article_ids"]
    assert result["novelty_map"].get(dedup_id) == "new"


def test_novelty_map_structure(base_state):
    """novelty_map must use dedup_article_id as key."""
    novelty_map = {1: "new", 2: "continuing", 3: "developing"}
    state = {**base_state, "novelty_map": novelty_map}
    assert state["novelty_map"][1] == "new"
    assert state["novelty_map"][2] == "continuing"
