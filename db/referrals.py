"""Реферальная программа: атрибуция и учёт бонусов."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from config.referral import (
    REFERRAL_TIER_BASE_PERCENT,
    REFERRAL_TIER_MAX_PERCENT,
    REFERRAL_TIER_STEP_PERCENT,
)
from db.connection import get_db


async def init_referral_tables() -> None:
    async with get_db() as db:
        async with db.execute("PRAGMA table_info(users)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        if "referred_by_tg_id" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN referred_by_tg_id INTEGER")
        if "referral_welcome_used" not in cols:
            await db.execute(
                "ALTER TABLE users ADD COLUMN referral_welcome_used INTEGER NOT NULL DEFAULT 0"
            )
        if "pending_referral_days" not in cols:
            await db.execute(
                "ALTER TABLE users ADD COLUMN pending_referral_days INTEGER NOT NULL DEFAULT 0"
            )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS referral_attributions (
                referred_tg_id INTEGER PRIMARY KEY,
                referrer_tg_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_referral_attr_referrer
            ON referral_attributions(referrer_tg_id)
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referral_reward_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL UNIQUE,
                referred_tg_id INTEGER NOT NULL,
                referrer_tg_id INTEGER NOT NULL,
                referrer_bonus_days INTEGER NOT NULL DEFAULT 0,
                referred_bonus_days INTEGER NOT NULL DEFAULT 0,
                welcome_applied INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def count_paid_orders(tg_id: int) -> int:
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM orders WHERE tg_id = ? AND status = 'paid'",
            (tg_id,),
        ) as cur:
            return int((await cur.fetchone())[0])


async def get_referrer_tg_id(referred_tg_id: int) -> Optional[int]:
    async with get_db() as db:
        async with db.execute(
            "SELECT referrer_tg_id FROM referral_attributions WHERE referred_tg_id = ?",
            (referred_tg_id,),
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else None


async def get_user_referral_flags(tg_id: int) -> dict[str, Any]:
    async with get_db() as db:
        async with db.execute(
            """SELECT referred_by_tg_id, referral_welcome_used, pending_referral_days
               FROM users WHERE tg_id = ?""",
            (tg_id,),
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return {
                    "referred_by_tg_id": None,
                    "referral_welcome_used": False,
                    "pending_referral_days": 0,
                }
            return {
                "referred_by_tg_id": row[0],
                "referral_welcome_used": bool(row[1]),
                "pending_referral_days": int(row[2] or 0),
            }


async def set_referrer_if_empty(referred_tg_id: int, referrer_tg_id: int) -> bool:
    if referred_tg_id == referrer_tg_id:
        return False
    async with get_db() as db:
        async with db.execute(
            "SELECT 1 FROM referral_attributions WHERE referred_tg_id = ?",
            (referred_tg_id,),
        ) as cur:
            if await cur.fetchone():
                return False
        await db.execute(
            """INSERT INTO referral_attributions (referred_tg_id, referrer_tg_id)
               VALUES (?, ?)""",
            (referred_tg_id, referrer_tg_id),
        )
        await db.execute(
            "UPDATE users SET referred_by_tg_id = ? WHERE tg_id = ? AND referred_by_tg_id IS NULL",
            (referrer_tg_id, referred_tg_id),
        )
        await db.commit()
        return True


async def mark_welcome_used(tg_id: int) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET referral_welcome_used = 1 WHERE tg_id = ?",
            (tg_id,),
        )
        await db.commit()


async def clear_welcome_used(tg_id: int) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET referral_welcome_used = 0 WHERE tg_id = ?",
            (tg_id,),
        )
        await db.commit()


async def add_pending_referral_days(tg_id: int, days: int) -> None:
    extra = int(days)
    if extra <= 0:
        return
    async with get_db() as db:
        await db.execute(
            """UPDATE users
               SET pending_referral_days = COALESCE(pending_referral_days, 0) + ?
               WHERE tg_id = ?""",
            (extra, tg_id),
        )
        await db.commit()


async def take_pending_referral_days(tg_id: int) -> int:
    async with get_db() as db:
        async with db.execute(
            "SELECT pending_referral_days FROM users WHERE tg_id = ?",
            (tg_id,),
        ) as cur:
            row = await cur.fetchone()
            pending = int(row[0] or 0) if row else 0
        if pending <= 0:
            return 0
        await db.execute(
            "UPDATE users SET pending_referral_days = 0 WHERE tg_id = ?",
            (tg_id,),
        )
        await db.commit()
        return pending


_ACTIVE_REFERRED_PAID_SQL = """SELECT COUNT(DISTINCT a.referred_tg_id)
   FROM referral_attributions a
   INNER JOIN subscriptions s ON s.tg_id = a.referred_tg_id
   WHERE a.referrer_tg_id = ?
     AND s.is_active = 1
     AND s.client_email NOT LIKE 'tgfree%'
     AND EXISTS (
       SELECT 1 FROM orders o
       WHERE o.tg_id = a.referred_tg_id AND o.status = 'paid'
     )"""


async def _count_active_referred_paid_friends_on(db, referrer_tg_id: int) -> int:
    async with db.execute(_ACTIVE_REFERRED_PAID_SQL, (referrer_tg_id,)) as cur:
        return int((await cur.fetchone())[0])


async def count_active_referred_paid_friends(referrer_tg_id: int) -> int:
    """Приглашённые с paid-заказом и активной подпиской (не trial)."""
    async with get_db() as db:
        return await _count_active_referred_paid_friends_on(db, referrer_tg_id)


def tier_discount_percent(active_referred_count: int) -> int:
    if active_referred_count <= 0:
        return 0
    raw = REFERRAL_TIER_BASE_PERCENT + (active_referred_count - 1) * REFERRAL_TIER_STEP_PERCENT
    return min(raw, REFERRAL_TIER_MAX_PERCENT)


async def get_referrer_tier_discount_percent(tg_id: int) -> int:
    n = await count_active_referred_paid_friends(tg_id)
    return tier_discount_percent(n)


async def insert_reward_log(
    *,
    order_id: int,
    referred_tg_id: int,
    referrer_tg_id: int,
    referrer_bonus_days: int,
    referred_bonus_days: int,
    welcome_applied: bool,
) -> None:
    async with get_db() as db:
        await db.execute(
            """INSERT INTO referral_reward_log
               (order_id, referred_tg_id, referrer_tg_id,
                referrer_bonus_days, referred_bonus_days, welcome_applied)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                order_id,
                referred_tg_id,
                referrer_tg_id,
                referrer_bonus_days,
                referred_bonus_days,
                int(welcome_applied),
            ),
        )
        await db.commit()


