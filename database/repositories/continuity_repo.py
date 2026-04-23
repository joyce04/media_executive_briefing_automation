import json
import uuid
from database.connection import get_conn


def get_active_stories(org_id: int, lookback_days: int = 7) -> list[dict]:
    """Get all non-resolved story clusters active in the last N days."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM story_continuity
               WHERE org_id = ?
                 AND last_seen_date >= date('now', ?)
                 AND status != 'resolved'
               ORDER BY days_active DESC""",
            (org_id, f"-{lookback_days} days"),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("representative_article_ids"):
                d["representative_article_ids"] = json.loads(d["representative_article_ids"])
            results.append(d)
        return results


def upsert_story_cluster(
    org_id: int,
    story_cluster_id: str,
    run_date: str,
    canonical_title: str,
    novelty_status: str,
    article_id: int,
    run_uuid: str,
) -> None:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM story_continuity WHERE org_id = ? AND story_cluster_id = ?",
            (org_id, story_cluster_id),
        ).fetchone()

        if existing:
            existing_ids = json.loads(existing["representative_article_ids"] or "[]")
            if article_id not in existing_ids:
                existing_ids.append(article_id)
            new_days = existing["days_active"]
            if str(existing["last_seen_date"]) < str(run_date):
                new_days += 1
            conn.execute(
                """UPDATE story_continuity
                   SET last_seen_date = ?,
                       days_active = ?,
                       status = ?,
                       representative_article_ids = ?,
                       latest_run_uuid = ?
                   WHERE org_id = ? AND story_cluster_id = ?""",
                (run_date, new_days, novelty_status,
                 json.dumps(existing_ids), run_uuid,
                 org_id, story_cluster_id),
            )
        else:
            conn.execute(
                """INSERT INTO story_continuity
                   (org_id, story_cluster_id, first_seen_date, last_seen_date,
                    canonical_title, days_active, status,
                    representative_article_ids, latest_run_uuid)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (org_id, story_cluster_id, run_date, run_date,
                 canonical_title, novelty_status,
                 json.dumps([article_id]), run_uuid),
            )


def create_new_cluster_id() -> str:
    return str(uuid.uuid4())


def log_keyword(
    org_id: int,
    run_uuid: str,
    run_date: str,
    keyword_query: str,
    language: str,
    source_type: str,
    rationale: str | None = None,
    articles_found: int = 0,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO search_keyword_log
               (org_id, run_uuid, run_date, keyword_query, language, rationale,
                source_type, articles_found)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (org_id, run_uuid, run_date, keyword_query, language,
             rationale, source_type, articles_found),
        )


def update_keyword_yield(run_uuid: str, keyword_query: str, articles_found: int) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE search_keyword_log
               SET articles_found = ?
               WHERE run_uuid = ? AND keyword_query = ?""",
            (articles_found, run_uuid, keyword_query),
        )
