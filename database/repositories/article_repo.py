import json
import hashlib
import urllib.parse
from datetime import datetime
from database.connection import get_conn

# Tracking params that should not affect article identity
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "ref", "referrer",
})


def _canonical_url(url: str) -> str:
    """Strip well-known tracking query parameters before hashing."""
    try:
        parsed = urllib.parse.urlparse(url.strip().lower())
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        clean_qs = {k: v for k, v in qs.items() if k not in _TRACKING_PARAMS}
        clean = parsed._replace(query=urllib.parse.urlencode(clean_qs, doseq=True))
        return urllib.parse.urlunparse(clean)
    except Exception:
        return url.strip().lower()


def compute_url_hash(url: str) -> str:
    return hashlib.sha256(_canonical_url(url).encode()).hexdigest()


def insert_raw_articles_batch(org_id: int, articles_data: list[tuple]) -> list[int]:
    """
    Insert a batch of raw articles.
    articles_data: list of (run_uuid, source_id, source_language, url, url_hash,
                            title, body_text, summary_from_source, published_at)
    Returns list of newly inserted row IDs.
    """
    if not articles_data:
        return []

    # Prepend org_id to each tuple
    with_org = [(org_id, *row) for row in articles_data]

    with get_conn() as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO raw_articles
               (org_id, run_uuid, source_id, source_language, url, url_hash, title,
                body_text, summary_from_source, published_at, fetch_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'fetched')""",
            with_org,
        )
        url_hashes = [row[4] for row in articles_data]
        run_uuid = articles_data[0][0]
        placeholders = ",".join("?" for _ in url_hashes)
        rows = conn.execute(
            f"""SELECT id FROM raw_articles
                WHERE org_id = ? AND run_uuid = ? AND url_hash IN ({placeholders})""",
            [org_id, run_uuid] + url_hashes,
        ).fetchall()
        return [r["id"] for r in rows]


def get_raw_articles_for_run(run_uuid: str, org_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM raw_articles WHERE run_uuid = ? AND org_id = ? ORDER BY id",
            (run_uuid, org_id),
        ).fetchall()
        return [dict(r) for r in rows]


def insert_deduplicated_article(
    org_id: int,
    run_uuid: str,
    canonical_article_id: int,
    dedup_cluster_id: str,
    dedup_method: str,
    confidence: float,
    duplicate_ids: list[int],
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO deduplicated_articles
               (org_id, run_uuid, canonical_article_id, dedup_cluster_id, dedup_method,
                confidence, duplicate_count, duplicate_ids)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                org_id, run_uuid, canonical_article_id, dedup_cluster_id, dedup_method,
                confidence, len(duplicate_ids), json.dumps(duplicate_ids),
            ),
        )
        return cur.lastrowid


def update_dedup_novelty(dedup_id: int, novelty_status: str, story_cluster_id: str | None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE deduplicated_articles SET novelty_status = ?, story_cluster_id = ? WHERE id = ?",
            (novelty_status, story_cluster_id, dedup_id),
        )


def get_deduplicated_articles_for_run(run_uuid: str, org_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT da.*, ra.title, ra.source_language, ra.url,
                      ra.summary_from_source, ra.body_text, ra.published_at
               FROM deduplicated_articles da
               JOIN raw_articles ra ON da.canonical_article_id = ra.id
               WHERE da.run_uuid = ? AND da.org_id = ?
               ORDER BY da.id""",
            (run_uuid, org_id),
        ).fetchall()
        return [dict(r) for r in rows]


def get_recent_canonical_articles(org_id: int, days: int = 7,
                                   exclude_run_uuid: str = "") -> list[dict]:
    """Get canonical articles from the last N days for cross-day novelty comparison."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT da.id, da.story_cluster_id, da.novelty_status,
                      ra.title, ra.summary_from_source, ra.url_hash, ra.published_at,
                      pr.run_date
               FROM deduplicated_articles da
               JOIN raw_articles ra ON da.canonical_article_id = ra.id
               JOIN pipeline_runs pr ON da.run_uuid = pr.run_uuid
               WHERE da.org_id = ?
                 AND pr.run_date >= date('now', ?)
                 AND da.run_uuid != ?
               ORDER BY pr.run_date DESC, da.id""",
            (org_id, f"-{days} days", exclude_run_uuid),
        ).fetchall()
        return [dict(r) for r in rows]
