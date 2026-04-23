from pydantic import BaseModel, Field
from datetime import datetime
from models.enums import Sentiment, TopicCategory, RiskLevel, NoveltyStatus


class RawArticle(BaseModel):
    id: int | None = None
    run_uuid: str
    source_id: str
    source_language: str   # "ko" | "en"
    url: str
    url_hash: str          # SHA256 of normalized URL
    title: str
    body_text: str | None = None
    summary_from_source: str | None = None
    published_at: datetime | None = None
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    fetch_status: str = "pending"


class DeduplicatedArticle(BaseModel):
    id: int | None = None
    run_uuid: str
    canonical_article_id: int
    dedup_cluster_id: str       # UUID grouping duplicates
    dedup_method: str           # "url_exact" | "title_fingerprint" | "llm_semantic"
    confidence: float = 1.0
    duplicate_count: int = 1
    duplicate_ids: list[int] = Field(default_factory=list)
    novelty_status: NoveltyStatus = NoveltyStatus.NEW
    story_cluster_id: str | None = None  # cross-day continuity cluster


class ArticleAnalysis(BaseModel):
    id: int | None = None
    run_uuid: str
    deduplicated_article_id: int
    raw_article_id: int

    sentiment: Sentiment
    sentiment_score: float          # -1.0 to +1.0
    sentiment_rationale: str | None = None

    primary_topic: TopicCategory
    secondary_topics: list[str] = Field(default_factory=list)

    players_mentioned: list[dict] = Field(default_factory=list)
    clubs_mentioned: list[dict] = Field(default_factory=list)
    officials_mentioned: list[dict] = Field(default_factory=list)
    venues_mentioned: list[str] = Field(default_factory=list)

    relevance_score: int             # 0-10
    risk_flag: RiskLevel
    risk_rationale: str | None = None

    summary_primary: str
    summary_secondary: str
    key_quote: str | None = None

    model_used: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)


class StoryContinuity(BaseModel):
    id: int | None = None
    story_cluster_id: str
    first_seen_date: str        # "YYYY-MM-DD"
    last_seen_date: str
    canonical_title: str
    canonical_title_alt: str | None = None
    days_active: int = 1
    status: NoveltyStatus = NoveltyStatus.NEW
    resolution_date: str | None = None
    representative_article_ids: list[int] = Field(default_factory=list)
    latest_run_uuid: str
