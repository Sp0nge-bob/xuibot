from __future__ import annotations

import httpx
from loguru import logger
from config.settings import settings

_cached_working_base_url: str | None = None


def get_candidate_base_urls() -> list[str]:
    """
    Возвращает список адресов сайта для проверки.
    Сайт может работать на порту 8090 (стандартный для VPS) или 8080.
    """
    urls: list[str] = []
    global _cached_working_base_url
    if _cached_working_base_url and _cached_working_base_url not in urls:
        urls.append(_cached_working_base_url)

    cfg_url = (getattr(settings, "WEBSITE_API_URL", None) or "").strip().rstrip("/")
    if cfg_url and cfg_url not in urls:
        urls.append(cfg_url)

    defaults = [
        "http://127.0.0.1:8090",
        "http://127.0.0.1:8080",
        "http://localhost:8090",
        "http://localhost:8080",
    ]
    for d in defaults:
        if d not in urls:
            urls.append(d)
    return urls


def get_website_base_url() -> str:
    candidates = get_candidate_base_urls()
    return candidates[0] if candidates else "http://127.0.0.1:8090"


def _get_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    secret = getattr(settings, "SECRET_KEY", None)
    if secret:
        headers["X-Bot-Secret"] = secret
    elif getattr(settings, "BOT_TOKEN", None):
        headers["X-Bot-Secret"] = settings.BOT_TOKEN
    return headers


async def request_otp_email(tg_id: int, email: str) -> dict:
    """
    Отправляет запрос к сайту на генерацию и отправку OTP-кода через почтовый транспорт (SMTP/Resend).
    Опрашивает доступные кандидаты адреса сайта (порт 8090, 8080).
    """
    global _cached_working_base_url
    headers = _get_headers()
    payload = {"email": email, "tg_id": tg_id}
    last_error_detail = "Сервис отправки почты временно недоступен. Попробуйте чуть позже."

    for base_url in get_candidate_base_urls():
        url = f"{base_url}/api/auth/bot-send-otp"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    _cached_working_base_url = base_url
                    data = resp.json()
                    return {"ok": True, "message": data.get("message", "Код отправлен")}
                elif resp.status_code == 429:
                    _cached_working_base_url = base_url
                    try:
                        data = resp.json()
                        detail = data.get("detail", "Слишком много запросов. Подождите немного.")
                    except Exception:
                        detail = "Слишком много запросов. Пожалуйста, подождите."
                    return {"ok": False, "detail": detail}
                elif resp.status_code in (400, 403):
                    try:
                        data = resp.json()
                        if "detail" in data:
                            _cached_working_base_url = base_url
                            return {"ok": False, "detail": data["detail"]}
                    except Exception:
                        pass
                    last_error_detail = "Некорректный адрес или доступ ограничен."
                elif resp.status_code == 401:
                    # Порт занят другим сервисом (например, 3x-ui без авторизации), проверяем следующий порт
                    logger.debug("Candidate {} returned 401 (not website API), trying next...", base_url)
                    continue
                else:
                    logger.debug("Candidate {} returned HTTP {}, trying next...", base_url, resp.status_code)
                    continue
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.debug("Candidate {} unreachable ({}): trying next...", base_url, e)
            continue
        except Exception as e:
            logger.debug("Error connecting to candidate {}: {}", base_url, e)
            continue

    logger.error("All website send-otp endpoints failed. Last detail: {}", last_error_detail)
    return {"ok": False, "detail": last_error_detail}


