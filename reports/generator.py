"""Assembles Jinja2 template context from DB state for report rendering."""
import re
import structlog
from database.repositories.report_repo import get_synthesis_for_date
from database.repositories.analysis_repo import get_analyses_for_run
from database.repositories.article_repo import get_deduplicated_articles_for_run
from database.repositories.org_repo import get_org_by_id
from config.settings import settings

logger = structlog.get_logger()


def _normalize_bullets(value) -> list[str]:
    """Return a clean list of bullet strings regardless of LLM output shape."""
    if not value:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = [str(i) for i in value]
    else:
        return []

    result = []
    for item in items:
        parts = re.split(r'\n\s*•\s*|(?<!\A)•\s*', item)
        for part in parts:
            clean = part.strip().lstrip('•').strip()
            if clean:
                result.append(clean)
    return result


def build_report_context(run_uuid: str, run_date: str, org_id: int, state: dict) -> dict:
    """Build the full context dict for Jinja2 template rendering."""
    org = get_org_by_id(org_id) or {}
    synthesis = get_synthesis_for_date(org_id, run_date)
    analyses = get_analyses_for_run(run_uuid, org_id)
    dedup_articles = get_deduplicated_articles_for_run(run_uuid, org_id)
    novelty_map = state.get("novelty_map", {})

    analysis_by_dedup_id = {a["deduplicated_article_id"]: a for a in analyses}
    dedup_by_id = {a["id"]: a for a in dedup_articles}

    new_articles = []
    developing_articles = []
    continuing_articles = []
    resolved_articles = []

    for dedup_id, novelty_status in novelty_map.items():
        dedup = dedup_by_id.get(dedup_id)
        if not dedup:
            continue
        analysis = analysis_by_dedup_id.get(dedup_id)

        article_data = {
            "title": dedup.get("title", ""),
            "url": dedup.get("url", ""),
            "source_language": dedup.get("source_language", "en"),
            "published_at": dedup.get("published_at"),
            "novelty_status": novelty_status,
            "days_active": dedup.get("days_active", 1),
        }
        if analysis:
            article_data.update({
                "sentiment": analysis.get("sentiment", "neutral"),
                "sentiment_score": analysis.get("sentiment_score", 0.0),
                "primary_topic": analysis.get("primary_topic", "other"),
                "relevance_score": analysis.get("relevance_score", 5),
                "risk_flag": analysis.get("risk_flag", "neutral"),
                "summary_primary": analysis.get("summary_primary", ""),
                "summary_secondary": analysis.get("summary_secondary", ""),
                "players_mentioned": analysis.get("players_mentioned", []),
                "clubs_mentioned": analysis.get("clubs_mentioned", []),
            })

        if novelty_status == "new":
            new_articles.append(article_data)
        elif novelty_status == "developing":
            developing_articles.append(article_data)
        elif novelty_status == "continuing":
            continuing_articles.append(article_data)
        elif novelty_status == "resolved":
            resolved_articles.append(article_data)

    _RISK_WEIGHT = {"crisis": 3, "concern": 2, "opportunity": 1, "neutral": 0}

    def _article_priority(a: dict) -> tuple:
        relevance = a.get("relevance_score", 0)
        risk = _RISK_WEIGHT.get(a.get("risk_flag", "neutral"), 0)
        return (relevance + risk, relevance)

    developing_articles.sort(key=_article_priority, reverse=True)
    developing_articles = [a for a in developing_articles if a.get("relevance_score", 0) > 5]

    new_articles.sort(key=_article_priority, reverse=True)
    new_articles = [a for a in new_articles if a.get("relevance_score", 0) > 5]
    new_articles = new_articles[:30]

    analysis_by_id = {a["id"]: a for a in analyses}
    dedup_url_by_dedup_id = {a["id"]: {"title": a.get("title", ""), "url": a.get("url", "")}
                             for a in dedup_articles}

    def _resolve_supporting_articles(article_ids: list) -> list[dict]:
        out = []
        for aid in (article_ids or []):
            analysis = analysis_by_id.get(aid)
            if not analysis:
                continue
            dedup_info = dedup_url_by_dedup_id.get(analysis.get("deduplicated_article_id"))
            if dedup_info and dedup_info.get("url"):
                out.append({"title": dedup_info["title"], "url": dedup_info["url"]})
        return out

    raw_narratives = (synthesis or {}).get("trending_narratives", [])[:5]
    for narrative in raw_narratives:
        narrative["supporting_articles"] = _resolve_supporting_articles(
            narrative.get("supporting_article_ids", [])
        )

    narrative_urls: set[str] = {
        art["url"]
        for n in raw_narratives
        for art in n.get("supporting_articles", [])
        if art.get("url")
    }
    new_articles_remainder = [a for a in new_articles if a.get("url") not in narrative_urls]

    return {
        "org": org,
        "run_date": run_date,
        "from_email": settings.smtp_user,
        "synthesis": synthesis or {},
        "new_articles": new_articles_remainder,
        "developing_articles": developing_articles,
        "continuing_articles": continuing_articles,
        "resolved_articles": resolved_articles,
        "new_count": len(new_articles_remainder),
        "developing_count": len(developing_articles),
        "continuing_count": len(continuing_articles),
        "resolved_count": len(resolved_articles),
        "total_analyzed": len(analyses),
        "skipped_continuing_count": state.get("skipped_continuing_count", 0),
        "trending_narratives": raw_narratives,
        "recommended_actions": (synthesis or {}).get("recommended_actions", [])[:5],
        "sentiment_today": (synthesis or {}).get("sentiment_today", 0.0),
        "sentiment_trend": (synthesis or {}).get("sentiment_trend"),
        "executive_summary": _normalize_bullets((synthesis or {}).get("executive_summary", [])),
        "executive_summary_en": _normalize_bullets((synthesis or {}).get("executive_summary_en", [])),
    }
