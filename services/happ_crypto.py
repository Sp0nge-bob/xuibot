"""Шифрование ссылок подписки для Happ (happ://crypt5/)."""
from __future__ import annotations

import httpx
from loguru import logger

from config.settings import settings

_HAPP_USER_AGENT = "vpn-platega-bot/1.0"


async def encrypt_happ_subscription_link(plain_url: str) -> str:
    """
    Преобразует обычную URL подписки в happ://crypt5/… через API Happ.
    Документация: https://www.happ.su/main/dev-docs/crypto-link
    """
    url = (plain_url or "").strip()
    if not url:
        return url

    api_url = settings.HAPP_CRYPTO_API_URL.strip()
    try:
        async with httpx.AsyncClient(timeout=settings.HAPP_CRYPTO_TIMEOUT_SEC) as client:
            resp = await client.post(
                api_url,
                json={"url": url},
                headers={"User-Agent": _HAPP_USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        logger.warning("Happ crypto API failed for {}: {}", url[:80], e)
        return url
    except ValueError as e:
        logger.warning("Happ crypto API invalid JSON: {}", e)
        return url

    encrypted = (data.get("encrypted_link") or "").strip()
    if not encrypted.startswith("happ://crypt"):
        logger.warning(
            "Happ crypto API: unexpected response (no happ://crypt link), using plain URL",
        )
        return url

    return encrypted