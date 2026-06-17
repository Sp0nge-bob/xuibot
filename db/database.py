import aiosqlite
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from loguru import logger

DB_PATH = os.getenv("DB_PATH", "data/bot.db")

os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)


async def _apply_pragmas(db: aiosqlite.Connection) -> None:
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA foreign_keys=ON")


async def _create_indexes(db: aiosqlite.Connection) -> None:
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_subscriptions_tg_active "
        "ON subscriptions(tg_id, is_active)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_subscriptions_active_end "
        "ON subscriptions(is_active, end_date DESC)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_tg_status ON orders(tg_id, status)"
    )


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await _apply_pragmas(db)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER,
                plan_id TEXT,
                plan_name TEXT,
                amount INTEGER,
                platega_tx_id TEXT UNIQUE,
                payment_method TEXT,
                order_type TEXT DEFAULT 'new',
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                paid_at TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS refund_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER,
                subscription_id INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS refund_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                refund_id INTEGER NOT NULL,
                sender_tg_id INTEGER NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                body TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(refund_id) REFERENCES refund_requests(id)
            )
        """)
        # Миграции для существующих БД
        async with db.execute("PRAGMA table_info(orders)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        if "payment_method" not in cols:
            await db.execute("ALTER TABLE orders ADD COLUMN payment_method TEXT")
        if "order_type" not in cols:
            await db.execute("ALTER TABLE orders ADD COLUMN order_type TEXT DEFAULT 'new'")
        if "promo_code" not in cols:
            await db.execute("ALTER TABLE orders ADD COLUMN promo_code TEXT")
        if "original_amount" not in cols:
            await db.execute("ALTER TABLE orders ADD COLUMN original_amount INTEGER")
        if "discount_amount" not in cols:
            await db.execute("ALTER TABLE orders ADD COLUMN discount_amount INTEGER DEFAULT 0")
        if "payment_redirect" not in cols:
            await db.execute("ALTER TABLE orders ADD COLUMN payment_redirect TEXT")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER,
                order_id INTEGER,
                inbound_id INTEGER,
                client_email TEXT,
                client_uuid TEXT,
                sub_id TEXT,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                traffic_limit_gb INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                FOREIGN KEY(order_id) REFERENCES orders(id)
            )
        """)
        await _create_indexes(db)
        await db.commit()

    from db.bot_settings import init_bot_settings
    from db.promo_codes import init_promo_tables
    from db.promo_pending import init_promo_pending_tables
    from db.trial_grants import init_trial_tables
    from db.xui_nodes import init_xui_nodes
    await init_bot_settings()
    await init_promo_tables()
    await init_promo_pending_tables()
    await init_trial_tables()
    await init_xui_nodes()
    logger.info("Database initialized at {}", DB_PATH)

async def get_or_create_user(tg_id: int, username: Optional[str] = None, first_name: Optional[str] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)) as cur:
            row = await cur.fetchone()
        if row:
            return dict(row)
        await db.execute(
            "INSERT INTO users (tg_id, username, first_name) VALUES (?, ?, ?)",
            (tg_id, username, first_name)
        )
        await db.commit()
        return {"tg_id": tg_id, "username": username, "first_name": first_name}

