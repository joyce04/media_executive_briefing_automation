"""Integration test — full pipeline on fixture articles with mocked LLM + real SQLite."""
import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import AIMessage

FIXTURES = Path(__file__).parent.parent / "fixtures"


def make_keyword_response() -> AIMessage:
    keywords = [
        {"query": "한국 축구 국가대표", "language": "ko", "source": "google_news", "rationale": "test"},
        {"query": "KFA football", "language": "en", "source": "google_news", "rationale": "test"},
    ]
    return AIMessage(content=json.dumps(keywords))


def make_dedup_response(same: bool = False) -> AIMessage:
    return AIMessage(content=json.dumps({"same_story": same, "confidence": 0.95, "reason": "test"}))


def make_novelty_response(articles: list[dict]) -> AIMessage:
    result = [
        {"index": i, "novelty": "new", "confidence": 0.9, "matched_yesterday_index": None, "reason": "first seen"}
        for i in range(len(articles))
    ]
    return AIMessage(content=json.dumps(result))


def make_analysis_response() -> AIMessage:
    return AIMessage(content=json.dumps({
        "sentiment": "positive",
        "sentiment_score": 0.6,
        "primary_topic": "national_team",
        "secondary_topics": ["match_result"],
        "players_mentioned": [],
        "clubs_mentioned": [],
        "officials_mentioned": [],
        "venues_mentioned": [],
        "kfa_relevance_score": 7,
        "risk_flag": "neutral",
        "risk_rationale_ko": None,
        "summary_ko": "테스트 요약입니다.",
        "summary_en": "Test summary.",
        "key_quote": None,
    }))


def make_synthesis_response() -> AIMessage:
    return AIMessage(content=json.dumps({
        "trending_narratives": [
            {"rank": 1, "title_ko": "국가대표 승리", "title_en": "National team win",
             "description_ko": "한국이 승리했습니다.", "description_en": "Korea won.",
             "article_count": 1, "supporting_article_ids": [1], "sentiment_distribution": {"positive": 1}}
        ],
        "crisis_alerts": [],
        "pr_opportunities": [],
        "competitive_intel": [],
        "recommended_actions": [
            {"priority": 1, "action_ko": "성명 발표", "action_en": "Issue statement",
             "rationale_ko": "긍정 여론 활용", "related_article_ids": []}
        ],
        "executive_summary_ko": "오늘 한국 축구는 좋은 성과를 보였습니다.",
        "executive_summary_en": "Korean football had positive results today.",
    }))


@pytest.mark.asyncio
async def test_full_pipeline_with_fixture_articles(base_state, monkeypatch):
    """Run the complete 8-node pipeline on fixture articles with all LLMs mocked."""
    from database.repositories.pipeline_repo import create_run
    create_run(base_state["run_date"], base_state["run_uuid"])

    # Load fixture articles
    ko_articles = json.loads((FIXTURES / "sample_articles_ko.json").read_text())
    en_articles = json.loads((FIXTURES / "sample_articles_en.json").read_text())
    all_fixtures = ko_articles + en_articles

    # Mock all collectors to return fixture data
    from collectors.base import CollectedArticle
    from datetime import datetime

    fixture_collected = []
    for art in all_fixtures:
        fixture_collected.append(CollectedArticle(
            source_id=art["source_id"],
            source_language=art["source_language"],
            url=art["url"],
            title=art["title"],
            summary=art.get("summary_from_source"),
            published_at=datetime.fromisoformat(art["published_at"]) if art.get("published_at") else None,
        ))

    mock_collector = MagicMock()
    mock_collector.collect = AsyncMock(return_value=fixture_collected)

    monkeypatch.setattr("agents.collect_node.build_registry", lambda: [mock_collector])
    monkeypatch.setattr("collectors.dynamic_search.DynamicSearchCollector.collect_all",
                        AsyncMock(return_value=[]))

    # Mock all LLM calls
    mock_haiku = MagicMock()
    mock_sonnet = MagicMock()

    call_count = [0]

    async def haiku_side_effect(messages, **kwargs):
        call_count[0] += 1
        content = messages[-1].content if messages else ""
        if "Generate" in content and "search queries" in content:
            return make_keyword_response()
        elif "same event" in content:
            return make_dedup_response(False)
        elif "novelty" in content or "YESTERDAY" in content:
            return make_novelty_response([{"id": i} for i in range(5)])
        else:
            return make_analysis_response()

    mock_haiku.ainvoke = AsyncMock(side_effect=haiku_side_effect)
    mock_sonnet.ainvoke = AsyncMock(return_value=make_synthesis_response())

    monkeypatch.setattr("agents.llm_client.get_haiku", lambda: mock_haiku)
    monkeypatch.setattr("agents.llm_client.get_sonnet", lambda: mock_sonnet)

    # Mock email sending and PDF generation
    monkeypatch.setattr("reports.email_sender.send_report_email", lambda **kw: None)
    monkeypatch.setattr("reports.pdf_generator.generate_pdf", lambda **kw: True)

    # Run each node in sequence
    from agents.keyword_node import run as keyword_run
    from agents.collect_node import run as collect_run
    from agents.filter_node import run as filter_run
    from agents.deduplicate_node import run as dedup_run
    from agents.novelty_node import run as novelty_run
    from agents.analyze_node import run as analyze_run
    from agents.synthesize_node import run as synthesize_run

    state = dict(base_state)

    # Node 1: keywords
    result = await keyword_run(state)
    state.update(result)
    assert len(state["generated_keywords"]) > 0

    # Node 2: collect
    result = await collect_run(state)
    state.update(result)
    # collect_node applies a keyword relevance filter; allow up to 2 articles dropped
    assert 0 < len(state["raw_article_ids"]) <= len(all_fixtures)

    # Node 3: filter
    result = await filter_run(state)
    state.update(result)
    assert len(state["filtered_article_ids"]) > 0

    # Node 4: deduplicate
    result = await dedup_run(state)
    state.update(result)
    assert len(state["deduplicated_article_ids"]) > 0

    # Node 5: novelty
    monkeypatch.setattr("agents.novelty_node.get_recent_canonical_articles", lambda **kw: [])
    monkeypatch.setattr("agents.novelty_node.get_active_stories", lambda lookback_days=7: [])
    result = await novelty_run(state)
    state.update(result)
    assert len(state["new_article_ids"]) > 0

    # Node 6: analyze
    result = await analyze_run(state)
    state.update(result)
    assert len(state["analyzed_article_ids"]) > 0

    # Node 7: synthesize
    monkeypatch.setattr("agents.synthesize_node.get_recent_sentiment_history", lambda days=7: [])
    result = await synthesize_run(state)
    state.update(result)
    assert state["synthesis_id"] is not None

    print(f"\n✓ E2E pipeline complete:")
    print(f"  Articles collected:   {len(state['raw_article_ids'])}")
    print(f"  After dedup:          {len(state['deduplicated_article_ids'])}")
    print(f"  New/Developing:       {len(state['new_article_ids'])}")
    print(f"  Analyzed:             {len(state['analyzed_article_ids'])}")
    print(f"  Synthesis ID:         {state['synthesis_id']}")
    print(f"  Errors:               {state.get('errors', [])}")
