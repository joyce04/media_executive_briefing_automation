import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from database.connection import get_conn


def get_user_by_email(email: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? AND is_active = 1", (email,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ? AND is_active = 1", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_google_sub(google_sub: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE google_sub = ? AND is_active = 1", (google_sub,)
        ).fetchone()
        return dict(row) if row else None


def create_user(
    email: str,
    password_hash: str | None = None,
    google_sub: str | None = None,
    name: str = "",
    avatar_url: str | None = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO users (email, password_hash, google_sub, name, avatar_url)
               VALUES (?, ?, ?, ?, ?)""",
            (email, password_hash, google_sub, name, avatar_url),
        )
        return cur.lastrowid


def update_user(user_id: int, **fields) -> None:
    allowed = {"name", "avatar_url", "password_hash", "google_sub", "is_active"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE users SET {set_clause} WHERE id = ?",
            [*updates.values(), user_id],
        )


def get_user_orgs(user_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT o.*, uo.role FROM organizations o
               JOIN user_orgs uo ON uo.org_id = o.id
               WHERE uo.user_id = ? AND o.is_active = 1
               ORDER BY o.name""",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def add_user_to_org(user_id: int, org_id: int, role: str = "owner") -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO user_orgs (user_id, org_id, role) VALUES (?, ?, ?)""",
            (user_id, org_id, role),
        )


def get_user_org_role(user_id: int, org_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT role FROM user_orgs WHERE user_id = ? AND org_id = ?",
            (user_id, org_id),
        ).fetchone()
        return row["role"] if row else None


# --- Refresh token management ---

def store_refresh_token(user_id: int, token: str, expires_days: int = 30) -> None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_days)).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (user_id, token_hash, expires_at),
        )


def get_user_by_refresh_token(token: str) -> dict | None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT u.* FROM users u
               JOIN refresh_tokens rt ON rt.user_id = u.id
               WHERE rt.token_hash = ?
                 AND rt.expires_at > datetime('now')
                 AND u.is_active = 1""",
            (token_hash,),
        ).fetchone()
        return dict(row) if row else None


def revoke_refresh_token(token: str) -> None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with get_conn() as conn:
        conn.execute("DELETE FROM refresh_tokens WHERE token_hash = ?", (token_hash,))


def revoke_all_user_tokens(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM refresh_tokens WHERE user_id = ?", (user_id,))
