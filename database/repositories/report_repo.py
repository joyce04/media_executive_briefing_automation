import json
from datetime import datetime, timezone
from database.connection import get_conn


def insert_synthesis(
    org_id: int,
    run_uuid: str,
    run_date: str,
    synthesis: dict,
    model_used: str,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT OR REPLACE INTO daily_synthesis
               (org_id, run_uuid, run_date,
                trending_narratives, crisis_alerts, pr_opportunities, competitive_intel,
                sentiment_today, sentiment_7day_avg, sentiment_trend,
                recommended_actions, executive_summary, executive_summary_en,
                articles_synthesized, model_used, synthesized_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                org_id, run_uuid, run_date,
                json.dumps(synthesis.get("trending_narratives", [])),
                json.dumps(synthesis.get("crisis_alerts", [])),
                json.dumps(synthesis.get("pr_opportunities", [])),
                json.dumps(synthesis.get("competitive_intel", [])),
                synthesis.get("sentiment_today", 0.0),
                synthesis.get("sentiment_7day_avg"),
                synthesis.get("sentiment_trend"),
                json.dumps(synthesis.get("recommended_actions", [])),
                json.dumps(synthesis.get("executive_summary", [])),
                json.dumps(synthesis.get("executive_summary_en", [])),
                synthesis.get("articles_synthesized", 0),
                model_used,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return cur.lastrowid


def get_synthesis_for_date(org_id: int, run_date: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM daily_synthesis WHERE org_id = ? AND run_date = ?",
            (org_id, run_date),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        for field in ("trending_narratives", "crisis_alerts", "pr_opportunities",
                      "competitive_intel", "recommended_actions",
                      "executive_summary", "executive_summary_en"):
            if d.get(field):
                d[field] = json.loads(d[field])
        return d


def get_yesterday_synthesis(org_id: int, today_date: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM daily_synthesis
               WHERE org_id = ? AND run_date < ?
               ORDER BY run_date DESC LIMIT 1""",
            (org_id, today_date),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        for field in ("trending_narratives", "crisis_alerts", "pr_opportunities",
                      "competitive_intel", "recommended_actions",
                      "executive_summary", "executive_summary_en"):
            if d.get(field):
                d[field] = json.loads(d[field])
        return d


def insert_report_record(
    org_id: int,
    run_uuid: str,
    run_date: str,
    report_format: str,
    file_path: str | None = None,
    file_size_bytes: int | None = None,
    delivery_target: str | None = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO generated_reports
               (org_id, run_uuid, run_date, report_format, file_path,
                file_size_bytes, delivery_target)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (org_id, run_uuid, run_date, report_format, file_path,
             file_size_bytes, delivery_target),
        )
        return cur.lastrowid


def update_report_delivery(report_id: int, status: str, error: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE generated_reports
               SET delivery_status = ?, delivered_at = ?, error_message = ?
               WHERE id = ?""",
            (
                status,
                datetime.now(timezone.utc).isoformat() if status == "sent" else None,
                error,
                report_id,
            ),
        )


def get_reports_for_org(org_id: int, limit: int = 30) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM generated_reports
               WHERE org_id = ?
               ORDER BY run_date DESC, id DESC
               LIMIT ?""",
            (org_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
