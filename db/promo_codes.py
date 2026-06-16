"""Промокоды и учёт использований."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiosqlite

from db.database import DB_PATH


async def init_promo_tables():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
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
) -> Dict[str, Any]:
    code = _normalize_code(code)
    if discount_type not in ("percent", "fixed"):
        raise ValueError("Тип скидки: percent или fixed")
    if discount_value <= 0:
        raise ValueError("Размер скидки должен быть > 0")
    if per_user_limit < 0:
        raise ValueError("Лимит на пользователя не может быть отрицательным")
    if discount_type == "percent" and discount_value > 100:
        raise ValueError("Процент скидки не может быть > 100")

    valid_until = None
    if valid_days and valid_days > 0:
        valid_until = (datetime.utcnow() + timedelta(days=valid_days)).isoformat()

    plan_ids_str = ",".join(plan_ids) if plan_ids else ""

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        try:
            cursor = await db.execute(
                """INSERT INTO promo_codes
                   (code, discount_type, discount_value, max_uses, per_user_limit,
                    valid_until, plan_ids, is_active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                (code, discount_type, discount_value, max_uses, per_user_limit,
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