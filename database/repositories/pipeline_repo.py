import sqlite3
from datetime import datetime, timezone
from database.connection import get_conn


def create_run(org_id: int, run_date: str, run_uuid: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO pipeline_runs (org_id, run_date, run_uuid, status, started_at)
               VALUES (?, ?, ?, 'started', ?)""",
            (org_id, run_date, run_uuid, datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


def update_run_status(run_uuid: str, status: str, **kwargs) -> None:
    fields = ["status = ?"]
    values = [status]
    if status in ("completed", "failed"):
        fields.append("completed_at = ?")
        values.append(datetime.now(timezone.utc).isoformat())
    for k, v in kwargs.items():
        fields.append(f"{k} = ?")
        values.append(v)
    values.append(run_uuid)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE pipeline_runs SET {', '.join(fields)} WHERE run_uuid = ?",
            values,
        )


def get_run(run_uuid: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM pipeline_runs WHERE run_uuid = ?", (run_uuid,)
        ).fetchone()


def get_runs_for_org(org_id: int, limit: int = 30) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM pipeline_runs WHERE org_id = ?
               ORDER BY run_date DESC LIMIT ?""",
            (org_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_last_completed_run(org_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM pipeline_runs
               WHERE org_id = ? AND status = 'completed'
               ORDER BY run_date DESC LIMIT 1""",
            (org_id,),
        ).fetchone()
