from enum import Enum


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class TopicCategory(str, Enum):
    MATCH_RESULT = "match_result"
    TRANSFER = "transfer"
    COACHING_STAFF = "coaching_staff"
    GOVERNANCE = "governance"
    YOUTH_FOOTBALL = "youth_football"
    NATIONAL_TEAM = "national_team"
    SPONSORSHIP = "sponsorship"
    CONTROVERSY = "controversy"
    INFRASTRUCTURE = "infrastructure"
    INTERNATIONAL = "international"
    PLAYER_SPOTLIGHT = "player_spotlight"
    TOURNAMENT_NEWS = "tournament_news"
    TRANSFER_WINDOW = "transfer_window"
    OTHER = "other"


class RiskLevel(str, Enum):
    CRISIS = "crisis"
    CONCERN = "concern"
    NEUTRAL = "neutral"
    OPPORTUNITY = "opportunity"


class NoveltyStatus(str, Enum):
    NEW = "new"
    DEVELOPING = "developing"
    CONTINUING = "continuing"
    RESOLVED = "resolved"


class FetchStatus(str, Enum):
    PENDING = "pending"
    FETCHED = "fetched"
    FETCH_FAILED = "fetch_failed"
    SKIPPED = "skipped"


class PipelineStatus(str, Enum):
    STARTED = "started"
    KEYWORDS = "keywords"
    COLLECTING = "collecting"
    DEDUPLICATING = "deduplicating"
    FILTERING_NOVELTY = "filtering_novelty"
    ANALYZING = "analyzing"
    SYNTHESIZING = "synthesizing"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
