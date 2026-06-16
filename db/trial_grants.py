"""Учёт выдачи пробных подписок (лимит 1 раз в 90 дней на TG-аккаунт)."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiosqlite

from config.trial import TRIAL_COOLDOWN_DAYS, is_trial_email
from db.database import DB_PATH

_INIT_DONE = False


async def init_trial_tables() -> None:
    global _INIT_DONE
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS trial_grants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                subscription_id INTEGER,
                granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id)
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_trial_grants_tg_id ON trial_grants(tg_id)"
        )
        await db.commit()
    _INIT_DONE = True


async def _ensure_init() -> None:
    if not _INIT_DONE:
        await init_trial_tables()


async def get_last_trial_grant(tg_id: int) -> Optional[Dict[str, Any]]:
    await _ensure_init()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM trial_grants
               WHERE tg_id = ?
               ORDER BY granted_at DESC LIMIT 1""",
            (tg_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def has_recent_trial_grant(tg_id: int, *, days: int = TRIAL_COOLDOWN_DAYS) -> bool:
    grant = await get_last_trial_grant(tg_id)
    if not grant:
        return False
    granted_at = datetime.fromisoformat(str(grant["granted_at"]).replace("Z", ""))
    return granted_at >= datetime.utcnow() - timedelta(days=days)


async def record_trial_grant(tg_id: int, subscription_id: int) -> int:
    await _ensure_init()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO trial_grants (tg_id, subscription_id) VALUES (?, ?)",
            (tg_id, subscription_id),
        )
        await db.commit()
        return cursor.lastrowid


async def can_claim_trial(tg_id: int) -> tuple[bool, str]:
    """Возвращает (доступно, причина отказа)."""
    await _ensure_init()
    from db import database as db

    if await has_recent_trial_grant(tg_id):
        grant = await get_last_trial_grant(tg_id)
        granted_at = datetime.fromisoformat(str(grant["granted_at"]).replace("Z", ""))
        next_at = granted_at + timedelta(days=TRIAL_COOLDOWN_DAYS)
        return False, f"Пробный период уже использован. Снова доступен с {next_at.strftime('%d.%m.%Y')}."

    subs = await db.get_active_subscriptions(tg_id)
    for sub in subs:
        if is_trial_email(sub.get("client_email")):
            return False, "У вас уже активен пробный период."
    for sub in subs:
        if not is_trial_email(sub.get("client_email")):
            return False, "У вас уже есть активная подписка."

    return True, ""


async def reset_trial_eligibility(tg_id: int) -> int:
    """Удаляет записи о выдаче пробного — пользователь сможет взять снова."""
    await _ensure_init()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM trial_grants WHERE tg_id = ?", (tg_id,))
        await db.commit()
        return cursor.rowcount


async def list_recent_trial_grants(limit: int = 15) -> List[Dict[str, Any]]:
    await _ensure_init()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT g.id, g.tg_id, g.granted_at, g.subscription_id,
                      u.username, u.first_name
               FROM trial_grants g
               LEFT JOIN users u ON u.tg_id = g.tg_id
               ORDER BY g.granted_at DESC
               LIMIT ?""",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]