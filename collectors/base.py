from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import httpx
import feedparser
import structlog

logger = structlog.get_logger()

HEADERS = {
    "User-Agent": "MediaIntel/1.0 feedparser/6.0",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


@dataclass
class CollectedArticle:
    source_id: str
    source_language: str
    url: str
    title: str
    summary: str | None
    published_at: datetime | None


class BaseCollector(ABC):
    source_id: str
    source_language: str
    max_retries: int = 3
    timeout_seconds: int = 10

    async def fetch_url(self, url: str) -> bytes | None:
        """Fetch a URL with retry logic."""
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(headers=HEADERS, timeout=self.timeout_seconds,
                                             follow_redirects=True) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return resp.content
            except httpx.HTTPError as e:
                logger.warning("fetch_failed", url=url, attempt=attempt + 1, error=str(e))
                if attempt == self.max_retries - 1:
                    return None
        return None

    def parse_feed(self, content: bytes,
                   cutoff: datetime | None = None) -> list[CollectedArticle]:
        """Parse RSS/Atom content and return CollectedArticle list.

        Articles whose ``published_at`` is older than the cutoff are silently
        dropped to prevent re-ingesting stale content.  Entries with no
        publication date are always kept — the age cannot be determined.

        Args:
            content: Raw RSS/Atom bytes.
            cutoff: Earliest allowed published_at (UTC, tz-aware). Defaults to
                    ``now - collection_max_age_hours`` from settings.
        """
        from config.settings import settings
        import re

        if cutoff is None:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.collection_max_age_hours)

        feed = feedparser.parse(content)
        articles = []
        stale_count = 0
        for entry in feed.entries:
            url = entry.get("link", "").strip()
            title = entry.get("title", "").strip()
            if not url or not title:
                continue
            summary = entry.get("summary") or entry.get("description") or None
            if summary:
                summary = re.sub(r"<[^>]+>", "", summary).strip()[:2000]

            published_at: datetime | None = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                # feedparser always returns UTC tuples; build a timezone-aware datetime
                published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

            # Drop stale articles — skip only when we have a confirmed date that is too old
            if published_at is not None and published_at < cutoff:
                stale_count += 1
                continue

            # Store as naive UTC (strip tzinfo) to match existing DB convention
            published_at_naive = published_at.replace(tzinfo=None) if published_at else None

            articles.append(CollectedArticle(
                source_id=self.source_id,
                source_language=self.source_language,
                url=url,
                title=title,
                summary=summary,
                published_at=published_at_naive,
            ))

        if stale_count:
            logger.debug(
                "parse_feed_stale_dropped",
                source_id=self.source_id,
                stale_count=stale_count,
                cutoff_hours=settings.collection_max_age_hours,
            )
        return articles

    @abstractmethod
    async def collect(self) -> list[CollectedArticle]:
        """Fetch and return articles from this source."""
        ...
