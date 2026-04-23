from datetime import datetime, timedelta, timezone
from collectors.base import BaseCollector, CollectedArticle
import structlog
import urllib.parse

logger = structlog.get_logger()

GOOGLE_NEWS_BASE = "https://news.google.com/rss/search?q={query}&hl={hl}&gl={gl}&ceid={ceid}"


class GoogleNewsRSSCollector(BaseCollector):

    def __init__(self, source_id: str, query: str, language: str = "ko",
                 gl: str = "KR", ceid: str = "KR:ko",
                 after_date: str | None = None, before_date: str | None = None):
        self.source_id = source_id
        self.source_language = language
        self.query = query
        self.hl = language
        self.gl = gl
        self.ceid = ceid
        # Explicit date range (YYYY-MM-DD). When set, overrides collection_max_age_hours.
        self.after_date = after_date
        self.before_date = before_date

    def _build_url(self, query: str) -> str:
        if self.after_date:
            after_date = self.after_date
        else:
            from config.settings import settings
            cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.collection_max_age_hours)
            after_date = cutoff.strftime("%Y-%m-%d")
        dated_query = f"{query} after:{after_date}"
        if self.before_date:
            dated_query = f"{dated_query} before:{self.before_date}"
        return GOOGLE_NEWS_BASE.format(
            query=urllib.parse.quote(dated_query),
            hl=self.hl,
            gl=self.gl,
            ceid=self.ceid,
        )

    def _parse_cutoff(self) -> datetime | None:
        """Return a tz-aware UTC cutoff from after_date, or None to use the default."""
        if self.after_date:
            return datetime.strptime(self.after_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return None

    async def collect(self, extra_queries: list[str] | None = None) -> list[CollectedArticle]:
        articles: list[CollectedArticle] = []
        cutoff = self._parse_cutoff()

        content = await self.fetch_url(self._build_url(self.query))
        if content:
            articles.extend(self.parse_feed(content, cutoff=cutoff))

        for query in (extra_queries or []):
            content = await self.fetch_url(self._build_url(query))
            if content:
                entries = self.parse_feed(content, cutoff=cutoff)
                for e in entries:
                    e.source_id = f"{self.source_id}_dynamic"
                articles.extend(entries)

        logger.info("google_news_collected", source_id=self.source_id, total=len(articles))
        return articles
