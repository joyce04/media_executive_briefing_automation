import json
from datetime import datetime, timezone
from database.connection import get_conn


def insert_analysis(
    org_id: int,
    run_uuid: str,
    deduplicated_article_id: int,
    raw_article_id: int,
    analysis: dict,
    model_used: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO article_analyses
               (org_id, run_uuid, deduplicated_article_id, raw_article_id,
                sentiment, sentiment_score, sentiment_rationale,
                primary_topic, secondary_topics,
                players_mentioned, clubs_mentioned, officials_mentioned, venues_mentioned,
                relevance_score, risk_flag, risk_rationale,
                summary_primary, summary_secondary, key_quote,
                model_used, prompt_tokens, completion_tokens, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                org_id, run_uuid, deduplicated_article_id, raw_article_id,
                analysis.get("sentiment", "neutral"),
                analysis.get("sentiment_score", 0.0),
                analysis.get("sentiment_rationale"),
                analysis.get("primary_topic", "other"),
                json.dumps(analysis.get("secondary_topics", [])),
                json.dumps(analysis.get("players_mentioned", [])),
                json.dumps(analysis.get("clubs_mentioned", [])),
                json.dumps(analysis.get("officials_mentioned", [])),
                json.dumps(analysis.get("venues_mentioned", [])),
                analysis.get("relevance_score", 5),
                analysis.get("risk_flag", "neutral"),
                analysis.get("risk_rationale"),
                analysis.get("summary_primary", ""),
                analysis.get("summary_secondary", ""),
                analysis.get("key_quote"),
                model_used,
                prompt_tokens,
                completion_tokens,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return cur.lastrowid


def get_analyses_for_run(run_uuid: str, org_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT aa.*, ra.title, ra.url, ra.source_language,
                      da.novelty_status, da.story_cluster_id
               FROM article_analyses aa
               JOIN deduplicated_articles da ON aa.deduplicated_article_id = da.id
               JOIN raw_articles ra ON aa.raw_article_id = ra.id
               WHERE aa.run_uuid = ? AND aa.org_id = ?
               ORDER BY aa.relevance_score DESC, aa.id""",
            (run_uuid, org_id),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            for field in ("secondary_topics", "players_mentioned", "clubs_mentioned",
                          "officials_mentioned", "venues_mentioned"):
                if d.get(field):
                    d[field] = json.loads(d[field])
            results.append(d)
        return results


def get_recent_sentiment_history(org_id: int, days: int = 7) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT run_date, total_articles, avg_sentiment_score
               FROM daily_sentiment_history
               WHERE org_id = ?
               ORDER BY run_date DESC
               LIMIT ?""",
            (org_id, days),
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_sentiment_history(org_id: int, run_date: str, stats: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO daily_sentiment_history
               (org_id, run_date, total_articles, positive_count, neutral_count,
                negative_count, crisis_count, avg_sentiment_score, top_topics)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                org_id,
                run_date,
                stats["total_articles"],
                stats["positive_count"],
                stats["neutral_count"],
                stats["negative_count"],
                stats["crisis_count"],
                stats["avg_sentiment_score"],
                json.dumps(stats.get("top_topics", [])),
            ),
        )
