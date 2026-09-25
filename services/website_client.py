from __future__ import annotations

import httpx
from loguru import logger
from config.settings import settings


def get_website_base_url() -> str:
    url = getattr(settings, "WEBSITE_API_URL", None) or "http://127.0.0.1:8080"
    return url.rstrip("/")


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
    """
    base_url = get_website_base_url()
    url = f"{base_url}/api/auth/bot-send-otp"
    headers = _get_headers()
    payload = {"email": email, "tg_id": tg_id}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return {"ok": True, "message": data.get("message", "Код отправлен")}
            elif resp.status_code == 429:
                try:
                    data = resp.json()
                    detail = data.get("detail", "Слишком много запросов. Подождите немного.")
                except Exception:
                    detail = "Слишком много запросов. Пожалуйста, подождите."
                return {"ok": False, "detail": detail}
            elif resp.status_code in (400, 403):
                try:
                    data = resp.json()
                    detail = data.get("detail", "Ошибка валидации адреса")
                except Exception:
                    detail = "Некорректный адрес или доступ ограничен."
                return {"ok": False, "detail": detail}
            else:
                logger.error("Website send-otp error HTTP {}: {}", resp.status_code, resp.text)
                return {"ok": False, "detail": f"Ошибка отправки (HTTP {resp.status_code}). Попробуйте позже."}
    except httpx.ConnectError:
        logger.error("Website API is unreachable at {}", url)
        return {"ok": False, "detail": "Сервис отправки почты временно недоступен. Попробуйте чуть позже."}
    except Exception as e:
        logger.error("Failed to call website send-otp: {}", e)
        return {"ok": False, "detail": f"Ошибка соединения: {e}"}


async def verify_otp_email(tg_id: int, email: str, code: str) -> dict:
    """
    Отправляет введённый код на проверку в API сайта для подтверждения и привязки аккаунта.
    """
    base_url = get_website_base_url()
    url = f"{base_url}/api/auth/bot-verify-otp"
    headers = _get_headers()
    payload = {"email": email, "code": code, "tg_id": tg_id}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return {"ok": True, "message": data.get("message", "Почта успешно привязана!")}
            elif resp.status_code in (400, 403, 429):
                try:
                    data = resp.json()
                    detail = data.get("detail", "Неверный код подтверждения")
                except Exception:
                    detail = "Неверный код подтверждения"
                return {"ok": False, "detail": detail}
            else:
                logger.error("Website verify-otp error HTTP {}: {}", resp.status_code, resp.text)
                return {"ok": False, "detail": f"Ошибка проверки (HTTP {resp.status_code})"}
    except httpx.ConnectError:
        logger.error("Website API is unreachable at {}", url)
        return {"ok": False, "detail": "Сервис проверки временно недоступен. Попробуйте позже."}
    except Exception as e:
        logger.error("Failed to call website verify-otp: {}", e)
        return {"ok": False, "detail": f"Ошибка соединения: {e}"}


async def unlink_email_account(tg_id: int) -> dict:
    """
    Отвязывает почту от аккаунта Telegram.
    """
    base_url = get_website_base_url()
    url = f"{base_url}/api/auth/bot-unlink-email"
    headers = _get_headers()
    payload = {"tg_id": tg_id}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                return {"ok": True, "message": "Почта успешно отвязана"}
    except Exception as e:
        logger.debug("Website unlink-email API error (will fallback to direct DB): {}", e)

    # Fallback to direct DB in case website is not running
    try:
        from db.connection import get_db
        async with get_db() as db:
            await db.execute("UPDATE email_accounts SET tg_id = NULL WHERE tg_id = ?", (tg_id,))
            await db.execute("UPDATE users SET email = NULL WHERE tg_id = ?", (tg_id,))
            await db.commit()
        return {"ok": True, "message": "Почта успешно отвязана"}
    except Exception as dbe:
        logger.error("Failed to unlink email in DB: {}", dbe)
        return {"ok": False, "detail": f"Ошибка отвязки: {dbe}"}
