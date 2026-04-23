from collectors.base import BaseCollector, CollectedArticle
import structlog

logger = structlog.get_logger()

FIFA_NEWS_RSS = "https://www.fifa.com/en/news/feed.rss"


class FIFANewsCollector(BaseCollector):
    source_id = "fifa_news"
    source_language = "en"

    def __init__(self, url: str = FIFA_NEWS_RSS):
        self.url = url

    async def collect(self) -> list[CollectedArticle]:
        content = await self.fetch_url(self.url)
        if not content:
            logger.error("fifa_fetch_failed")
            return []
        articles = self.parse_feed(content)
        logger.info("fifa_collected", count=len(articles))
        return articles
