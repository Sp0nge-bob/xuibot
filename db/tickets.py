"""Тикеты поддержки и возвратов."""
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiosqlite

from db.database import DB_PATH

CATEGORY_REFUND = "refund"
CATEGORY_SUPPORT = "support"
CATEGORY_OTHER = "other"

STATUS_OPEN = "open"
STATUS_CLOSED = "closed"

REFUND_DECISION_APPROVED = "approved"
REFUND_DECISION_REJECTED = "rejected"

_CATEGORY_LABELS = {
    CATEGORY_REFUND: "Возврат",
    CATEGORY_SUPPORT: "Поддержка",
    CATEGORY_OTHER: "Другое",
}


def category_label(category: str) -> str:
    return _CATEGORY_LABELS.get(category, category)


async def init_tickets_tables() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                subscription_id INTEGER,
                order_id INTEGER,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP,
                last_message_at TIMESTAMP,
                admin_last_read_at TIMESTAMP,
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id),
                FOREIGN KEY(order_id) REFERENCES orders(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                sender_tg_id INTEGER NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                content_type TEXT NOT NULL DEFAULT 'text',
                body TEXT,
                file_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(ticket_id) REFERENCES tickets(id)
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tickets_status_cat "
            "ON tickets(status, category, last_message_at DESC)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tickets_tg_open "
            "ON tickets(tg_id, status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tickets_sub "
            "ON tickets(subscription_id, status)"
        )
        await db.commit()
        await _migrate_refund_tables(db)
        await _migrate_refund_decision_column(db)


async def _migrate_refund_decision_column(db: aiosqlite.Connection) -> None:
    async with db.execute("PRAGMA table_info(tickets)") as cur:
        columns = {row[1] for row in await cur.fetchall()}
    if "refund_decision" not in columns:
        await db.execute("ALTER TABLE tickets ADD COLUMN refund_decision TEXT")
        await db.commit()


