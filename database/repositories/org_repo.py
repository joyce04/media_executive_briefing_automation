import hashlib
import json
import secrets
import sqlite3
from database.connection import get_conn


def get_org_by_slug(slug: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM organizations WHERE slug = ?", (slug,)
        ).fetchone()
        return dict(row) if row else None


def get_org_by_id(org_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM organizations WHERE id = ?", (org_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_active_orgs() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM organizations WHERE is_active = 1 ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def create_org(
    slug: str,
    name: str,
    name_short: str,
    primary_color: str = "#1a56db",
    secondary_color: str = "#1e429f",
    logo_url: str | None = None,
    language_primary: str = "en",
    timezone: str = "UTC",
    schedule_cron: str = "0 7 * * *",
    model_tier: str = "starter",
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO organizations
               (slug, name, name_short, primary_color, secondary_color, logo_url,
                language_primary, timezone, schedule_cron, model_tier)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (slug, name, name_short, primary_color, secondary_color, logo_url,
             language_primary, timezone, schedule_cron, model_tier),
        )
        return cur.lastrowid


def update_org(org_id: int, **fields) -> None:
    allowed = {
        "name", "name_short", "primary_color", "secondary_color", "logo_url",
        "language_primary", "timezone", "schedule_cron", "model_tier", "is_active",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = "datetime('now')"
    set_clause = ", ".join(
        f"{k} = datetime('now')" if v == "datetime('now')" else f"{k} = ?"
        for k, v in updates.items()
    )
    values = [v for v in updates.values() if v != "datetime('now')"]
    values.append(org_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE organizations SET {set_clause} WHERE id = ?", values)


def get_org_sources(org_id: int, active_only: bool = True) -> list[dict]:
    query = "SELECT * FROM org_sources WHERE org_id = ?"
    if active_only:
        query += " AND is_active = 1"
    query += " ORDER BY priority, id"
    with get_conn() as conn:
        rows = conn.execute(query, (org_id,)).fetchall()
        return [dict(r) for r in rows]


def upsert_org_source(org_id: int, source_id: str, name: str, source_type: str,
                      url: str, language: str, priority: str = "medium") -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO org_sources (org_id, source_id, name, source_type, url, language, priority)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(org_id, source_id) DO UPDATE SET
                 name=excluded.name, source_type=excluded.source_type, url=excluded.url,
                 language=excluded.language, priority=excluded.priority""",
            (org_id, source_id, name, source_type, url, language, priority),
        )


def get_org_entities(org_id: int, entity_type: str | None = None,
                     active_only: bool = True) -> list[dict]:
    query = "SELECT * FROM org_entities WHERE org_id = ?"
    params: list = [org_id]
    if entity_type:
        query += " AND entity_type = ?"
        params.append(entity_type)
    if active_only:
        query += " AND is_active = 1"
    query += " ORDER BY priority, id"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["attributes"] = json.loads(d.get("attributes") or "{}")
            result.append(d)
        return result


def upsert_org_entity(org_id: int, entity_type: str, name_primary: str,
                      name_alt: str | None = None, priority: int = 2,
                      attributes: dict | None = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO org_entities
               (org_id, entity_type, name_primary, name_alt, priority, attributes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (org_id, entity_type, name_primary, name_alt, priority,
             json.dumps(attributes or {})),
        )
        return cur.lastrowid


def get_org_prompts(org_id: int) -> dict[str, str]:
    """Returns {prompt_key: system_msg} for all prompts belonging to this org."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT prompt_key, system_msg FROM org_prompts WHERE org_id = ?", (org_id,)
        ).fetchall()
        return {r["prompt_key"]: r["system_msg"] for r in rows}


def upsert_org_prompt(org_id: int, prompt_key: str, system_msg: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO org_prompts (org_id, prompt_key, system_msg)
               VALUES (?, ?, ?)
               ON CONFLICT(org_id, prompt_key) DO UPDATE SET system_msg=excluded.system_msg""",
            (org_id, prompt_key, system_msg),
        )


def get_org_recipients(org_id: int, active_only: bool = True) -> dict[str, list[dict]]:
    """Returns {role: [{name, email}, ...]} grouped by role."""
    query = "SELECT * FROM org_recipients WHERE org_id = ?"
    if active_only:
        query += " AND is_active = 1"
    query += " ORDER BY role, id"
    with get_conn() as conn:
        rows = conn.execute(query, (org_id,)).fetchall()
    result: dict[str, list[dict]] = {"to": [], "cc": [], "bcc": []}
    for r in rows:
        d = dict(r)
        result.setdefault(d["role"], []).append({"name": d["name"], "email": d["email"]})
    return result


def add_org_recipient(org_id: int, role: str, name: str, email: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO org_recipients (org_id, role, name, email) VALUES (?, ?, ?, ?)",
            (org_id, role, name, email),
        )
        return cur.lastrowid


def remove_org_recipient(recipient_id: int, org_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM org_recipients WHERE id = ? AND org_id = ?",
            (recipient_id, org_id),
        )


def get_org_config(org_id: int) -> dict:
    """Full org config bundle passed into PipelineState."""
    org = get_org_by_id(org_id)
    if not org:
        raise ValueError(f"Organization {org_id} not found")
    return {
        "org": org,
        "sources": get_org_sources(org_id),
        "entities": get_org_entities(org_id),
        "prompts": get_org_prompts(org_id),
        "recipients": get_org_recipients(org_id),
    }


# --- API key management ---

def generate_api_key(org_id: int, label: str = "default") -> str:
    """Create a new API key for an org. Returns the raw key (shown once)."""
    raw_key = secrets.token_hex(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO api_keys (org_id, key_hash, label) VALUES (?, ?, ?)",
            (org_id, key_hash, label),
        )
    return raw_key


def get_org_by_api_key(raw_key: str) -> dict | None:
    """Look up org from a raw API key. Updates last_used_at."""
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT o.* FROM organizations o
               JOIN api_keys k ON k.org_id = o.id
               WHERE k.key_hash = ? AND k.is_active = 1 AND o.is_active = 1""",
            (key_hash,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE api_keys SET last_used_at = datetime('now') WHERE key_hash = ?",
                (key_hash,),
            )
        return dict(row) if row else None


def list_api_keys(org_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, label, created_at, last_used_at, is_active
               FROM api_keys WHERE org_id = ? ORDER BY created_at DESC""",
            (org_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def revoke_api_key(key_id: int, org_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE api_keys SET is_active = 0 WHERE id = ? AND org_id = ?",
            (key_id, org_id),
        )
