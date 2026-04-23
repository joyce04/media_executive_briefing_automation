from collectors.base import BaseCollector, CollectedArticle
import structlog

logger = structlog.get_logger()


class RSSCollector(BaseCollector):
    """Generic feedparser-based RSS collector."""

    def __init__(self, source_id: str, source_language: str, url: str,
                 after_date: str | None = None):
        self.source_id = source_id
        self.source_language = source_language
        self.url = url
        # Optional YYYY-MM-DD lower bound — overrides collection_max_age_hours in parse_feed.
        self.after_date = after_date

    async def collect(self) -> list[CollectedArticle]:
        from datetime import datetime, timezone
        content = await self.fetch_url(self.url)
        if not content:
            logger.error("rss_fetch_failed", source_id=self.source_id, url=self.url)
            return []
        cutoff = None
        if self.after_date:
            cutoff = datetime.strptime(self.after_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        articles = self.parse_feed(content, cutoff=cutoff)
        logger.info("rss_collected", source_id=self.source_id, count=len(articles))
        return articles
