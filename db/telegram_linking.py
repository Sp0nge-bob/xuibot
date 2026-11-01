"""Atomic fallback for an unambiguous, explicitly authorized account link."""
from utils.utc import utc_now


async def consume_link_token(db, token: str, tg_id: int) -> dict:
    await db.execute("BEGIN IMMEDIATE")
    try:
        async with db.execute(
            "SELECT email, expires_at, used FROM telegram_link_tokens WHERE token = ?", (token,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return {"ok": False, "detail": "Токен привязки не найден."}
        email, expires_at, used = row
        if used:
            return {"ok": False, "detail": "Эта ссылка для привязки уже была использована."}
        now = utc_now().isoformat()
        if expires_at <= now:
            return {"ok": False, "detail": "Срок действия ссылки для привязки истёк."}

        # Missing/invalid authorization tables must fail closed via the caller.
        async with db.execute(
            "SELECT 1 FROM email_blacklist WHERE email = ? "
            "UNION SELECT 1 FROM email_accounts WHERE email = ? AND is_blocked = 1 LIMIT 1",
            (email, email),
        ) as cursor:
            if await cursor.fetchone():
                return {"ok": False, "detail": "Данная почта находится в чёрном списке и не может быть привязана к Telegram."}

        checks = (
            ("SELECT 1 FROM email_accounts WHERE (tg_id = ? AND email <> ?) OR (email = ? AND tg_id IS NOT NULL AND tg_id <> ?) LIMIT 1", (tg_id, email, email, tg_id)),
            ("SELECT 1 FROM users WHERE (tg_id = ? AND email IS NOT NULL AND email <> '' AND email <> ?) OR (email = ? AND tg_id <> ?) LIMIT 1", (tg_id, email, email, tg_id)),
            ("SELECT 1 FROM subscriptions WHERE (email_account = ? AND tg_id IS NOT NULL AND tg_id <> ?) OR (tg_id = ? AND email_account IS NOT NULL AND email_account <> '' AND email_account <> ?) LIMIT 1", (email, tg_id, tg_id, email)),
        )
        for query, params in checks:
            async with db.execute(query, params) as cursor:
                if await cursor.fetchone():
                    return {"ok": False, "detail": "Аккаунт уже привязан. Сначала отвяжите предыдущую почту или Telegram."}

        claim = await db.execute(
            "UPDATE telegram_link_tokens SET used = 1 WHERE token = ? AND used = 0 AND expires_at > ?",
            (token, now),
        )
        if claim.rowcount != 1:
            return {"ok": False, "detail": "Эта ссылка для привязки уже была использована."}
        await db.execute("INSERT OR IGNORE INTO email_accounts (email, tg_id) VALUES (?, ?)", (email, tg_id))
        await db.execute("UPDATE email_accounts SET tg_id = ? WHERE email = ?", (tg_id, email))
        await db.execute("UPDATE users SET email = ? WHERE tg_id = ?", (email, tg_id))
        await db.execute("UPDATE subscriptions SET tg_id = ? WHERE email_account = ?", (tg_id, email))
        await db.execute(
            "UPDATE subscriptions SET email_account = ? WHERE tg_id = ? AND (email_account IS NULL OR email_account = '')",
            (email, tg_id),
        )
        await db.commit()
        return {"ok": True, "email": email, "message": f"Аккаунт успешно привязан к {email}!"}
    finally:
        if db.in_transaction:
            await db.rollback()
