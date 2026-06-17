"""Промокоды и учёт использований."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiosqlite

from db.database import DB_PATH


PROMO_TYPE_DISCOUNT = "discount"
PROMO_TYPE_GRANT = "grant"


def is_grant_promo(promo: Dict[str, Any]) -> bool:
    return (promo.get("promo_type") or PROMO_TYPE_DISCOUNT) == PROMO_TYPE_GRANT


def grant_plan_id(promo: Dict[str, Any]) -> Optional[str]:
    if not is_grant_promo(promo):
        return None
    raw = (promo.get("plan_ids") or "").strip()
    if not raw:
        return None
    return raw.split(",")[0].strip() or None


async def init_promo_tables():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                promo_type TEXT NOT NULL DEFAULT 'discount',
                discount_type TEXT NOT NULL,
                discount_value INTEGER NOT NULL,
                max_uses INTEGER,
                used_count INTEGER DEFAULT 0,
                per_user_limit INTEGER DEFAULT 1,
                valid_until TIMESTAMP,
                plan_ids TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        async with db.execute("PRAGMA table_info(promo_codes)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        if "promo_type" not in cols:
            await db.execute(
                "ALTER TABLE promo_codes ADD COLUMN promo_type TEXT NOT NULL DEFAULT 'discount'"
            )
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                promo_id INTEGER NOT NULL,
                tg_id INTEGER NOT NULL,
                order_id INTEGER,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(promo_id) REFERENCES promo_codes(id)
            )
        """)
        await db.commit()


def _normalize_code(code: str) -> str:
    return code.strip().upper()


def _row_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
    return dict(row)


async def create_promo_code(
    *,
    code: str,
    discount_type: str,
    discount_value: int,
    max_uses: Optional[int] = None,
    per_user_limit: int = 1,
    valid_days: Optional[int] = None,
    plan_ids: Optional[List[str]] = None,
    promo_type: str = PROMO_TYPE_DISCOUNT,
) -> Dict[str, Any]:
    code = _normalize_code(code)
    if promo_type not in (PROMO_TYPE_DISCOUNT, PROMO_TYPE_GRANT):
        raise ValueError("Тип промокода: discount или grant")
    if per_user_limit < 0:
        raise ValueError("Лимит на пользователя не может быть отрицательным")

    if promo_type == PROMO_TYPE_GRANT:
        grant_id = (plan_ids or [None])[0] if plan_ids else None
        if not grant_id:
            raise ValueError("Укажите тариф для бесплатного промокода")
        discount_type = "grant"
        discount_value = 0
        plan_ids_str = grant_id
    else:
        if discount_type not in ("percent", "fixed"):
            raise ValueError("Тип скидки: percent или fixed")
        if discount_value <= 0:
            raise ValueError("Размер скидки должен быть > 0")
        if discount_type == "percent" and discount_value > 100:
            raise ValueError("Процент скидки не может быть > 100")
        plan_ids_str = ",".join(plan_ids) if plan_ids else ""

    valid_until = None
    if valid_days and valid_days > 0:
        valid_until = (datetime.utcnow() + timedelta(days=valid_days)).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        try:
            cursor = await db.execute(
                """INSERT INTO promo_codes
                   (code, promo_type, discount_type, discount_value, max_uses, per_user_limit,
                    valid_until, plan_ids, is_active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (code, promo_type, discount_type, discount_value, max_uses, per_user_limit,
                 valid_until, plan_ids_str),
            )
            await db.commit()
            promo_id = cursor.lastrowid
        except aiosqlite.IntegrityError as e:
            raise ValueError(f"Промокод {code} уже существует") from e

    promo = await get_promo_by_id(promo_id)
    if not promo:
        raise RuntimeError("Не удалось создать промокод")
    return promo


async def get_promo_by_id(promo_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM promo_codes WHERE id = ?", (promo_id,)) as cur:
            row = await cur.fetchone()
            return _row_to_dict(row) if row else None


async def get_promo_by_code(code: str) -> Optional[Dict[str, Any]]:
    code = _normalize_code(code)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM promo_codes WHERE code = ?", (code,)) as cur:
            row = await cur.fetchone()
            return _row_to_dict(row) if row else None


async def list_promo_codes(*, active_only: bool = False) -> List[Dict[str, Any]]:
    query = "SELECT * FROM promo_codes"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY created_at DESC"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query) as cur:
            return [_row_to_dict(r) for r in await cur.fetchall()]


async def set_promo_active(promo_id: int, is_active: bool) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE promo_codes SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, promo_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_promo_code(promo_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM promo_uses WHERE promo_id = ?", (promo_id,))
        cursor = await db.execute("DELETE FROM promo_codes WHERE id = ?", (promo_id,))
        await db.commit()
        return cursor.rowcount > 0


async def count_user_promo_uses(promo_id: int, tg_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM promo_uses WHERE promo_id = ? AND tg_id = ?",
            (promo_id, tg_id),
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def has_order_promo_use(order_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM promo_uses WHERE order_id = ? LIMIT 1",
            (order_id,),
        ) as cur:
            return await cur.fetchone() is not None


async def record_promo_use(promo_id: int, tg_id: int, order_id: int) -> None:
    if await has_order_promo_use(order_id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO promo_uses (promo_id, tg_id, order_id) VALUES (?, ?, ?)",
            (promo_id, tg_id, order_id),
        )
        await db.execute(
            "UPDATE promo_codes SET used_count = used_count + 1 WHERE id = ?",
            (promo_id,),
        )
        await db.commit()


async def count_promo_uses() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM promo_uses") as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def reset_all_promo_applications() -> dict[str, int]:
    """Очистить все записи применений промокодов и обнулить счётчики."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM promo_uses") as cur:
            uses_deleted = int((await cur.fetchone())[0])
        await db.execute("DELETE FROM promo_uses")
        await db.execute("UPDATE promo_codes SET used_count = 0")
        await db.commit()
    from db import promo_pending as pending_db
    pending_deleted = await pending_db.clear_all_pending_discounts()
    return {
        "uses_deleted": uses_deleted,
        "pending_deleted": pending_deleted,
    }


async def record_grant_promo_use(promo_id: int, tg_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO promo_uses (promo_id, tg_id, order_id) VALUES (?, ?, NULL)",
            (promo_id, tg_id),
        )
        await db.execute(
            "UPDATE promo_codes SET used_count = used_count + 1 WHERE id = ?",
            (promo_id,),
        )
        await db.commit()