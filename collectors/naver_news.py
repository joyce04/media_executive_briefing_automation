"""Naver News collector using the Naver Search API.

Collects from two sections only:
  - kfootball (국내축구): Korean domestic football, KFA, K-League, national team
  - wfootball (해외축구): World football with focus on Korean players abroad

Requires NAVER_CLIENT_ID and NAVER_CLIENT_SECRET from https://developers.naver.com.
The "검색 (Search)" API product must be enabled for the application.

API reference: https://developers.naver.com/docs/serviceapi/search/news/news.md
"""
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx
import structlog

from collectors.base import BaseCollector, CollectedArticle
from config.settings import settings

logger = structlog.get_logger()

NAVER_NEWS_API = "https://openapi.naver.com/v1/search/news.json"

# Queries are grouped by section.  Each query is issued to the Naver Search API
# and results are tagged with the corresponding section source_id.
# Dynamic keyword_node queries are handled separately by DynamicSearchCollector.
SECTION_QUERIES: dict[str, list[str]] = {
    "kfootball": [
        "K리그",
        "대한축구협회",
        "한국 축구 국가대표",
        "한국 여자 축구 국가대표",
    ],
    "wfootball": [
        "손흥민 이강인 김민재",
        "해외 축구 한국 선수",
        "한국 선수 유럽 축구",
    ],
}


class NaverNewsCollector(BaseCollector):
    """Collects Korean football news from the kfootball and wfootball sections
    via the Naver Search API."""

    source_id = "naver_news"   # overridden per-article to naver_kfootball / naver_wfootball
    source_language = "ko"

    def __init__(self, display: int = 50):
        """
        Args:
            display: Number of results per query (1–100, default 50).
        """
        self.display = min(display, 100)

    async def collect(self) -> list[CollectedArticle]:
        if not settings.naver_client_id or not settings.naver_client_secret:
            logger.warning(
                "naver_credentials_missing",
                msg="Set NAVER_CLIENT_ID and NAVER_CLIENT_SECRET to enable Naver collection",
            )
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.collection_max_age_hours)
        headers = {
            "X-Naver-Client-Id": settings.naver_client_id,
            "X-Naver-Client-Secret": settings.naver_client_secret,
        }

        articles: list[CollectedArticle] = []
        seen_urls: set[str] = set()
        stale_count = 0

        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            for section, queries in SECTION_QUERIES.items():
                source_id = f"naver_{section}"
                for query in queries:
                    items = await self._fetch_query(client, headers, query)
                    for item in items:
                        url = (item.get("originallink") or item.get("link", "")).strip()
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)

                        title = re.sub(r"<[^>]+>", "", item.get("title", "")).strip()
                        if not title:
                            continue

                        summary = re.sub(r"<[^>]+>", "", item.get("description", "")).strip()[:2000] or None

                        published_at: datetime | None = None
                        pub_date_str = item.get("pubDate", "")
                        if pub_date_str:
                            try:
                                dt_aware = parsedate_to_datetime(pub_date_str)
                                if dt_aware < cutoff:
                                    stale_count += 1
                                    continue
                                published_at = dt_aware.astimezone(timezone.utc).replace(tzinfo=None)
                            except Exception:
                                pass  # Unparseable date: keep the article

                        articles.append(CollectedArticle(
                            source_id=source_id,
                            source_language="ko",
                            url=url,
                            title=title,
                            summary=summary,
                            published_at=published_at,
                        ))

        if stale_count:
            logger.debug("naver_stale_dropped", stale_count=stale_count,
                         cutoff_hours=settings.collection_max_age_hours)
        kfootball_count = sum(1 for a in articles if a.source_id == "naver_kfootball")
        wfootball_count = sum(1 for a in articles if a.source_id == "naver_wfootball")
        logger.info("naver_collected", total=len(articles),
                    kfootball=kfootball_count, wfootball=wfootball_count)
        return articles

    async def _fetch_query(
        self, client: httpx.AsyncClient, headers: dict, query: str
    ) -> list[dict]:
        """Fetch one search query from the Naver News API. Returns items or [] on error."""
        logger.debug("naver_query", query=query)
        try:
            resp = await client.get(
                NAVER_NEWS_API,
                params={"query": query, "display": self.display, "sort": "date"},
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json().get("items", [])
        except Exception as exc:
            logger.warning("naver_api_error", query=query[:50], error=str(exc))
            return []
