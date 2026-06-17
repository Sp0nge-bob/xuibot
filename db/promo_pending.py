"""Ожидающие применения скидочные промокоды (после ввода в главном меню)."""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import aiosqlite

from db.database import DB_PATH

PENDING_DISCOUNT_DAYS = 7


async def init_promo_pending_tables() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_pending_discounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                promo_id INTEGER NOT NULL,
                promo_code TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                consumed_order_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_promo_pending_tg "
            "ON promo_pending_discounts(tg_id, consumed_order_id, expires_at)"
        )
        await db.commit()


async def set_pending_discount(
    tg_id: int,
    promo: Dict[str, Any],
    *,
    days: int = PENDING_DISCOUNT_DAYS,
) -> Dict[str, Any]:
    expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "DELETE FROM promo_pending_discounts WHERE tg_id = ? AND consumed_order_id IS NULL",
            (tg_id,),
        )
        await db.execute(
            """INSERT INTO promo_pending_discounts
               (tg_id, promo_id, promo_code, expires_at)
               VALUES (?, ?, ?, ?)""",
            (tg_id, promo["id"], promo["code"], expires_at),
        )
        await db.commit()
        async with db.execute(
            """SELECT * FROM promo_pending_discounts
               WHERE tg_id = ? AND consumed_order_id IS NULL
               ORDER BY id DESC LIMIT 1""",
            (tg_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else {}


async def get_active_pending_discount(tg_id: int) -> Optional[Dict[str, Any]]:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM promo_pending_discounts
               WHERE tg_id = ? AND consumed_order_id IS NULL AND expires_at > ?
               ORDER BY id DESC LIMIT 1""",
            (tg_id, now),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def consume_pending_discount(
    tg_id: int,
    order_id: int,
    promo_code: str,
) -> bool:
    code = promo_code.strip().upper()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """UPDATE promo_pending_discounts
               SET consumed_order_id = ?
               WHERE tg_id = ? AND consumed_order_id IS NULL
                 AND UPPER(promo_code) = ? AND expires_at > ?""",
            (order_id, tg_id, code, datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cursor.rowcount > 0