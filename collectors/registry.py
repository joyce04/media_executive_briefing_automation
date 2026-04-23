from collectors.rss_collector import RSSCollector
from collectors.naver_news import NaverNewsCollector
from collectors.yonhap import YonhapCollector
from collectors.google_news_rss import GoogleNewsRSSCollector
from collectors.bbc_sport import BBCSportCollector
from collectors.fifa_news import FIFANewsCollector
from collectors.base import BaseCollector


def build_registry(sources: list[dict]) -> list[BaseCollector]:
    """Build the list of static collectors from an org's source config."""
    collectors: list[BaseCollector] = []
    for source in sources:
        sid = source["source_id"]
        lang = source.get("language", "en")
        url = source.get("url", "")

        if sid == "naver_news_football":
            collectors.append(NaverNewsCollector())
        elif sid == "yonhap_sports":
            collectors.append(YonhapCollector(url=url))
        elif sid.startswith("google_news") and lang == "ko":
            query = source.get("query", "")
            collectors.append(GoogleNewsRSSCollector(
                source_id=sid, query=query, language="ko",
                gl="KR", ceid="KR:ko",
            ))
        elif sid.startswith("google_news") and lang == "en":
            query = source.get("query", "")
            collectors.append(GoogleNewsRSSCollector(
                source_id=sid, query=query, language="en",
                gl="US", ceid="US:en",
            ))
        elif sid == "bbc_sport_football":
            collectors.append(BBCSportCollector(url=url))
        elif sid == "fifa_news":
            collectors.append(FIFANewsCollector(url=url))
        else:
            collectors.append(RSSCollector(source_id=sid, source_language=lang, url=url))

    return collectors
