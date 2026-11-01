"""Versioned additive bot/site storage contract; never delete or guess user data.

Keep this module byte-identical in both repositories. Every SQL identifier below
is a developer-owned constant, not request input. Existing duplicate identities
abort this migration atomically and require a protected operator reconciliation.
"""
from __future__ import annotations

USERS_SQL = """CREATE TABLE IF NOT EXISTS users (
 tg_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, full_name TEXT,
 email TEXT, email_verified INTEGER DEFAULT 0,
 email_bonus_granted INTEGER NOT NULL DEFAULT 0,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
ORDERS_SQL = """CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER, plan_id TEXT, plan_name TEXT,
 plan_days INTEGER, amount INTEGER, original_amount INTEGER,
 discount_amount INTEGER DEFAULT 0, promo_code TEXT, platega_tx_id TEXT,
 payment_method TEXT, order_type TEXT DEFAULT 'new', status TEXT DEFAULT 'pending',
 source TEXT DEFAULT 'bot', customer_email TEXT, payment_redirect TEXT,
 subscription_id INTEGER, sub_display_name TEXT, is_dev INTEGER DEFAULT 0,
 paid_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
SUBSCRIPTIONS_SQL = """CREATE TABLE IF NOT EXISTS subscriptions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER, order_id TEXT,
 inbound_id INTEGER, plan_days INTEGER, traffic_gb INTEGER DEFAULT 0,
 traffic_limit_gb INTEGER DEFAULT 0, start_date TIMESTAMP, end_date TIMESTAMP,
 status TEXT DEFAULT 'active', is_active INTEGER DEFAULT 1,
 client_email TEXT, client_uuid TEXT, sub_id TEXT, xui_client_id TEXT, xui_sub_id TEXT,
 sub_link TEXT, display_name TEXT, email_account TEXT, origin TEXT DEFAULT 'bot',
 is_dev INTEGER DEFAULT 0, expiry_reminder_sent_at TIMESTAMP,
 grant_bonus_days INTEGER NOT NULL DEFAULT 0,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
EMAIL_ACCOUNTS_SQL = """CREATE TABLE IF NOT EXISTS email_accounts (
 email TEXT PRIMARY KEY, tg_id INTEGER, user_id INTEGER,
 is_blocked INTEGER DEFAULT 0, block_reason TEXT DEFAULT '', blocked_at TIMESTAMP,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
PAYMENT_INBOX_SQL = """CREATE TABLE IF NOT EXISTS payment_inbox (
 tx_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending', owner TEXT,
 lease_until REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt_at REAL NOT NULL DEFAULT 0, error_code TEXT,
 PRIMARY KEY(tx_id,status))"""
PAYMENT_STATES_SQL = """CREATE TABLE IF NOT EXISTS payment_states (
 tx_id TEXT PRIMARY KEY, financial_state TEXT NOT NULL,
 updated_at REAL NOT NULL DEFAULT 0)"""

_COLUMNS = {
 "users": {"username": "TEXT", "first_name": "TEXT", "full_name": "TEXT", "email": "TEXT",
           "email_verified": "INTEGER DEFAULT 0", "email_bonus_granted": "INTEGER NOT NULL DEFAULT 0"},
 "orders": {"tg_id": "INTEGER", "plan_id": "TEXT", "plan_name": "TEXT", "plan_days": "INTEGER",
            "amount": "INTEGER", "original_amount": "INTEGER", "discount_amount": "INTEGER DEFAULT 0",
            "promo_code": "TEXT", "platega_tx_id": "TEXT", "payment_method": "TEXT",
            "order_type": "TEXT DEFAULT 'new'", "status": "TEXT DEFAULT 'pending'",
            "source": "TEXT DEFAULT 'bot'", "customer_email": "TEXT", "payment_redirect": "TEXT",
            "subscription_id": "INTEGER", "sub_display_name": "TEXT", "is_dev": "INTEGER DEFAULT 0",
            "paid_at": "TIMESTAMP"},
 "subscriptions": {"tg_id": "INTEGER", "order_id": "INTEGER", "inbound_id": "INTEGER",
            "plan_days": "INTEGER", "traffic_gb": "INTEGER DEFAULT 0", "traffic_limit_gb": "INTEGER DEFAULT 0",
            "start_date": "TIMESTAMP", "end_date": "TIMESTAMP", "status": "TEXT DEFAULT 'active'",
            "is_active": "INTEGER DEFAULT 1", "client_email": "TEXT", "client_uuid": "TEXT", "sub_id": "TEXT",
            "xui_client_id": "TEXT", "xui_sub_id": "TEXT", "sub_link": "TEXT", "display_name": "TEXT",
            "email_account": "TEXT", "origin": "TEXT DEFAULT 'bot'", "is_dev": "INTEGER DEFAULT 0",
            "expiry_reminder_sent_at": "TIMESTAMP", "grant_bonus_days": "INTEGER NOT NULL DEFAULT 0"},
 "email_accounts": {"tg_id": "INTEGER", "user_id": "INTEGER", "is_blocked": "INTEGER DEFAULT 0",
                    "block_reason": "TEXT DEFAULT ''", "blocked_at": "TIMESTAMP"},
}


class SharedSchemaConflict(RuntimeError):
    """Non-destructive startup failure; does not expose personal identifiers."""


async def _columns(db, table: str) -> set[str]:
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        return {row[1] for row in await cur.fetchall()}


async def ensure_shared_schema(db, *, include_auth: bool = False) -> None:
    owns_transaction = not db.in_transaction
    if owns_transaction:
        # Serialize concurrent service startup before any schema read/upgrade.
        await db.execute("BEGIN IMMEDIATE")
    await db.execute("SAVEPOINT shared_contract_v1")
    try:
        for ddl in (USERS_SQL, ORDERS_SQL, SUBSCRIPTIONS_SQL, EMAIL_ACCOUNTS_SQL):
            await db.execute(ddl)
        needs_bonus_history = "email_bonus_granted" not in await _columns(db, "users")
        for table, declarations in _COLUMNS.items():
            existing = await _columns(db, table)
            for column, declaration in declarations.items():
                if column not in existing:
                    await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
            if "created_at" not in existing:
                # SQLite cannot add CURRENT_TIMESTAMP as a nonconstant default.
                # Do not fabricate historical creation times on old databases.
                await db.execute(f"ALTER TABLE {table} ADD COLUMN created_at TIMESTAMP")
        if needs_bonus_history:
            # Preserve the existing bot migration's one-time benefit history.
            await db.execute("UPDATE users SET email_bonus_granted = 1 WHERE email IS NOT NULL AND TRIM(email) != ''")
            await db.execute("UPDATE users SET email_bonus_granted = 1 WHERE tg_id IN "
                             "(SELECT tg_id FROM email_accounts WHERE tg_id IS NOT NULL AND tg_id > 0)")
        for table, column, index in (
            ("orders", "platega_tx_id", "uq_shared_orders_transaction"),
            ("email_accounts", "tg_id", "uq_shared_email_telegram"),
            ("email_accounts", "user_id", "uq_shared_email_user_id"),
            ("users", "email", "uq_shared_users_email"),
        ):
            async with db.execute(f"SELECT COUNT(*) FROM (SELECT {column} FROM {table} "
                                  f"WHERE {column} IS NOT NULL GROUP BY {column} HAVING COUNT(*) > 1)") as cur:
                count = (await cur.fetchone())[0]
            if count:
                raise SharedSchemaConflict(f"Duplicate groups in {table}.{column}: {count}; reconcile an authorized backup before upgrade")
            await db.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {index} ON {table}({column}) WHERE {column} IS NOT NULL")
        await db.execute(PAYMENT_INBOX_SQL)
        await db.execute(PAYMENT_STATES_SQL)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_payment_inbox_due ON payment_inbox(state,next_attempt_at,lease_until)")
        if include_auth:
            await db.execute("""CREATE TABLE IF NOT EXISTS otp_codes (
             id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, code_hash TEXT NOT NULL,
             magic_hash TEXT, expires_at TIMESTAMP NOT NULL, used INTEGER DEFAULT 0,
             attempts INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            existing = await _columns(db, "otp_codes")
            for column, declaration in {"purpose": "TEXT NOT NULL DEFAULT 'legacy'", "subject": "TEXT", "target": "TEXT"}.items():
                if column not in existing:
                    await db.execute(f"ALTER TABLE otp_codes ADD COLUMN {column} {declaration}")
            await db.execute("UPDATE otp_codes SET used = 2 WHERE used = 0 AND (purpose = 'legacy' OR purpose IS NULL)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_otp_context ON otp_codes(email,purpose,subject,target,used)")
        await db.execute("RELEASE SAVEPOINT shared_contract_v1")
        if owns_transaction:
            await db.commit()
    except BaseException:
        await db.execute("ROLLBACK TO SAVEPOINT shared_contract_v1")
        await db.execute("RELEASE SAVEPOINT shared_contract_v1")
        if owns_transaction:
            await db.rollback()
        raise
