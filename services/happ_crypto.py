"""Шифрование ссылок подписки для Happ (crypt5 API / crypt4 RSA)."""
from __future__ import annotations

import asyncio
import base64
from typing import Final

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from loguru import logger

from config.happ_crypto import (
    HAPP_CRYPTO_CRYPT4_LOCAL,
    HAPP_CRYPTO_CRYPT5_API,
    HAPP_CRYPTO_NONE,
    effective_happ_crypto_mode,
    normalize_happ_crypto_mode,
)
from config.settings import settings
from db import bot_settings as bot_settings_db

_HAPP_USER_AGENT: Final[str] = "vpn-platega-bot/1.0"
_HAPP_CRYPTO_V4_PUBLIC_KEY_PEM: Final[str] = """-----BEGIN PUBLIC KEY-----
MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAlBetA0wjbaj+h7oJ/d/h
pNrXvAcuhOdFGEFcfCxSWyLzWk4SAQ05gtaEGZyetTax2uqagi9HT6lapUSUe2S8
nMLJf5K+LEs9TYrhhBdx/B0BGahA+lPJa7nUwp7WfUmSF4hir+xka5ApHjzkAQn6
cdG6FKtSPgq1rYRPd1jRf2maEHwiP/e/jqdXLPP0SFBjWTMt/joUDgE7v/IGGB0L
Q7mGPAlgmxwUHVqP4bJnZ//5sNLxWMjtYHOYjaV+lixNSfhFM3MdBndjpkmgSfmg
D5uYQYDL29TDk6Eu+xetUEqry8ySPjUbNWdDXCglQWMxDGjaqYXMWgxBA1UKjUBW
wbgr5yKTJ7mTqhlYEC9D5V/LOnKd6pTSvaMxkHXwk8hBWvUNWAxzAf5JZ7EVE3jt
0j682+/hnmL/hymUE44yMG1gCcWvSpB3BTlKoMnl4yrTakmdkbASeFRkN3iMRewa
IenvMhzJh1fq7xwX94otdd5eLB2vRFavrnhOcN2JJAkKTnx9dwQwFpGEkg+8U613
+Tfm/f82l56fFeoFN98dD2mUFLFZoeJ5CG81ZeXrH83niI0joX7rtoAZIPWzq3Y1
Zb/Zq+kK2hSIhphY172Uvs8X2Qp2ac9UoTPM71tURsA9IvPNvUwSIo/aKlX5KE3I
VE0tje7twWXL5Gb1sfcXRzsCAwEAAQ==
-----END PUBLIC KEY-----"""

# RSA-4096 PKCS1v15: (4096/8) - 11 = 501 байт
_CRYPT4_MAX_PLAIN_BYTES: Final[int] = 501

_cache: dict[tuple[str, str], str] = {}
_cache_lock = asyncio.Lock()
_v4_public_key = None
_crypt4_deprecated_logged = False


def clear_happ_crypto_cache() -> None:
    _cache.clear()


def _warn_crypt4_deprecated() -> None:
    global _crypt4_deprecated_logged
    if _crypt4_deprecated_logged:
        return
    _crypt4_deprecated_logged = True
    logger.warning(
        "HAPP_CRYPTO_MODE=crypt4_local: Happ больше не принимает happ://crypt4/ "
        "(invalid url) — используется crypt5 API. Поставьте HAPP_CRYPTO_MODE=crypt5_api"
    )


async def get_happ_crypto_mode() -> str:
    stored = await bot_settings_db.get_happ_crypto_mode()
    if stored is not None:
        mode = stored
    else:
        mode = normalize_happ_crypto_mode(settings.HAPP_CRYPTO_MODE)
    if mode == HAPP_CRYPTO_CRYPT4_LOCAL:
        _warn_crypt4_deprecated()
        mode = HAPP_CRYPTO_CRYPT5_API
        try:
            await bot_settings_db.set_happ_crypto_mode(mode)
        except Exception as e:
            logger.debug("Не удалось обновить happ_crypto_mode в БД: {}", e)
    return mode


def _load_crypt4_public_key():
    global _v4_public_key
    if _v4_public_key is None:
        _v4_public_key = serialization.load_pem_public_key(
            _HAPP_CRYPTO_V4_PUBLIC_KEY_PEM.encode("ascii"),
        )
    return _v4_public_key


def _encrypt_crypt4_local_sync(plain_url: str) -> str:
    data = plain_url.encode("utf-8")
    if len(data) > _CRYPT4_MAX_PLAIN_BYTES:
        raise ValueError(
            f"URL слишком длинный для Crypt4 ({len(data)} > {_CRYPT4_MAX_PLAIN_BYTES} байт)",
        )
    public_key = _load_crypt4_public_key()
    ciphertext = public_key.encrypt(data, padding.PKCS1v15())
    encoded = base64.b64encode(ciphertext).decode("ascii")
    return f"happ://crypt4/{encoded}"


async def _encrypt_crypt4_local(plain_url: str) -> str:
    return await asyncio.to_thread(_encrypt_crypt4_local_sync, plain_url)


async def _encrypt_crypt5_api(plain_url: str) -> str:
    api_url = settings.HAPP_CRYPTO_API_URL.strip()
    async with httpx.AsyncClient(timeout=settings.HAPP_CRYPTO_TIMEOUT_SEC) as client:
        resp = await client.post(
            api_url,
            json={"url": plain_url},
            headers={"User-Agent": _HAPP_USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()

    encrypted = (data.get("encrypted_link") or "").strip()
    if not encrypted.startswith("happ://crypt"):
        raise ValueError("Happ crypto API: нет happ://crypt в ответе")
    return encrypted


async def _encrypt_uncached(plain_url: str, mode: str) -> str:
    mode = effective_happ_crypto_mode(mode)
    if mode == HAPP_CRYPTO_CRYPT5_API:
        return await _encrypt_crypt5_api(plain_url)
    return plain_url


async def encrypt_happ_subscription_link(plain_url: str, *, mode: str | None = None) -> str:
    """
    Шифрует plain URL для клиента Happ.
    mode: none | crypt5_api | crypt4_local (если None — из настроек).
    """
    url = (plain_url or "").strip()
    if not url:
        return url

    if mode is not None:
        resolved_mode = effective_happ_crypto_mode(normalize_happ_crypto_mode(mode))
    else:
        resolved_mode = await get_happ_crypto_mode()
    if resolved_mode == HAPP_CRYPTO_NONE:
        return url

    cache_key = (resolved_mode, url)
    cached = _cache.get(cache_key)
    if cached:
        return cached

    async with _cache_lock:
        cached = _cache.get(cache_key)
        if cached:
            return cached
        try:
            encrypted = await _encrypt_uncached(url, resolved_mode)
        except Exception as e:
            logger.warning(
                "Happ crypto {} failed for {}: {}",
                resolved_mode,
                url[:80],
                e,
            )
            return url
        _cache[cache_key] = encrypted
        return encrypted