async def create_order(
    tg_id: int,
    plan_id: str,
    plan_name: str,
    amount: int,
    platega_tx_id: str,
    payment_method: Optional[str] = None,
    order_type: str = "new",
    *,
    promo_code: Optional[str] = None,
    original_amount: Optional[int] = None,
    discount_amount: int = 0,
    payment_redirect: Optional[str] = None,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO orders
               (tg_id, plan_id, plan_name, amount, platega_tx_id, payment_method, order_type,
                promo_code, original_amount, discount_amount, payment_redirect, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (tg_id, plan_id, plan_name, amount, platega_tx_id, payment_method, order_type,
             promo_code, original_amount or amount, discount_amount, payment_redirect)
        )
        await db.commit()
        return cursor.lastrowid

async def update_order_status(platega_tx_id: str, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await _apply_pragmas(db)
        await db.execute(
            "UPDATE orders SET status = ?, paid_at = ? WHERE platega_tx_id = ?",
            (status, datetime.utcnow().isoformat() if status == "paid" else None, platega_tx_id)
        )
        await db.commit()


async def mark_order_paid_if_pending(platega_tx_id: str) -> bool:
    """Атомарно pending → paid. False если уже paid или не pending."""
    async with aiosqlite.connect(DB_PATH) as db:
        await _apply_pragmas(db)
        cur = await db.execute(
            """UPDATE orders SET status = 'paid', paid_at = ?
               WHERE platega_tx_id = ? AND status = 'pending'""",
            (datetime.utcnow().isoformat(), platega_tx_id),
        )
        await db.commit()
        return cur.rowcount > 0

async def get_order_by_platega_tx(tx_id: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM orders WHERE platega_tx_id = ?", (tx_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def create_subscription(
    tg_id: int,
    order_id: Optional[int],
    inbound_id: int,
    client_email: str,
    client_uuid: str,
    sub_id: Optional[str],
    days: int,
    traffic_gb: int,
) -> int:
    now = datetime.utcnow()
    end = now + timedelta(days=days)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO subscriptions 
               (tg_id, order_id, inbound_id, client_email, client_uuid, sub_id, 
                start_date, end_date, traffic_limit_gb, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (tg_id, order_id, inbound_id, client_email, client_uuid, sub_id,
             now.isoformat(), end.isoformat(), traffic_gb)
        )
        await db.commit()
        return cursor.lastrowid

async def get_primary_subscription(tg_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        await _apply_pragmas(db)
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM subscriptions
               WHERE tg_id = ? AND is_active = 1
               ORDER BY CASE WHEN client_email LIKE 'tgfree%' THEN 1 ELSE 0 END,
                        end_date DESC
               LIMIT 1""",
            (tg_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_primary_paid_subscription(tg_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        await _apply_pragmas(db)
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM subscriptions
               WHERE tg_id = ? AND is_active = 1
                 AND client_email NOT LIKE 'tgfree%'
               ORDER BY end_date DESC
               LIMIT 1""",
            (tg_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_subscription_by_id(sub_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def extend_subscription_record(subscription_id: int, additional_days: int) -> str:
    sub = await get_subscription_by_id(subscription_id)
    if not sub:
        raise ValueError("Подписка не найдена")
    current_end = datetime.fromisoformat(sub["end_date"])
    now = datetime.utcnow()
    base = current_end if current_end > now else now
    new_end = base + timedelta(days=additional_days)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE subscriptions SET end_date = ?, is_active = 1 WHERE id = ?",
            (new_end.isoformat(), subscription_id),
        )
        await db.commit()
    return new_end.isoformat()


async def get_pending_order(tg_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM orders
               WHERE tg_id = ? AND status = 'pending'
               ORDER BY id DESC LIMIT 1""",
            (tg_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def create_refund_request(tg_id: int, subscription_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT id FROM refund_requests
               WHERE tg_id = ? AND subscription_id = ? AND status = 'pending'""",
            (tg_id, subscription_id),
        ) as cur:
            existing = await cur.fetchone()
        if existing:
            return existing[0]
        cursor = await db.execute(
            "INSERT INTO refund_requests (tg_id, subscription_id) VALUES (?, ?)",
            (tg_id, subscription_id),
        )
        await db.commit()
        return cursor.lastrowid


async def get_active_subscriptions(tg_id: int) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM subscriptions
               WHERE tg_id = ? AND is_active = 1
               ORDER BY CASE WHEN client_email LIKE 'tgfree%' THEN 1 ELSE 0 END,
                        end_date DESC""",
            (tg_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

_SYNC_SUB_COLS = (
    "id, tg_id, order_id, client_email, client_uuid, sub_id, "
    "start_date, end_date, traffic_limit_gb, is_active"
)


async def get_all_active_subscriptions() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        await _apply_pragmas(db)
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT {_SYNC_SUB_COLS} FROM subscriptions "
            "WHERE is_active = 1 ORDER BY end_date DESC"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def count_active_trial_subscriptions() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await _apply_pragmas(db)
        async with db.execute(
            """SELECT COUNT(*) FROM subscriptions
               WHERE is_active = 1 AND client_email LIKE 'tgfree%'"""
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def get_expired_subscriptions() -> List[Dict[str, Any]]:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM subscriptions WHERE is_active = 1 AND end_date < ?",
            (now,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def deactivate_subscription(sub_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE subscriptions SET is_active = 0 WHERE id = ?", (sub_id,))
        await db.commit()


async def get_admin_stats() -> Dict[str, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            users = (await cur.fetchone())[0]
        async with db.execute(
            """SELECT COUNT(*) FROM subscriptions
               WHERE is_active = 1 AND client_email NOT LIKE 'tgfree%'""",
        ) as cur:
            paid_subs = (await cur.fetchone())[0]
        async with db.execute(
            """SELECT COUNT(*) FROM subscriptions
               WHERE is_active = 1 AND client_email LIKE 'tgfree%'""",
        ) as cur:
            trial_subs = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM orders WHERE status = 'paid'") as cur:
            paid_orders = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM refund_requests WHERE status = 'pending'") as cur:
            pending_refunds = (await cur.fetchone())[0]
    return {
        "users": users,
        "paid_subs": paid_subs,
        "trial_subs": trial_subs,
        "paid_orders": paid_orders,
        "pending_refunds": pending_refunds,
    }


async def search_connected_users(query: str, limit: int = 25) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    if q.startswith("@"):
        q = q[1:]

    base_sql = """
        SELECT s.id AS subscription_id, u.tg_id, u.username, u.first_name,
               s.end_date, s.client_email, s.sub_id
        FROM subscriptions s
        JOIN users u ON u.tg_id = s.tg_id
        WHERE s.is_active = 1
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if q.isdigit():
            from config.trial import trial_client_email
            tg_id = int(q)
            sql = base_sql + (
                " AND (u.tg_id = ? OR s.client_email = ? OR s.client_email = ?)"
                " ORDER BY s.end_date DESC LIMIT ?"
            )
            params: tuple = (tg_id, f"tg{tg_id}", trial_client_email(tg_id), limit)
        else:
            pattern = f"%{q}%"
            sql = base_sql + """
                AND (
                    LOWER(COALESCE(u.username, '')) LIKE LOWER(?)
                    OR LOWER(COALESCE(u.first_name, '')) LIKE LOWER(?)
                    OR LOWER(s.client_email) LIKE LOWER(?)
                )
                ORDER BY s.end_date DESC LIMIT ?
            """
            params = (pattern, pattern, pattern, limit)
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


def _connected_users_trial_clause(trial_only: Optional[bool]) -> str:
    if trial_only is True:
        return " AND s.client_email LIKE 'tgfree%'"
    if trial_only is False:
        return " AND s.client_email NOT LIKE 'tgfree%'"
    return ""


async def count_connected_users(*, trial_only: Optional[bool] = None) -> int:
    clause = _connected_users_trial_clause(trial_only)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"""SELECT COUNT(*) FROM subscriptions s
                WHERE s.is_active = 1{clause}""",
        ) as cur:
            return (await cur.fetchone())[0]


async def get_connected_users(
    limit: int = 30,
    *,
    trial_only: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    clause = _connected_users_trial_clause(trial_only)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""SELECT s.id AS subscription_id, u.tg_id, u.username, u.first_name,
                      s.end_date, s.client_email, s.sub_id
               FROM subscriptions s
               JOIN users u ON u.tg_id = s.tg_id
               WHERE s.is_active = 1{clause}
               ORDER BY s.end_date DESC
               LIMIT ?""",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def cancel_refund_requests_for_subscription(subscription_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE refund_requests SET status = 'cancelled' WHERE subscription_id = ? AND status = 'pending'",
            (subscription_id,),
        )
        await db.commit()


async def get_refund_request_by_id(refund_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT r.id, r.tg_id, r.subscription_id, r.status, r.created_at,
                      s.client_email, s.end_date, u.username, u.first_name
               FROM refund_requests r
               JOIN subscriptions s ON s.id = r.subscription_id
               LEFT JOIN users u ON u.tg_id = r.tg_id
               WHERE r.id = ?""",
            (refund_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def close_refund_request(refund_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE refund_requests SET status = 'closed' WHERE id = ? AND status = 'pending'",
            (refund_id,),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_pending_refund_for_user(tg_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT r.id, r.tg_id, r.subscription_id, r.status, r.created_at,
                      s.client_email, s.end_date
               FROM refund_requests r
               JOIN subscriptions s ON s.id = r.subscription_id
               WHERE r.tg_id = ? AND r.status = 'pending'
               ORDER BY r.id DESC LIMIT 1""",
            (tg_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def add_refund_message(
    *,
    refund_id: int,
    sender_tg_id: int,
    is_admin: bool,
    body: str,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO refund_messages (refund_id, sender_tg_id, is_admin, body)
               VALUES (?, ?, ?, ?)""",
            (refund_id, sender_tg_id, int(is_admin), body),
        )
        await db.commit()
        return cursor.lastrowid


async def get_refund_message_by_id(message_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM refund_messages WHERE id = ?", (message_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_refund_messages(refund_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT id, refund_id, sender_tg_id, is_admin, body, created_at
               FROM refund_messages
               WHERE refund_id = ?
               ORDER BY id ASC LIMIT ?""",
            (refund_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_pending_refunds(limit: int = 20) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT r.id, r.tg_id, r.created_at, s.client_email, s.end_date,
                      u.username, u.first_name
               FROM refund_requests r
               JOIN subscriptions s ON s.id = r.subscription_id
               LEFT JOIN users u ON u.tg_id = r.tg_id
               WHERE r.status = 'pending'
               ORDER BY r.id DESC LIMIT ?""",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def update_subscription_from_panel(
    subscription_id: int,
    *,
    end_date: str,
    sub_id: Optional[str] = None,
    is_active: bool = True,
    traffic_limit_gb: Optional[int] = None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        if sub_id and traffic_limit_gb is not None:
            await db.execute(
                """UPDATE subscriptions
                   SET end_date = ?, sub_id = ?, client_uuid = ?, is_active = ?,
                       traffic_limit_gb = ?
                   WHERE id = ?""",
                (end_date, sub_id, sub_id, int(is_active), traffic_limit_gb, subscription_id),
            )
        elif sub_id:
            await db.execute(
                """UPDATE subscriptions
                   SET end_date = ?, sub_id = ?, client_uuid = ?, is_active = ?
                   WHERE id = ?""",
                (end_date, sub_id, sub_id, int(is_active), subscription_id),
            )
        elif traffic_limit_gb is not None:
            await db.execute(
                """UPDATE subscriptions
                   SET end_date = ?, is_active = ?, traffic_limit_gb = ?
                   WHERE id = ?""",
                (end_date, int(is_active), traffic_limit_gb, subscription_id),
            )
        else:
            await db.execute(
                "UPDATE subscriptions SET end_date = ?, is_active = ? WHERE id = ?",
                (end_date, int(is_active), subscription_id),
            )
        await db.commit()
