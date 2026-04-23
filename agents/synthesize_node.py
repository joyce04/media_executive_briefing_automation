"""Node 6: Cross-article synthesis — produces executive briefing content."""
import json
import structlog
from langchain_core.messages import SystemMessage, HumanMessage
from agents.llm_client import get_org_llm, get_org_model_name
from database.repositories.analysis_repo import get_analyses_for_run, get_recent_sentiment_history
from database.repositories.report_repo import insert_synthesis
from database.repositories.pipeline_repo import update_run_status
from models.state import PipelineState

logger = structlog.get_logger()


def compute_sentiment_trend(today_avg: float, history: list[dict]) -> tuple[float | None, str | None]:
    if len(history) < 3:
        return None, None
    avg_7d = sum(h["avg_sentiment_score"] for h in history) / len(history)
    if today_avg > avg_7d + 0.1:
        trend = "improving"
    elif today_avg < avg_7d - 0.1:
        trend = "declining"
    else:
        trend = "stable"
    return avg_7d, trend


SYNTHESIS_SCHEMA = """{
  "trending_narratives": [
    {"rank": 1, "title": "...", "description": "...",
     "article_count": 3, "supporting_article_ids": [1,2,3],
     "sentiment_distribution": {"positive":1,"neutral":1,"negative":1}}
  ],
  "crisis_alerts": [
    {"severity": "high", "title": "...", "description": "...",
     "article_ids": [4,5], "recommended_action": "..."}
  ],
  "pr_opportunities": [
    {"title": "...", "description": "...", "article_ids": [6]}
  ],
  "competitive_intel": [
    {"entity": "Competitor name", "development": "...", "implication": "..."}
  ],
  "recommended_actions": [
    {"priority": 1, "action": "...", "rationale": "...", "related_article_ids": [7]}
  ],
  "executive_summary": ["• First key point", "• Second key point"],
  "executive_summary_en": ["• First key point in English", "• Second key point in English"]
}"""


def _build_entity_context(entities: list[dict]) -> tuple[str, str]:
    """Return (tracked_entities_ctx, events_ctx) strings for the synthesis prompt."""
    from datetime import date, datetime
    today = date.today()

    player_lines = []
    event_lines = []

    for e in entities:
        etype = e.get("entity_type", "")
        attrs = e.get("attributes", {})
        name_alt = e.get("name_alt", "")
        alt_str = f" ({name_alt})" if name_alt else ""

        if etype in ("player", "person") and e.get("priority", 99) <= 2:
            watch_reason = attrs.get("watch_reason", "")
            player_lines.append(f"- {e['name_primary']}{alt_str}: {watch_reason}")

        elif etype == "tournament":
            try:
                end = datetime.strptime(attrs.get("end_date", ""), "%Y-%m-%d").date()
                if end < today:
                    continue
                start = datetime.strptime(attrs.get("start_date", ""), "%Y-%m-%d").date()
                days = (start - today).days
                label = f"starts in {days}d" if days >= 0 else "ongoing"
                event_lines.append(f"- {e['name_primary']}{alt_str}, {label}")
            except Exception:
                event_lines.append(f"- {e['name_primary']}{alt_str}")

    entities_ctx = "\n".join(player_lines) if player_lines else "(none configured)"
    events_ctx = "\n".join(event_lines) if event_lines else "(none)"
    return entities_ctx, events_ctx


