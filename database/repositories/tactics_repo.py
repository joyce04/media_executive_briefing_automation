"""Database access functions for the tactics intelligence pipeline."""
import json
from datetime import datetime, timezone
from database.connection import get_tactics_conn


def create_tactics_run(run_uuid: str, week_start: str, week_end: str) -> None:
    """Insert a new tactics pipeline run record."""
    with get_tactics_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO tactics_pipeline_runs
               (run_uuid, week_start, week_end, status, started_at)
               VALUES (?, ?, ?, 'started', ?)""",
            (run_uuid, week_start, week_end, datetime.now(timezone.utc).isoformat()),
        )


def update_tactics_run_status(run_uuid: str, status: str, error_message: str | None = None,
                               **kwargs) -> None:
    """Update status and optional fields on a tactics pipeline run record."""
    fields = ["status = ?"]
    values = [status]
    if status in ("completed", "failed"):
        fields.append("completed_at = ?")
        values.append(datetime.now(timezone.utc).isoformat())
    if error_message is not None:
        fields.append("error_message = ?")
        values.append(error_message)
    for k, v in kwargs.items():
        fields.append(f"{k} = ?")
        values.append(v)
    values.append(run_uuid)
    with get_tactics_conn() as conn:
        conn.execute(
            f"UPDATE tactics_pipeline_runs SET {', '.join(fields)} WHERE run_uuid = ?",
            values,
        )


def insert_tactics_raw_articles_batch(articles_data: list[tuple]) -> list[int]:
    """Insert a batch of raw tactics articles.

    articles_data should be a list of tuples:
    (run_uuid, source_id, url, url_hash, title, body_text, summary_from_source, published_at)

    Returns a list of newly inserted row IDs.
    """
    if not articles_data:
        return []

    with get_tactics_conn() as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO tactics_raw_articles
               (run_uuid, source_id, url, url_hash, title,
                body_text, summary_from_source, published_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            articles_data,
        )

        url_hashes = [row[3] for row in articles_data]
        run_uuid = articles_data[0][0]

        if not url_hashes:
            return []

        placeholders = ",".join("?" for _ in url_hashes)
        rows = conn.execute(
            f"SELECT id FROM tactics_raw_articles WHERE run_uuid = ? AND url_hash IN ({placeholders})",
            [run_uuid] + url_hashes,
        ).fetchall()

        return [r["id"] for r in rows]


def get_tactics_raw_articles_for_run(run_uuid: str) -> list[dict]:
    """Return all raw articles collected in the given run."""
    with get_tactics_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tactics_raw_articles WHERE run_uuid = ? ORDER BY id",
            (run_uuid,),
        ).fetchall()
        return [dict(r) for r in rows]


def insert_tactics_deduplicated_article(
    run_uuid: str,
    canonical_article_id: int,
    dedup_cluster_id: str,
    dedup_method: str,
    confidence: float,
    duplicate_ids: list[int],
) -> int:
    """Insert a deduplicated article record and return its ID."""
    with get_tactics_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tactics_deduplicated_articles
               (run_uuid, canonical_article_id, dedup_cluster_id, dedup_method,
                confidence, duplicate_count, duplicate_ids)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                run_uuid, canonical_article_id, dedup_cluster_id, dedup_method,
                confidence, len(duplicate_ids), json.dumps(duplicate_ids),
            ),
        )
        return cur.lastrowid


def get_tactics_deduplicated_articles_for_run(run_uuid: str) -> list[dict]:
    """Return all deduplicated articles for the given run, joined with raw article fields."""
    with get_tactics_conn() as conn:
        rows = conn.execute(
            """SELECT da.*, ra.title, ra.source_id, ra.url,
                      ra.summary_from_source, ra.body_text, ra.published_at
               FROM tactics_deduplicated_articles da
               JOIN tactics_raw_articles ra ON da.canonical_article_id = ra.id
               WHERE da.run_uuid = ?
               ORDER BY da.id""",
            (run_uuid,),
        ).fetchall()
        return [dict(r) for r in rows]


def insert_tactics_analysis(
    run_uuid: str,
    deduplicated_article_id: int,
    raw_article_id: int,
    analysis: dict,
    model_used: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> int:
    """Insert a per-article tactical analysis record and return its ID."""
    with get_tactics_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tactics_article_analyses
               (run_uuid, deduplicated_article_id, raw_article_id,
                tactical_theme, formations_discussed, concepts_mentioned,
                teams_referenced, coaches_referenced, leagues_referenced,
                difficulty_level, summary_en, summary_ko, key_insight,
                model_used, prompt_tokens, completion_tokens, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_uuid,
                deduplicated_article_id,
                raw_article_id,
                analysis.get("tactical_theme"),
                json.dumps(analysis.get("formations_discussed", []), ensure_ascii=False),
                json.dumps(analysis.get("concepts_mentioned", []), ensure_ascii=False),
                json.dumps(analysis.get("teams_referenced", []), ensure_ascii=False),
                json.dumps(analysis.get("coaches_referenced", []), ensure_ascii=False),
                json.dumps(analysis.get("leagues_referenced", []), ensure_ascii=False),
                analysis.get("difficulty_level"),
                analysis.get("summary_en"),
                analysis.get("summary_ko"),
                analysis.get("key_insight"),
                model_used,
                prompt_tokens,
                completion_tokens,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return cur.lastrowid


def get_tactics_analyses_for_run(run_uuid: str) -> list[dict]:
    """Return all article analyses for the given run, joined with article title/url."""
    with get_tactics_conn() as conn:
        rows = conn.execute(
            """SELECT aa.*, ra.title, ra.url, ra.source_id, ra.published_at
               FROM tactics_article_analyses aa
               JOIN tactics_raw_articles ra ON aa.raw_article_id = ra.id
               WHERE aa.run_uuid = ?
               ORDER BY aa.id""",
            (run_uuid,),
        ).fetchall()
        return [dict(r) for r in rows]


def insert_tactics_synthesis(
    run_uuid: str,
    week_start: str,
    week_end: str,
    synthesis: dict,
    model_used: str,
) -> int:
    """Insert (or replace) the weekly synthesis record and return its ID."""
    with get_tactics_conn() as conn:
        cur = conn.execute(
            """INSERT OR REPLACE INTO tactics_weekly_synthesis
               (run_uuid, week_start, week_end,
                novel_tactics, executive_summary_ko,
                top_themes_ko, formation_trends_ko,
                set_piece_insights_ko,
                articles_synthesized, model_used, synthesized_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_uuid,
                week_start,
                week_end,
                json.dumps(synthesis.get("novel_tactics", []), ensure_ascii=False),
                json.dumps(synthesis.get("executive_summary_ko", []), ensure_ascii=False),
                json.dumps(synthesis.get("top_themes_ko", []), ensure_ascii=False),
                json.dumps(synthesis.get("formation_trends_ko", []), ensure_ascii=False),
                json.dumps(synthesis.get("set_piece_insights_ko", []), ensure_ascii=False),
                synthesis.get("articles_synthesized", 0),
                model_used,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return cur.lastrowid


def get_tactics_synthesis_for_week(week_start: str) -> dict | None:
    """Return the synthesis record for a given week_start date, or None."""
    with get_tactics_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tactics_weekly_synthesis WHERE week_start = ?",
            (week_start,),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        # Deserialize JSON fields
        for field in (
            "novel_tactics", "executive_summary_ko",
            "top_themes_ko", "formation_trends_ko",
            "set_piece_insights_ko",
        ):
            val = data.get(field)
            if val and isinstance(val, str):
                try:
                    data[field] = json.loads(val)
                except (json.JSONDecodeError, ValueError):
                    pass
        return data