async def _migrate_refund_tables(db: aiosqlite.Connection) -> None:
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='refund_requests'"
    ) as cur:
        if not await cur.fetchone():
            return
    async with db.execute("SELECT COUNT(*) FROM tickets") as cur:
        if (await cur.fetchone())[0] > 0:
            return
    async with db.execute("SELECT COUNT(*) FROM refund_requests") as cur:
        if (await cur.fetchone())[0] == 0:
            return

    async with db.execute(
        "SELECT id, tg_id, subscription_id, status, created_at FROM refund_requests ORDER BY id"
    ) as cur:
        refunds = await cur.fetchall()

    id_map: dict[int, int] = {}
    for old_id, tg_id, sub_id, status, created_at in refunds:
        new_status = STATUS_OPEN if status == "pending" else STATUS_CLOSED
        closed_at = created_at if new_status == STATUS_CLOSED else None
        cursor = await db.execute(
            """INSERT INTO tickets
               (tg_id, category, subscription_id, status, created_at, closed_at, last_message_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (tg_id, CATEGORY_REFUND, sub_id, new_status, created_at, closed_at, created_at),
        )
        id_map[old_id] = cursor.lastrowid

    async with db.execute(
        """SELECT refund_id, sender_tg_id, is_admin, body, created_at
           FROM refund_messages ORDER BY id"""
    ) as cur:
        messages = await cur.fetchall()

    for refund_id, sender_tg_id, is_admin, body, created_at in messages:
        ticket_id = id_map.get(refund_id)
        if not ticket_id:
            continue
        await db.execute(
            """INSERT INTO ticket_messages
               (ticket_id, sender_tg_id, is_admin, content_type, body, created_at)
               VALUES (?, ?, ?, 'text', ?, ?)""",
            (ticket_id, sender_tg_id, is_admin, body, created_at),
        )
    await db.commit()


def _ticket_select_sql() -> str:
    return """
        SELECT t.id, t.tg_id, t.category, t.subscription_id, t.order_id,
               t.status, t.refund_decision, t.created_at, t.closed_at, t.last_message_at, t.admin_last_read_at,
               u.username, u.first_name,
               s.client_email, s.end_date AS sub_end_date,
               o.plan_name, o.amount AS order_amount, o.platega_tx_id
        FROM tickets t
        LEFT JOIN users u ON u.tg_id = t.tg_id
        LEFT JOIN subscriptions s ON s.id = t.subscription_id
        LEFT JOIN orders o ON o.id = t.order_id
    """


async def create_ticket(
    *,
    tg_id: int,
    category: str,
    subscription_id: int | None = None,
    order_id: int | None = None,
) -> int:
    if category == CATEGORY_REFUND:
        if not subscription_id or not order_id:
            raise ValueError("subscription_id and order_id required for refund")
        existing = await get_open_refund_ticket_for_order(subscription_id, order_id)
        if existing:
            return existing["id"]

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO tickets (tg_id, category, subscription_id, order_id, last_message_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (tg_id, category, subscription_id, order_id),
        )
        await db.commit()
        return cursor.lastrowid


async def get_ticket_by_id(ticket_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            _ticket_select_sql() + " WHERE t.id = ?",
            (ticket_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_open_refund_ticket_for_order(
    subscription_id: int,
    order_id: int,
) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            _ticket_select_sql()
            + """ WHERE t.subscription_id = ? AND t.order_id = ?
                  AND t.category = ? AND t.status = ?
                ORDER BY t.id DESC LIMIT 1""",
            (subscription_id, order_id, CATEGORY_REFUND, STATUS_OPEN),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_open_refund_tickets_for_subscription(
    subscription_id: int,
) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            _ticket_select_sql()
            + """ WHERE t.subscription_id = ? AND t.category = ? AND t.status = ?
                ORDER BY t.id DESC""",
            (subscription_id, CATEGORY_REFUND, STATUS_OPEN),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_open_refund_order_ids_for_subscription(subscription_id: int) -> set[int]:
    tickets = await get_open_refund_tickets_for_subscription(subscription_id)
    return {t["order_id"] for t in tickets if t.get("order_id")}


async def get_open_refund_tickets_by_subscription_for_user(
    tg_id: int,
) -> dict[int, list[Dict[str, Any]]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            _ticket_select_sql()
            + """ WHERE t.tg_id = ? AND t.category = ? AND t.status = ?
                  AND t.subscription_id IS NOT NULL
                ORDER BY t.subscription_id, t.id DESC""",
            (tg_id, CATEGORY_REFUND, STATUS_OPEN),
        ) as cur:
            rows = await cur.fetchall()
    by_sub: dict[int, list[Dict[str, Any]]] = {}
    for row in rows:
        ticket = dict(row)
        by_sub.setdefault(ticket["subscription_id"], []).append(ticket)
    return by_sub


async def get_user_open_tickets(tg_id: int) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            _ticket_select_sql()
            + " WHERE t.tg_id = ? AND t.status = ? ORDER BY t.last_message_at DESC",
            (tg_id, STATUS_OPEN),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_open_tickets(
    *,
    category: str | None = None,
    limit: int = 30,
) -> List[Dict[str, Any]]:
    clause = " WHERE t.status = ?"
    params: list[Any] = [STATUS_OPEN]
    if category:
        clause += " AND t.category = ?"
        params.append(category)
    params.append(limit)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            _ticket_select_sql()
            + clause
            + " ORDER BY t.last_message_at DESC, t.id DESC LIMIT ?",
            tuple(params),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def close_ticket(ticket_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """UPDATE tickets SET status = ?, closed_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status = ?""",
            (STATUS_CLOSED, ticket_id, STATUS_OPEN),
        )
        await db.commit()
        return cursor.rowcount > 0


async def close_refund_ticket(ticket_id: int, decision: str) -> bool:
    if decision not in (REFUND_DECISION_APPROVED, REFUND_DECISION_REJECTED):
        raise ValueError(f"invalid refund decision: {decision}")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """UPDATE tickets SET status = ?, refund_decision = ?,
                      closed_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status = ? AND category = ?""",
            (STATUS_CLOSED, decision, ticket_id, STATUS_OPEN, CATEGORY_REFUND),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_refund_ticket_for_order(order_id: int) -> Optional[Dict[str, Any]]:
    """Последний refund-тикет по заказу (для уведомления при chargeback)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            _ticket_select_sql()
            + """ WHERE t.order_id = ? AND t.category = ?
                ORDER BY t.id DESC LIMIT 1""",
            (order_id, CATEGORY_REFUND),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def cancel_tickets_for_subscription(subscription_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE tickets SET status = ?, closed_at = CURRENT_TIMESTAMP
               WHERE subscription_id = ? AND category = ? AND status = ?""",
            (STATUS_CLOSED, subscription_id, CATEGORY_REFUND, STATUS_OPEN),
        )
        await db.commit()


async def touch_ticket_activity(ticket_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tickets SET last_message_at = CURRENT_TIMESTAMP WHERE id = ?",
            (ticket_id,),
        )
        await db.commit()


async def mark_ticket_read_by_admin(ticket_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tickets SET admin_last_read_at = CURRENT_TIMESTAMP WHERE id = ?",
            (ticket_id,),
        )
        await db.commit()


async def count_unread_for_admin(ticket_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT admin_last_read_at FROM tickets WHERE id = ?",
            (ticket_id,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return 0
        last_read = row[0]
        if last_read:
            async with db.execute(
                """SELECT COUNT(*) FROM ticket_messages
                   WHERE ticket_id = ? AND is_admin = 0 AND created_at > ?""",
                (ticket_id, last_read),
            ) as cur:
                return (await cur.fetchone())[0]
        async with db.execute(
            """SELECT COUNT(*) FROM ticket_messages
               WHERE ticket_id = ? AND is_admin = 0""",
            (ticket_id,),
        ) as cur:
            return (await cur.fetchone())[0]


async def add_ticket_message(
    *,
    ticket_id: int,
    sender_tg_id: int,
    is_admin: bool,
    content_type: str,
    body: str | None = None,
    file_id: str | None = None,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO ticket_messages
               (ticket_id, sender_tg_id, is_admin, content_type, body, file_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ticket_id, sender_tg_id, int(is_admin), content_type, body, file_id),
        )
        await db.execute(
            "UPDATE tickets SET last_message_at = CURRENT_TIMESTAMP WHERE id = ?",
            (ticket_id,),
        )
        await db.commit()
        return cursor.lastrowid


async def get_ticket_messages(ticket_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT id, ticket_id, sender_tg_id, is_admin, content_type, body, file_id, created_at
               FROM ticket_messages WHERE ticket_id = ? ORDER BY id ASC LIMIT ?""",
            (ticket_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_ticket_stats() -> Dict[str, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM tickets WHERE status = ?", (STATUS_OPEN,),
        ) as cur:
            total = (await cur.fetchone())[0]
        stats = {"pending_tickets": total, "pending_refunds": 0, "pending_support": 0, "pending_other": 0}
        for cat, key in (
            (CATEGORY_REFUND, "pending_refunds"),
            (CATEGORY_SUPPORT, "pending_support"),
            (CATEGORY_OTHER, "pending_other"),
        ):
            async with db.execute(
                "SELECT COUNT(*) FROM tickets WHERE status = ? AND category = ?",
                (STATUS_OPEN, cat),
            ) as cur:
                stats[key] = (await cur.fetchone())[0]
        return stats