async def run(state: PipelineState) -> dict:
    run_uuid = state["run_uuid"]
    run_date = state["run_date"]
    org_id = state["org_id"]
    org_config = state["org_config"]
    org = org_config["org"]
    entities = org_config.get("entities", [])
    prompts = org_config.get("prompts", {})
    novelty_map = state.get("novelty_map", {})

    logger.info("synthesize_node_start", run_uuid=run_uuid, org=org["slug"])
    update_run_status(run_uuid, "synthesizing")

    analyses = get_analyses_for_run(run_uuid, org_id)
    if not analyses:
        logger.warning("synthesize_no_analyses")
        return {"synthesis_id": None, "stage": "synthesize",
                "errors": ["No analyses available for synthesis"]}

    history = get_recent_sentiment_history(org_id, days=7)
    today_scores = [a["sentiment_score"] for a in analyses]
    today_avg = sum(today_scores) / len(today_scores) if today_scores else 0.0
    avg_7d, trend = compute_sentiment_trend(today_avg, history)

    entity_ctx, events_ctx = _build_entity_context(entities)

    analysis_context = []
    for a in analyses[:60]:
        analysis_context.append({
            "id": a["id"],
            "title": a.get("title", ""),
            "sentiment": a.get("sentiment"),
            "sentiment_score": a.get("sentiment_score"),
            "primary_topic": a.get("primary_topic"),
            "relevance_score": a.get("relevance_score"),
            "risk_flag": a.get("risk_flag"),
            "summary_primary": a.get("summary_primary", ""),
            "summary_secondary": a.get("summary_secondary", ""),
            "novelty_status": novelty_map.get(a.get("deduplicated_article_id"), "new"),
            "tracked_players_mentioned": a.get("tracked_players_mentioned", []),
        })

    sentiment_context = {
        "today_average": round(today_avg, 3),
        "7day_average": round(avg_7d, 3) if avg_7d else None,
        "trend": trend,
    }

    org_name = org.get("name", "the organization")
    lang_primary = org.get("language_primary", "en")

    lang_instruction = (
        f"Write executive_summary in {lang_primary} (bullet list, 5-7 items, each ≤ 40 words, starting with '• ').\n"
        f"Write executive_summary_en in English (same format).\n"
        f"Write all other text fields in both {lang_primary} and English where applicable."
        if lang_primary != "en"
        else "Write all text in English. executive_summary and executive_summary_en can be identical."
    )

    # Korean-specific tone guidance
    lang_tone = ""
    if lang_primary == "ko":
        lang_tone = """
LANGUAGE TONE (Korean output only):
- Use polite, advisory Korean for recommended actions
- Preferred endings: 고려해 볼 수 있다, 검토해 볼 수 있다, ~ 방향을 권고한다
- Forbidden: 필요하다, 해야 한다, 반드시, ~할 것
- Write as a respectful advisor presenting options, not as an authority issuing directives"""

    prompt = f"""You are the Chief Intelligence Analyst for {org_name}.
Today is {run_date}.

Analyze {len(analysis_context)} news articles and produce a comprehensive executive briefing.

Sentiment trend: {json.dumps(sentiment_context)}

=== TRACKED ENTITIES (summarize any news; flag if action needed) ===
{entity_ctx}

=== UPCOMING EVENTS (flag preparation stories and key dates) ===
{events_ctx}

Articles (ordered by relevance):
{json.dumps(analysis_context, ensure_ascii=False, indent=2)}

{lang_instruction}{lang_tone}

Return JSON matching this schema exactly:
{SYNTHESIS_SCHEMA}

Requirements:
- List up to 5 trending narratives (most important first)
- Flag all crisis/high-risk items in crisis_alerts (may be empty [])
- Identify 1-3 PR opportunities (may be empty [])
- Note competitive intelligence where relevant (may be empty [])
- Provide 3-5 recommended actions ordered by priority"""

    system_msg = prompts.get(
        "synthesis",
        f"You are the Chief Intelligence Analyst for {org_name}. Return JSON only.",
    )

    llm = get_org_llm(org, mode="smart")
    model_name = get_org_model_name(org, mode="smart")

    try:
        resp = await llm.ainvoke([
            SystemMessage(content=system_msg),
            HumanMessage(content=prompt),
        ])
        text = resp.content.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0:
            synthesis_data = json.loads(text[start:end])
            synthesis_data["sentiment_today"] = today_avg
            synthesis_data["sentiment_7day_avg"] = avg_7d
            synthesis_data["sentiment_trend"] = trend
            synthesis_data["articles_synthesized"] = len(analyses)

            synthesis_id = insert_synthesis(
                org_id=org_id,
                run_uuid=run_uuid,
                run_date=run_date,
                synthesis=synthesis_data,
                model_used=model_name,
            )
            logger.info("synthesize_node_done", synthesis_id=synthesis_id)
            return {"synthesis_id": synthesis_id, "stage": "synthesize"}
    except Exception as e:
        logger.error("synthesize_error", error=str(e))
        return {"synthesis_id": None, "stage": "synthesize", "errors": [f"synthesis_node: {e}"]}

    return {"synthesis_id": None, "stage": "synthesize"}
