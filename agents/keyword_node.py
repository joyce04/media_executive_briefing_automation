"""Node 1: LLM generates today's targeted search queries from org config + yesterday's context."""
import json
import urllib.parse
import structlog
import feedparser
import httpx
from datetime import date, datetime
from langchain_core.messages import SystemMessage, HumanMessage
import agents.llm_client as llm_client
from database.repositories.report_repo import get_yesterday_synthesis
from database.repositories.continuity_repo import get_active_stories
from models.state import PipelineState

logger = structlog.get_logger()


def _days_until(date_str: str, from_date: date) -> int | None:
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d").date()
        return (target - from_date).days
    except Exception:
        return None


async def _fetch_entity_headlines(entities: list[dict]) -> dict[str, list[str]]:
    """Fetch recent Google News headlines for priority-1 tracked entities.

    Returns {name: [headline, ...]} with up to 4 headlines per entity.
    Gives the LLM live context (current club, recent events) without relying
    on potentially stale training knowledge.
    """
    result: dict[str, list[str]] = {}
    p1 = [e for e in entities if e.get("priority", 99) <= 1]
    if not p1:
        return result

    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True,
                                  headers={"User-Agent": "MediaIntel/1.0"}) as client:
        for entity in p1:
            name_primary = entity.get("name_primary", "")
            name_alt = entity.get("name_alt", "")
            headlines: list[str] = []
            for query in [name_primary, name_alt]:
                if not query or len(headlines) >= 4:
                    break
                url = (
                    "https://news.google.com/rss/search?q="
                    + urllib.parse.quote(query)
                    + "&hl=en&gl=US&ceid=US:en"
                )
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    feed = feedparser.parse(resp.content)
                    for entry in feed.entries[:3]:
                        title = entry.get("title", "").strip()
                        if title and title not in headlines:
                            headlines.append(title)
                except Exception:
                    pass
            if name_primary:
                result[name_primary] = headlines[:4]
    return result


def _build_entity_context(entities: list[dict],
                           headlines: dict[str, list[str]] | None = None) -> str:
    """Format priority-1/2 tracked entities for LLM context."""
    top = [e for e in entities if e.get("priority", 99) <= 2]
    lines = []
    for e in top:
        pri = e.get("priority", 2)
        attrs = e.get("attributes", {})
        watch_reason = attrs.get("watch_reason", "")
        name_alt = e.get("name_alt", "")
        alt_str = f" ({name_alt})" if name_alt else ""
        line = f"- [P{pri}] {e['name_primary']}{alt_str}: {watch_reason}"
        if headlines and pri == 1:
            entity_headlines = headlines.get(e.get("name_primary", ""), [])
            if entity_headlines:
                line += "\n  Recent headlines: " + " | ".join(entity_headlines)
        lines.append(line)
    return "\n".join(lines) if lines else "(none configured)"


def _build_tournament_context(tournaments: list[dict], from_date: date) -> str:
    """Return only tournaments that are ongoing or starting within 12 months."""
    lines = []
    for t in tournaments:
        attrs = t.get("attributes", {})
        end_days = _days_until(attrs.get("end_date", ""), from_date)
        if end_days is not None and end_days < 0:
            continue
        start_days = _days_until(attrs.get("start_date", ""), from_date)
        if start_days is not None and start_days > 365:
            continue
        if start_days is not None and start_days >= 0:
            status_label = f"starts in {start_days}d"
        elif end_days is not None:
            status_label = f"ongoing (ends in {end_days}d)"
        else:
            status_label = "ongoing"
        name_alt = t.get("name_alt", "")
        alt_str = f" ({name_alt})" if name_alt else ""
        lines.append(f"- {t['name_primary']}{alt_str}, {status_label}")
    return "\n".join(lines) if lines else "(no active or upcoming tournaments within 12 months)"


def _build_default_keywords(org_config: dict, today: date) -> list[dict]:
    """Build fallback keywords from org's entity config when LLM is unavailable."""
    entities = org_config.get("entities", [])
    org = org_config.get("org", {})
    lang = org.get("language_primary", "en")

    keywords: list[dict] = []

    # Use any keyword_core entities first
    for e in entities:
        if e.get("entity_type") != "keyword_core":
            continue
        keywords.append({
            "query": e["name_primary"],
            "language": lang,
            "source": "google_news",
            "rationale": e.get("attributes", {}).get("watch_reason", "core keyword"),
        })

    # Per-entity queries for players/persons
    for e in entities:
        if e.get("entity_type") not in ("player", "person") or e.get("priority", 99) > 2:
            continue
        keywords.append({
            "query": e["name_primary"],
            "language": lang,
            "source": "google_news",
            "rationale": f"{e['name_primary']} watch",
        })
        if e.get("name_alt") and e.get("priority", 99) <= 1:
            keywords.append({
                "query": e["name_alt"],
                "language": "en",
                "source": "google_news",
                "rationale": f"{e['name_primary']} EN watch",
            })

    return keywords


