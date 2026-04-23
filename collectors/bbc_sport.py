from collectors.base import BaseCollector, CollectedArticle
import structlog

logger = structlog.get_logger()

BBC_SPORT_FOOTBALL_RSS = "https://feeds.bbci.co.uk/sport/football/rss.xml"


class BBCSportCollector(BaseCollector):
    source_id = "bbc_sport_football"
    source_language = "en"

    def __init__(self, url: str = BBC_SPORT_FOOTBALL_RSS):
        self.url = url

    async def collect(self) -> list[CollectedArticle]:
        content = await self.fetch_url(self.url)
        if not content:
            logger.error("bbc_fetch_failed")
            return []
        articles = self.parse_feed(content)
        # Filter for Korea/Asian football relevance
        korea_keywords = ["Korea", "KFA", "Asian", "AFC", "Son", "hwang", "national team",
                          "World Cup", "Olympics", "women's", "Ji So-yun"]
        filtered = [
            a for a in articles
            if any(kw.lower() in (a.title + (a.summary or "")).lower() for kw in korea_keywords)
        ]
        result = filtered if filtered else articles[:20]
        logger.info("bbc_collected", raw=len(articles), filtered=len(result))
        return result
