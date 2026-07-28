"""Промокоды и учёт использований."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiosqlite

from db.connection import get_db


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
    async with get_db() as db:
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
        async with db.execute("PRAGMA table_info(promo_uses)") as cur:
            use_cols = {row[1] for row in await cur.fetchall()}
        if "subscription_id" not in use_cols:
            await db.execute(
                "ALTER TABLE promo_uses ADD COLUMN subscription_id INTEGER"
            )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_promo_uses_subscription "
            "ON promo_uses(subscription_id)"
        )
        await db.commit()


def _normalize_code(code: str) -> str:
    return code.strip().upper()


def _row_to_dict(row) -> Dict[str, Any]:
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

    async with get_db() as db:
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
    async with get_db() as db:
        async with db.execute("SELECT * FROM promo_codes WHERE id = ?", (promo_id,)) as cur:
            row = await cur.fetchone()
            return _row_to_dict(row) if row else None


async def get_promo_by_code(code: str) -> Optional[Dict[str, Any]]:
    code = _normalize_code(code)
    async with get_db() as db:
        async with db.execute("SELECT * FROM promo_codes WHERE code = ?", (code,)) as cur:
            row = await cur.fetchone()
            return _row_to_dict(row) if row else None


async def list_promo_codes(*, active_only: bool = False) -> List[Dict[str, Any]]:
    query = "SELECT * FROM promo_codes"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY created_at DESC"
    async with get_db() as db:
        async with db.execute(query) as cur:
            return [_row_to_dict(r) for r in await cur.fetchall()]


async def set_promo_active(promo_id: int, is_active: bool) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE promo_codes SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, promo_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_promo_code(promo_id: int) -> bool:
    async with get_db() as db:
        await db.execute("DELETE FROM promo_uses WHERE promo_id = ?", (promo_id,))
        cursor = await db.execute("DELETE FROM promo_codes WHERE id = ?", (promo_id,))
        await db.commit()
        return cursor.rowcount > 0


async def count_user_promo_uses(promo_id: int, tg_id: int) -> int:
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM promo_uses WHERE promo_id = ? AND tg_id = ?",
            (promo_id, tg_id),
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def has_order_promo_use(order_id: int) -> bool:
    async with get_db() as db:
        async with db.execute(
            "SELECT 1 FROM promo_uses WHERE order_id = ? LIMIT 1",
            (order_id,),
        ) as cur:
            return await cur.fetchone() is not None


async def record_promo_use(promo_id: int, tg_id: int, order_id: int) -> None:
    async with get_db() as db:
        cur = await db.execute(
            """UPDATE promo_codes SET used_count = used_count + 1
               WHERE id = ? AND is_active = 1
                 AND (max_uses IS NULL OR used_count < max_uses)
                 AND NOT EXISTS (SELECT 1 FROM promo_uses WHERE order_id = ?)""",
            (promo_id, order_id),
        )
        if cur.rowcount == 0:
            return
        await db.execute(
            "INSERT INTO promo_uses (promo_id, tg_id, order_id) VALUES (?, ?, ?)",
            (promo_id, tg_id, order_id),
        )
        await db.commit()


async def count_promo_uses() -> int:
    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM promo_uses") as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def reset_all_promo_applications() -> dict[str, int]:
    """Очистить все записи применений промокодов и обнулить счётчики."""
    async with get_db() as db:
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


async def record_grant_promo_use(
    promo_id: int,
    tg_id: int,
    *,
    subscription_id: Optional[int] = None,
) -> None:
    """Учёт grant-промокода. per_user_limit=0 — безлимит (как в _validate_promo_common)."""
    promo = await get_promo_by_id(promo_id)
    if not promo or not promo.get("is_active"):
        raise ValueError("Промокод недоступен (лимит исчерпан)")

    max_uses = promo.get("max_uses")
    if max_uses is not None and (promo.get("used_count") or 0) >= max_uses:
        raise ValueError("Промокод недоступен (лимит исчерпан)")

    per_user = int(promo.get("per_user_limit") or 0)
    if per_user > 0:
        user_uses = await count_user_promo_uses(promo_id, tg_id)
        if user_uses >= per_user:
            raise ValueError("Лимит промокода для вас исчерпан")

    async with get_db() as db:
        cur = await db.execute(
            """UPDATE promo_codes SET used_count = used_count + 1
               WHERE id = ? AND is_active = 1
                 AND (max_uses IS NULL OR used_count < max_uses)""",
            (promo_id,),
        )
        if cur.rowcount == 0:
            raise ValueError("Промокод недоступен (лимит исчерпан)")
        await db.execute(
            """INSERT INTO promo_uses (promo_id, tg_id, order_id, subscription_id)
               VALUES (?, ?, NULL, ?)""",
            (promo_id, tg_id, subscription_id),
        )
        await db.commit()


async def get_grant_uses_for_subscription(
    subscription_id: int,
    *,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Grant-промо, применённые к подписке (новые записи с subscription_id)."""
    async with get_db() as db:
        async with db.execute(
            """SELECT u.id AS use_id, u.tg_id, u.used_at, u.subscription_id,
                      p.id AS promo_id, p.code, p.plan_ids, p.promo_type
               FROM promo_uses u
               JOIN promo_codes p ON p.id = u.promo_id
               WHERE u.subscription_id = ?
                 AND u.order_id IS NULL
                 AND (p.promo_type = 'grant' OR p.discount_type = 'grant')
               ORDER BY u.used_at DESC
               LIMIT ?""",
            (subscription_id, limit),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def find_grant_use_heuristic_for_subscription(
    *,
    tg_id: int,
    subscription_id: int,
    start_date: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Старые grant-записи без subscription_id: ближайший по времени used_at к start_date
    подписки (окно ±2 суток) или последний grant этого пользователя.
    """
    # Сначала точная привязка
    linked = await get_grant_uses_for_subscription(subscription_id, limit=1)
    if linked:
        return linked[0]

    async with get_db() as db:
        async with db.execute(
            """SELECT u.id AS use_id, u.tg_id, u.used_at, u.subscription_id,
                      p.id AS promo_id, p.code, p.plan_ids, p.promo_type
               FROM promo_uses u
               JOIN promo_codes p ON p.id = u.promo_id
               WHERE u.tg_id = ?
                 AND u.order_id IS NULL
                 AND (u.subscription_id IS NULL OR u.subscription_id = ?)
                 AND (p.promo_type = 'grant' OR p.discount_type = 'grant')
               ORDER BY u.used_at DESC
               LIMIT 20""",
            (tg_id, subscription_id),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

    if not rows:
        return None

    # Уже с subscription_id (на всякий)
    for r in rows:
        if r.get("subscription_id") == subscription_id:
            return r

    if not start_date:
        return rows[0]

    try:
        start = datetime.fromisoformat(str(start_date).replace("Z", ""))
    except ValueError:
        return rows[0]

    best = None
    best_delta = None
    for r in rows:
        try:
            used = datetime.fromisoformat(str(r.get("used_at") or "").replace("Z", ""))
        except ValueError:
            continue
        delta = abs((used - start).total_seconds())
        # ±2 суток
        if delta <= 2 * 86400 and (best_delta is None or delta < best_delta):
            best = r
            best_delta = delta
    return best or rows[0]