from datetime import datetime, timezone
from database.connection import get_conn


def get_all_plans() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM plans ORDER BY price_usd_monthly").fetchall()
        return [dict(r) for r in rows]


def get_plan_by_name(name: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM plans WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None


def get_plan_by_stripe_price(stripe_price_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM plans WHERE stripe_price_id = ?", (stripe_price_id,)
        ).fetchone()
        return dict(row) if row else None


def update_plan_stripe_price(plan_name: str, stripe_price_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE plans SET stripe_price_id = ? WHERE name = ?",
            (stripe_price_id, plan_name),
        )


def get_subscription(org_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT s.*, p.name as plan_name, p.model_tier, p.max_recipients,
                      p.max_orgs, p.price_usd_monthly
               FROM subscriptions s
               JOIN plans p ON p.id = s.plan_id
               WHERE s.org_id = ?""",
            (org_id,),
        ).fetchone()
        return dict(row) if row else None


def create_subscription(
    org_id: int,
    plan_name: str = "starter",
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    status: str = "trialing",
    trial_ends_at: str | None = None,
    current_period_end: str | None = None,
) -> int:
    plan = get_plan_by_name(plan_name)
    if not plan:
        raise ValueError(f"Plan '{plan_name}' not found")
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO subscriptions
               (org_id, plan_id, stripe_customer_id, stripe_subscription_id,
                status, trial_ends_at, current_period_end)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (org_id, plan["id"], stripe_customer_id, stripe_subscription_id,
             status, trial_ends_at, current_period_end),
        )
        return cur.lastrowid


def update_subscription(org_id: int, **fields) -> None:
    allowed = {
        "plan_id", "stripe_customer_id", "stripe_subscription_id",
        "status", "trial_ends_at", "current_period_end",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE subscriptions SET {set_clause} WHERE org_id = ?",
            [*updates.values(), org_id],
        )


def get_subscription_by_stripe_id(stripe_subscription_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE stripe_subscription_id = ?",
            (stripe_subscription_id,),
        ).fetchone()
        return dict(row) if row else None
