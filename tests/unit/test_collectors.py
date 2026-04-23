"""Unit tests for RSS collectors."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from collectors.base import BaseCollector, CollectedArticle
from collectors.rss_collector import RSSCollector
from collectors.yonhap import YonhapCollector


def _make_sample_rss() -> bytes:
    """Build RSS fixture with pubDates 1–2 hours ago so they always pass the age filter."""
    now = datetime.now(timezone.utc)
    d1 = (now - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    d2 = (now - timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Football News</title>
    <item>
      <title>한국 축구 국가대표 평가전 승리</title>
      <link>https://example.com/article1</link>
      <description>한국이 평가전에서 2-0으로 승리했다.</description>
      <pubDate>{d1}</pubDate>
    </item>
    <item>
      <title>KFA 신임 감독 선임 발표</title>
      <link>https://example.com/article2</link>
      <description>대한축구협회가 새로운 국가대표팀 감독을 선임했다.</description>
      <pubDate>{d2}</pubDate>
    </item>
  </channel>
</rss>""".encode("utf-8")


SAMPLE_RSS = _make_sample_rss()


@pytest.mark.asyncio
async def test_rss_collector_parses_articles():
    collector = RSSCollector(
        source_id="test_source",
        source_language="ko",
        url="https://example.com/rss",
    )
    with patch.object(collector, "fetch_url", new=AsyncMock(return_value=SAMPLE_RSS)):
        articles = await collector.collect()
    assert len(articles) == 2
    assert articles[0].title == "한국 축구 국가대표 평가전 승리"
    assert articles[0].source_id == "test_source"
    assert articles[0].source_language == "ko"
    assert "example.com/article1" in articles[0].url


@pytest.mark.asyncio
async def test_rss_collector_handles_fetch_failure():
    collector = RSSCollector(
        source_id="failing_source",
        source_language="ko",
        url="https://example.com/rss",
    )
    with patch.object(collector, "fetch_url", new=AsyncMock(return_value=None)):
        articles = await collector.collect()
    assert articles == []


@pytest.mark.asyncio
async def test_yonhap_filters_football_content():
    collector = YonhapCollector()
    with patch.object(collector, "fetch_url", new=AsyncMock(return_value=SAMPLE_RSS)):
        articles = await collector.collect()
    # Both articles contain 축구/KFA keywords
    assert len(articles) == 2


def test_parse_feed_extracts_correct_fields():
    collector = RSSCollector("test", "ko", "http://x.com")
    articles = collector.parse_feed(SAMPLE_RSS)
    assert len(articles) == 2
    assert articles[0].url == "https://example.com/article1"
    assert articles[0].published_at is not None