async def run(state: PipelineState) -> dict:
    run_date = state["run_date"]
    run_uuid = state["run_uuid"]
    org_id = state["org_id"]
    org_config = state["org_config"]
    org = org_config["org"]
    entities = org_config.get("entities", [])
    prompts = org_config.get("prompts", {})

    logger.info("keyword_node_start", run_date=run_date, org=org["slug"])

    players = [e for e in entities if e.get("entity_type") in ("player", "person")]
    tournaments = [e for e in entities if e.get("entity_type") == "tournament"]

    try:
        today = datetime.strptime(str(run_date), "%Y-%m-%d").date()
    except Exception:
        today = date.today()

    # Fetch live headlines for P1 entities so the LLM gets current context
    entity_headlines = await _fetch_entity_headlines(players)
    logger.debug("entity_headlines_fetched", entities=list(entity_headlines.keys()))

    entity_ctx = _build_entity_context(players, headlines=entity_headlines)
    tournament_ctx = _build_tournament_context(tournaments, today)

    yesterday_synthesis = get_yesterday_synthesis(org_id, run_date)
    active_stories = get_active_stories(org_id, lookback_days=7)

    if not yesterday_synthesis and not active_stories:
        defaults = _build_default_keywords(org_config, today)
        logger.info("keyword_node_no_context", using="defaults", count=len(defaults))
        return {"generated_keywords": defaults, "stage": "keywords"}

    context_parts = []
    if yesterday_synthesis:
        narratives = yesterday_synthesis.get("trending_narratives", [])[:5]
        context_parts.append(f"Yesterday's top narratives:\n{json.dumps(narratives, ensure_ascii=False, indent=2)}")
    if active_stories:
        stories_summary = [
            {"title": s["canonical_title"], "days_active": s["days_active"], "status": s["status"]}
            for s in active_stories[:10]
        ]
        context_parts.append(f"Active ongoing stories:\n{json.dumps(stories_summary, ensure_ascii=False, indent=2)}")

    context = "\n\n".join(context_parts)
    org_name = org.get("name", "the organization")
    lang_primary = org.get("language_primary", "en")

    prompt = f"""Today is {run_date}. Generate targeted news search queries for {org_name}'s daily media intelligence pipeline.

{context}

=== TRACKED ENTITIES — recent live headlines are provided to identify current context ===
{entity_ctx}

CONTEXT RULE: Derive current context (e.g. current club, recent events) ONLY from the "Recent headlines" shown above.
- If headlines clearly mention a detail → include it in the query
- If headlines are absent → use the entity name ONLY
- NEVER guess or use training-data knowledge for details that may be out of date

=== ACTIVE / UPCOMING EVENTS ===
{tournament_ctx}

Generate 12-18 search queries following these rules:
- Prioritise active stories (listed above) — generate follow-up queries for each ongoing narrative
- Only generate event queries for events listed above
- Today is {run_date}; do not generate queries about events that concluded before this date

QUERY MIX (12-18 total):
- Mix of queries in the org's primary language ({lang_primary}) and English
- At least 1 query per priority-1 entity (with current context if known from headlines)
- At least 2 event-related queries for active or upcoming events
- 1-2 wildcard queries for unexpected breaking news

Return a JSON array only, no other text:
[{{"query": "search query string", "language": "{lang_primary} or en", "source": "google_news or naver", "rationale": "why this query is current/relevant today"}}]"""

    system_msg = prompts.get(
        "keyword_generation",
        f"You are a media intelligence analyst for {org_name}. Return JSON only.",
    )

    llm = llm_client.get_org_llm(org, mode="fast")
    error_msg: str | None = None
    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_msg),
            HumanMessage(content=prompt),
        ])
        text = response.content.strip()
        try:
            keywords = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("[")
            end = text.rfind("]") + 1
            keywords = json.loads(text[start:end]) if start >= 0 and end > start else []
        if keywords:
            logger.info("keyword_node_done", count=len(keywords))
            return {"generated_keywords": keywords, "stage": "keywords"}
    except (json.JSONDecodeError, ValueError) as e:
        error_msg = str(e)
        logger.error("keyword_node_parse_failed", error=error_msg, exc_info=True)
    except Exception as e:
        error_msg = str(e)
        logger.error("keyword_node_failed", error=error_msg, exc_info=True)

    result: dict = {
        "generated_keywords": _build_default_keywords(org_config, today),
        "stage": "keywords",
    }
    if error_msg:
        result["errors"] = [f"keyword_node: {error_msg}"]
    return result
