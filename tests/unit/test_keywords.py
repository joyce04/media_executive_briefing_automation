"""Unit tests for keyword_node."""
import json
import pytest
from langchain_core.messages import AIMessage
from agents import keyword_node


@pytest.mark.asyncio
async def test_keyword_node_returns_defaults_on_no_context(base_state, mock_haiku):
    """When no prior synthesis exists, should return defaults without LLM call."""
    result = await keyword_node.run(base_state)
    assert "generated_keywords" in result
    assert len(result["generated_keywords"]) > 0
    assert result["stage"] == "keywords"
    # With no prior context, defaults are returned without LLM call
    keywords = result["generated_keywords"]
    assert all("query" in kw for kw in keywords)
    assert all("language" in kw for kw in keywords)


@pytest.mark.asyncio
async def test_keyword_node_parses_llm_response(base_state, mock_haiku, monkeypatch):
    """Test that valid LLM JSON response is parsed correctly."""
    keywords_json = json.dumps([
        {"query": "손흥민 국가대표", "language": "ko", "source": "google_news", "rationale": "Active player"},
        {"query": "KFA coach selection", "language": "en", "source": "google_news", "rationale": "International news"},
    ])
    mock_haiku.ainvoke.return_value = AIMessage(content=keywords_json)

    # Simulate having prior context by patching repo functions
    monkeypatch.setattr("agents.keyword_node.get_yesterday_synthesis", lambda d: {"trending_narratives": [{"title_ko": "손흥민 복귀"}]})
    monkeypatch.setattr("agents.keyword_node.get_active_stories", lambda lookback_days=7: [])

    result = await keyword_node.run(base_state)
    assert len(result["generated_keywords"]) == 2
    assert result["generated_keywords"][0]["query"] == "손흥민 국가대표"


@pytest.mark.asyncio
async def test_keyword_node_falls_back_on_llm_error(base_state, mock_haiku, monkeypatch):
    """On LLM error, should fall back to defaults."""
    mock_haiku.ainvoke.side_effect = Exception("LLM timeout")
    monkeypatch.setattr("agents.keyword_node.get_yesterday_synthesis", lambda d: {"trending_narratives": []})
    monkeypatch.setattr("agents.keyword_node.get_active_stories", lambda lookback_days=7: [])

    result = await keyword_node.run(base_state)
    assert "generated_keywords" in result
    assert len(result["generated_keywords"]) > 0
    assert any("errors" in result and len(result.get("errors", [])) > 0 for _ in [1])
