"""Node 5: Per-article analysis — only NEW and DEVELOPING articles."""
import json
import structlog
from langchain_core.messages import SystemMessage, HumanMessage
from agents.llm_client import get_org_llm, get_org_model_name
from database.repositories.article_repo import get_deduplicated_articles_for_run
from database.repositories.analysis_repo import insert_analysis, upsert_sentiment_history
from database.repositories.pipeline_repo import update_run_status
from config.settings import settings
from models.state import PipelineState

logger = structlog.get_logger()

ANALYSIS_SCHEMA = """{
  "sentiment": "positive|neutral|negative",
  "sentiment_score": -1.0 to 1.0,
  "sentiment_rationale": "brief reason",
  "primary_topic": "match_result|transfer|coaching_staff|governance|youth|national_team|sponsorship|controversy|infrastructure|international|player_spotlight|tournament_news|other",
  "secondary_topics": ["topic1"],
  "players_mentioned": [{"name": "Player Name", "role": "brief context"}],
  "tracked_players_mentioned": [{"name": "Player Name", "context": "brief update"}],
  "clubs_mentioned": ["Club Name"],
  "officials_mentioned": [{"name": "Name", "role": "Title"}],
  "venues_mentioned": ["Venue Name"],
  "relevance_score": 0-10,
  "risk_flag": "crisis|concern|neutral|opportunity",
  "risk_rationale": "brief reason for flag",
  "summary_primary": "1-2 sentence summary in org's primary language",
  "summary_secondary": "1-2 sentence summary in English",
  "key_quote": "most significant direct quote if present, else null"
}"""


def _build_watchlist_context(entities: list[dict]) -> str:
    players = [e for e in entities if e.get("entity_type") in ("player", "person")
               and e.get("priority", 99) <= 2]
    if not players:
        return "(no tracked entities configured)"
    parts = []
    for p in players:
        name_alt = p.get("name_alt", "")
        alt_str = f" ({name_alt})" if name_alt else ""
        parts.append(f"{p['name_primary']}{alt_str}")
    return ", ".join(parts)


async def analyze_article(article: dict, org: dict, watchlist_ctx: str,
                           prompts: dict) -> dict | None:
    """Analyze a single article. Returns analysis dict or None on failure."""
    title = article.get("title", "")
    body = article.get("body_text") or article.get("summary_from_source") or ""
    language = article.get("source_language", "en")

    if not title:
        return None

    text_input = f"Title: {title}\n\n{body[:3000]}"
    is_short = len(text_input) < settings.short_article_char_threshold
    mode = "fast" if is_short else "smart"
    llm = get_org_llm(org, mode=mode)
    model_name = get_org_model_name(org, mode=mode)

    org_name = org.get("name", "the organization")
    lang_primary = org.get("language_primary", "en")
    lang_instruction = (
        f"Write summary_primary in {lang_primary} and summary_secondary in English."
        if lang_primary != "en"
        else "Write both summary_primary and summary_secondary in English."
    )

    # Korean-specific tone guidance for orgs using Korean as primary language
    lang_tone = ""
    if lang_primary == "ko":
        lang_tone = "\nFor Korean text: use polite, advisory tone (고려해 볼 수 있다, 검토해 볼 수 있다 style endings)."

    prompt = f"""Analyze this {language.upper()} article for {org_name}'s media intelligence.

{text_input}

Tracked entities to watch for: {watchlist_ctx}
For tracked_players_mentioned: only include entities from the watchlist above who actually appear in the article.
{lang_instruction}{lang_tone}

Return JSON exactly matching this schema:
{ANALYSIS_SCHEMA}"""

    system_msg = prompts.get(
        "analysis",
        f"You are an intelligence analyst for {org_name}. Return JSON only.",
    )

    try:
        resp = await llm.ainvoke([
            SystemMessage(content=system_msg),
            HumanMessage(content=prompt),
        ])
        text = resp.content.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0:
            data = json.loads(text[start:end])
            data["_model_used"] = model_name
            usage = getattr(resp, "usage_metadata", None) or {}
            data["_prompt_tokens"] = usage.get("input_tokens")
            data["_completion_tokens"] = usage.get("output_tokens")
            return data
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("analyze_article_parse_error", title=title[:50], error=str(e), exc_info=True)
    except Exception as e:
        logger.error("analyze_article_error", title=title[:50], error=str(e), exc_info=True)
    return None


async def run(state: PipelineState) -> dict:
    run_uuid = state["run_uuid"]
    run_date = state["run_date"]
    org_id = state["org_id"]
    org_config = state["org_config"]
    org = org_config["org"]
    entities = org_config.get("entities", [])
    prompts = org_config.get("prompts", {})
    new_article_ids = state.get("new_article_ids", [])
    novelty_map = state.get("novelty_map", {})

    logger.info("analyze_node_start", run_uuid=run_uuid, to_analyze=len(new_article_ids))
    update_run_status(run_uuid, "analyzing")

    watchlist_ctx = _build_watchlist_context(entities)

    all_dedup = get_deduplicated_articles_for_run(run_uuid, org_id)
    to_analyze = [a for a in all_dedup if a["id"] in new_article_ids]

    analyzed_ids = []
    sentiment_scores = []
    risk_counts: dict[str, int] = {"crisis": 0, "concern": 0, "neutral": 0, "opportunity": 0}
    topic_counts: dict[str, int] = {}

    for article in to_analyze:
        analysis = await analyze_article(article, org, watchlist_ctx, prompts)
        if not analysis:
            continue

        analysis_id = insert_analysis(
            org_id=org_id,
            run_uuid=run_uuid,
            deduplicated_article_id=article["id"],
            raw_article_id=article["canonical_article_id"],
            analysis=analysis,
            model_used=analysis.get("_model_used", ""),
            prompt_tokens=analysis.get("_prompt_tokens"),
            completion_tokens=analysis.get("_completion_tokens"),
        )
        analyzed_ids.append(analysis_id)
        sentiment_scores.append(float(analysis.get("sentiment_score", 0.0)))
        risk = analysis.get("risk_flag", "neutral")
        risk_counts[risk] = risk_counts.get(risk, 0) + 1
        topic = analysis.get("primary_topic", "other")
        topic_counts[topic] = topic_counts.get(topic, 0) + 1

    if sentiment_scores:
        avg_sentiment = sum(sentiment_scores) / len(sentiment_scores)
        top_topics = sorted(topic_counts.items(), key=lambda x: -x[1])[:5]
        upsert_sentiment_history(org_id, run_date, {
            "total_articles": len(to_analyze),
            "positive_count": sum(1 for s in sentiment_scores if s > 0.2),
            "neutral_count": sum(1 for s in sentiment_scores if -0.2 <= s <= 0.2),
            "negative_count": sum(1 for s in sentiment_scores if s < -0.2),
            "crisis_count": risk_counts.get("crisis", 0),
            "avg_sentiment_score": avg_sentiment,
            "top_topics": [{"topic": t, "count": c} for t, c in top_topics],
        })

    update_run_status(run_uuid, "analyzing", articles_analyzed=len(analyzed_ids))
    logger.info("analyze_node_done", analyzed=len(analyzed_ids))
    return {"analyzed_article_ids": analyzed_ids, "stage": "analyze"}