async def verify_otp_email(tg_id: int, email: str, code: str) -> dict:
    """
    Отправляет введённый код на проверку в API сайта для подтверждения и привязки аккаунта.
    """
    global _cached_working_base_url
    headers = _get_headers()
    payload = {"email": email, "code": code, "tg_id": tg_id}
    last_error_detail = "Сервис проверки временно недоступен. Попробуйте позже."

    for base_url in get_candidate_base_urls():
        url = f"{base_url}/api/auth/bot-verify-otp"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    _cached_working_base_url = base_url
                    data = resp.json()
                    return {"ok": True, "message": data.get("message", "Почта успешно привязана!")}
                elif resp.status_code in (400, 403, 429):
                    try:
                        data = resp.json()
                        if "detail" in data:
                            _cached_working_base_url = base_url
                            return {"ok": False, "detail": data["detail"]}
                    except Exception:
                        pass
                    return {"ok": False, "detail": "Неверный код подтверждения"}
                elif resp.status_code == 401:
                    logger.debug("Candidate {} returned 401 on verify, checking next...", base_url)
                    continue
                else:
                    logger.debug("Candidate {} returned HTTP {}, checking next...", base_url, resp.status_code)
                    continue
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.debug("Candidate {} unreachable ({}): trying next...", base_url, e)
            continue
        except Exception as e:
            logger.debug("Error connecting to candidate {}: {}", base_url, e)
            continue

    logger.error("Website verify-otp API failed across all endpoints")
    return {"ok": False, "detail": last_error_detail}


async def unlink_email_account(tg_id: int) -> dict:
    """
    Отвязывает почту от аккаунта Telegram.
    Сначала пытается через API сайта (чтобы сайт уведомил и переименовал подписки),
    при недоступности или любой ошибке выполняет надёжный fallback прямо в общей SQLite БД.
    """
    global _cached_working_base_url
    headers = _get_headers()
    payload = {"tg_id": tg_id}

    for base_url in get_candidate_base_urls():
        url = f"{base_url}/api/auth/bot-unlink-email"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    _cached_working_base_url = base_url
                    return {"ok": True, "message": "Почта успешно отвязана"}
        except Exception:
            continue

    logger.debug("Website unlink-email API unavailable, falling back to direct DB...")

    # Fallback to direct DB in case website is not running
    try:
        from db.connection import get_db
        async with get_db() as db:
            # Находим связанный email
            async with db.execute("SELECT email FROM email_accounts WHERE tg_id = ?", (tg_id,)) as cur:
                erow = await cur.fetchone()
            email = erow[0] if erow and erow[0] else None
            if not email:
                async with db.execute("SELECT email FROM users WHERE tg_id = ?", (tg_id,)) as cur:
                    urow = await cur.fetchone()
                email = urow[0] if urow and urow[0] else None

            # 1. Web-подписки: отвязываем от Telegram (tg_id = NULL), доступ в боте пропадает
            if email:
                await db.execute("""
                    UPDATE subscriptions
                    SET tg_id = NULL
                    WHERE (tg_id = ? OR email_account = ?)
                      AND (
                          origin = 'web'
                          OR display_name LIKE 'Web%'
                          OR client_email LIKE 'web%'
                          OR order_id IN (SELECT id FROM orders WHERE source = 'web')
                      )
                """, (tg_id, email))
            else:
                await db.execute("""
                    UPDATE subscriptions
                    SET tg_id = NULL
                    WHERE tg_id = ?
                      AND (
                          origin = 'web'
                          OR display_name LIKE 'Web%'
                          OR client_email LIKE 'web%'
                          OR order_id IN (SELECT id FROM orders WHERE source = 'web')
                      )
                """, (tg_id,))

            # 2. Telegram-подписки: отвязываем от сайта (email_account = NULL), доступ на сайте пропадает
            if email:
                await db.execute("""
                    UPDATE subscriptions
                    SET email_account = NULL
                    WHERE (tg_id = ? OR email_account = ?)
                      AND (
                          origin = 'bot'
                          OR (
                              origin != 'web'
                              AND display_name NOT LIKE 'Web%'
                              AND client_email NOT LIKE 'web%'
                              AND order_id NOT IN (SELECT id FROM orders WHERE source = 'web')
                          )
                      )
                """, (tg_id, email))
            else:
                await db.execute("""
                    UPDATE subscriptions
                    SET email_account = NULL
                    WHERE tg_id = ?
                      AND (
                          origin = 'bot'
                          OR (
                              origin != 'web'
                              AND display_name NOT LIKE 'Web%'
                              AND client_email NOT LIKE 'web%'
                              AND order_id NOT IN (SELECT id FROM orders WHERE source = 'web')
                          )
                      )
                """, (tg_id,))

            # 3. Разрываем связь
            if email:
                await db.execute("UPDATE email_accounts SET tg_id = NULL WHERE tg_id = ? OR email = ?", (tg_id, email))
            else:
                await db.execute("UPDATE email_accounts SET tg_id = NULL WHERE tg_id = ?", (tg_id,))
            await db.execute("UPDATE users SET email = NULL WHERE tg_id = ?", (tg_id,))
            await db.commit()
        return {"ok": True, "message": "Почта успешно отвязана"}
    except Exception as dbe:
        logger.error("Failed to unlink email in DB: {}", dbe)
        return {"ok": False, "detail": f"Ошибка отвязки: {dbe}"}