async def get_reward_log_by_order(order_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM referral_reward_log WHERE order_id = ?",
            (order_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def delete_reward_log(order_id: int) -> None:
    async with get_db() as db:
        await db.execute("DELETE FROM referral_reward_log WHERE order_id = ?", (order_id,))
        await db.commit()


async def count_referrals(referrer_tg_id: int) -> dict[str, int]:
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM referral_attributions WHERE referrer_tg_id = ?",
            (referrer_tg_id,),
        ) as cur:
            invited = int((await cur.fetchone())[0])
        async with db.execute(
            """SELECT COUNT(DISTINCT a.referred_tg_id)
               FROM referral_attributions a
               WHERE a.referrer_tg_id = ?
                 AND EXISTS (
                   SELECT 1 FROM orders o
                   WHERE o.tg_id = a.referred_tg_id AND o.status = 'paid'
                 )""",
            (referrer_tg_id,),
        ) as cur:
            paid = int((await cur.fetchone())[0])
        active = await _count_active_referred_paid_friends_on(db, referrer_tg_id)
        async with db.execute(
            """SELECT COALESCE(SUM(referrer_bonus_days), 0)
               FROM referral_reward_log WHERE referrer_tg_id = ?""",
            (referrer_tg_id,),
        ) as cur:
            earned_days = int((await cur.fetchone())[0])
    return {
        "invited": invited,
        "paid": paid,
        "active": active,
        "earned_days": earned_days,
    }


async def list_referred_users(referrer_tg_id: int, *, limit: int = 20) -> List[Dict[str, Any]]:
    async with get_db() as db:
        async with db.execute(
            """SELECT a.referred_tg_id, a.created_at,
                      u.username, u.first_name,
                      (SELECT COUNT(*) FROM orders o
                       WHERE o.tg_id = a.referred_tg_id AND o.status = 'paid') AS paid_orders,
                      (SELECT MAX(s.end_date) FROM subscriptions s
                       WHERE s.tg_id = a.referred_tg_id AND s.is_active = 1
                         AND s.client_email NOT LIKE 'tgfree%') AS active_end
               FROM referral_attributions a
               LEFT JOIN users u ON u.tg_id = a.referred_tg_id
               WHERE a.referrer_tg_id = ?
               ORDER BY a.created_at DESC
               LIMIT ?""",
            (referrer_tg_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]