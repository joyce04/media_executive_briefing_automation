from pydantic import BaseModel, Field
from datetime import datetime


class TrendingNarrative(BaseModel):
    rank: int
    title: str
    description: str
    article_count: int
    supporting_article_ids: list[int]
    sentiment_distribution: dict[str, int]  # {"positive": 2, "neutral": 3, "negative": 1}


class CrisisAlert(BaseModel):
    severity: str   # "critical" | "high" | "medium"
    title: str
    description: str
    article_ids: list[int]
    recommended_action: str


class RecommendedAction(BaseModel):
    priority: int   # 1 = highest
    action: str
    rationale: str
    related_article_ids: list[int] = Field(default_factory=list)


class DailySynthesis(BaseModel):
    id: int | None = None
    run_uuid: str
    run_date: str   # "YYYY-MM-DD"

    trending_narratives: list[TrendingNarrative]
    crisis_alerts: list[CrisisAlert]
    pr_opportunities: list[dict]
    competitive_intel: list[dict]

    sentiment_today: float
    sentiment_7day_avg: float | None = None
    sentiment_trend: str | None = None     # "improving" | "stable" | "declining"

    recommended_actions: list[RecommendedAction]
    executive_summary: list[str]
    executive_summary_en: list[str]

    articles_synthesized: int
    model_used: str
    synthesized_at: datetime = Field(default_factory=datetime.utcnow)


class DailyReport(BaseModel):
    run_date: str
    run_uuid: str
    synthesis: DailySynthesis

    # Article counts by novelty status
    new_count: int = 0
    developing_count: int = 0
    continuing_count: int = 0
    resolved_count: int = 0

    # Articles grouped by novelty for template rendering
    new_articles: list[dict] = Field(default_factory=list)
    developing_articles: list[dict] = Field(default_factory=list)
    continuing_articles: list[dict] = Field(default_factory=list)
    resolved_articles: list[dict] = Field(default_factory=list)

    generated_at: datetime = Field(default_factory=datetime.utcnow)