async def link_telegram_token(
    token: str,
    tg_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> dict:
    """
    Отправляет токен привязки на сайт через внутренний API.
    Сайт связывает аккаунты, шлёт уведомление в Telegram и переименовывает подписки в 3x-ui.
    Если сайт недоступен или вернул ошибку, выполняется надёжный fallback прямо в SQLite БД.
    """
    global _cached_working_base_url
    headers = _get_headers()
    payload = {
        "token": token,
        "tg_id": tg_id,
        "username": username,
        "first_name": first_name,
    }

    for base_url in get_candidate_base_urls():
        url = f"{base_url}/api/auth/bot-link-telegram"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ok"):
                        _cached_working_base_url = base_url
                        return data
                    elif "detail" in data:
                        return data
                elif resp.status_code in (400, 403):
                    try:
                        data = resp.json()
                        if "detail" in data:
                            _cached_working_base_url = base_url
                            return {"ok": False, "detail": data["detail"]}
                    except Exception:
                        pass
                elif resp.status_code == 401:
                    logger.debug("Candidate {} returned 401 on link_telegram, trying next...", base_url)
                    continue
                else:
                    logger.debug("Candidate {} returned HTTP {}, trying next...", base_url, resp.status_code)
                    continue
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.debug("Candidate {} unreachable for link_telegram: {}", base_url, e)
            continue
        except Exception as e:
            logger.debug("Error calling link_telegram on {}: {}", base_url, e)
            continue

    logger.warning("Website bot-link-telegram HTTP API unavailable, executing direct DB link fallback...")

    # Fallback to direct DB
    try:
        from utils.utc import utc_now
        from db.connection import get_db

        async with get_db() as db:
            async with db.execute(
                "SELECT email, expires_at, used FROM telegram_link_tokens WHERE token = ?",
                (token,),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return {"ok": False, "detail": "Токен привязки не найден."}
            email_val, exp_at, is_used = row[0], row[1], row[2]
            if is_used:
                return {"ok": False, "detail": "Эта ссылка для привязки уже была использована."}
            if exp_at <= utc_now().isoformat():
                return {"ok": False, "detail": "Срок действия ссылки для привязки истёк."}

            await db.execute("UPDATE telegram_link_tokens SET used = 1 WHERE token = ?", (token,))
            await db.execute(
                "INSERT OR IGNORE INTO email_accounts (email, tg_id) VALUES (?, ?)",
                (email_val, tg_id),
            )
            await db.execute("UPDATE email_accounts SET tg_id = ? WHERE email = ?", (tg_id, email_val))
            await db.execute("UPDATE users SET email = ? WHERE tg_id = ?", (email_val, tg_id))
            await db.execute("UPDATE subscriptions SET tg_id = ? WHERE email_account = ?", (tg_id, email_val))
            await db.execute(
                "UPDATE subscriptions SET email_account = ? WHERE tg_id = ? AND (email_account IS NULL OR email_account = '')",
                (email_val, tg_id),
            )
            await db.commit()
            return {"ok": True, "email": email_val, "message": f"Аккаунт успешно привязан к {email_val}!"}
    except Exception as dbe:
        logger.error("Direct DB link error: {}", dbe)
        return {"ok": False, "detail": f"Ошибка привязки: {dbe}"}
