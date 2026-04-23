from collectors.base import BaseCollector, CollectedArticle
import structlog

logger = structlog.get_logger()

YONHAP_SPORTS_RSS = "https://www.yna.co.kr/rss/sports.xml"


class YonhapCollector(BaseCollector):
    source_id = "yonhap_sports"
    source_language = "ko"

    def __init__(self, url: str = YONHAP_SPORTS_RSS):
        self.url = url

    async def collect(self) -> list[CollectedArticle]:
        content = await self.fetch_url(self.url)
        if not content:
            logger.error("yonhap_fetch_failed")
            return []
        articles = self.parse_feed(content)
        # Filter to football-relevant entries
        football_keywords = ["축구", "football", "soccer", "KFA", "대한축구협회", "국가대표", "여자 축구"]
        filtered = [
            a for a in articles
            if any(kw in (a.title + (a.summary or "")) for kw in football_keywords)
        ]
        logger.info("yonhap_collected", raw=len(articles), filtered=len(filtered))
        return filtered
