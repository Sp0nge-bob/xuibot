"""Шифрование ссылок подписки для Happ (RSA crypt3/crypt4 локально, crypt5 API)."""
from __future__ import annotations

import asyncio
import base64
from typing import Final

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from loguru import logger

from config.happ_crypto import (
    HAPP_CRYPTO_CRYPT3_LOCAL,
    HAPP_CRYPTO_CRYPT4_LOCAL,
    HAPP_CRYPTO_CRYPT5_API,
    HAPP_CRYPTO_NONE,
    normalize_happ_crypto_mode,
)
from config.settings import settings
from db import bot_settings as bot_settings_db

_HAPP_USER_AGENT: Final[str] = "vpn-platega-bot/1.0"

# Ключ из https://www.happ.su/main/dev-docs/crypto-link — в @kastov/cryptohapp это crypt3.
_HAPP_PUBLIC_KEY_V3_PEM: Final[str] = """-----BEGIN PUBLIC KEY-----
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

# Отдельный ключ crypt4 (не совпадает с RSA-ключом в документации Happ).
_HAPP_PUBLIC_KEY_V4_PEM: Final[str] = """-----BEGIN PUBLIC KEY-----
MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEA3UZ0M3L4K+WjM3vkbQnz
ozHg/cRbEXvQ6i4A8RVN4OM3rK9kU01FdjyoIgywve8OEKsFnVwERZAQZ1Trv60B
hmaM76QQEE+EUlIOL9EpwKWGtTL5lYC1sT9XJMNP3/CI0gP5wwQI88cY/xedpOEB
W72EmOOShHUm/b/3m+HPmqwc4ugKj5zWV5SyiT829aFA5DxSjmIIFBAms7DafmSq
LFTYIQL5cShDY2u+/sqyAw9yZIOoqW2TFIgIHhLPWek/ocDU7zyOrlu1E0SmcQQb
LFqHq02fsnH6IcqTv3N5Adb/CkZDDQ6HvQVBmqbKZKf7ZdXkqsc/Zw27xhG7OfXC
tUmWsiL7zA+KoTd3avyOh93Q9ju4UQsHthL3Gs4vECYOCS9dsXXSHEY/1ngU/hjO
WFF8QEE/rYV6nA4PTyUvo5RsctSQL/9DJX7XNh3zngvif8LsCN2MPvx6X+zLouBX
zgBkQ9DFfZAGLWf9TR7KVjZC/3NsuUCDoAOcpmN8pENBbeB0puiKMMWSvll36+2M
YR1Xs0MgT8Y9TwhE2+TnnTJOhzmHi/BxiUlY/w2E0s4ax9GHAmX0wyF4zeV7kDkc
vHuEdc0d7vDmdw0oqCqWj0Xwq86HfORu6tm1A8uRATjb4SzjTKclKuoElVAVa5Jo
oh/uZMozC65SmDw+N5p6Su8CAwEAAQ==
-----END PUBLIC KEY-----"""

_RSA_LOCAL: Final[dict[str, tuple[str, str]]] = {
    "crypt3": ("happ://crypt3/", _HAPP_PUBLIC_KEY_V3_PEM),
    "crypt4": ("happ://crypt4/", _HAPP_PUBLIC_KEY_V4_PEM),
}

# RSA-4096 PKCS1v15: (4096/8) - 11 = 501 байт
_RSA_MAX_PLAIN_BYTES: Final[int] = 501

_cache: dict[tuple[str, str], str] = {}
_cache_lock = asyncio.Lock()
_rsa_public_keys: dict[str, object] = {}


def clear_happ_crypto_cache() -> None:
    _cache.clear()


async def get_happ_crypto_mode() -> str:
    stored = await bot_settings_db.get_happ_crypto_mode()
    if stored is not None:
        return stored
    return normalize_happ_crypto_mode(settings.HAPP_CRYPTO_MODE)


def _load_rsa_public_key(version: str):
    if version not in _rsa_public_keys:
        _, pem = _RSA_LOCAL[version]
        _rsa_public_keys[version] = serialization.load_pem_public_key(pem.encode("ascii"))
    return _rsa_public_keys[version]


def _encrypt_rsa_local_sync(plain_url: str, version: str) -> str:
    prefix, _ = _RSA_LOCAL[version]
    data = plain_url.encode("utf-8")
    if len(data) > _RSA_MAX_PLAIN_BYTES:
        raise ValueError(
            f"URL слишком длинный для RSA {version} ({len(data)} > {_RSA_MAX_PLAIN_BYTES} байт)",
        )
    public_key = _load_rsa_public_key(version)
    ciphertext = public_key.encrypt(data, padding.PKCS1v15())
    encoded = base64.b64encode(ciphertext).decode("ascii")
    return f"{prefix}{encoded}"


async def _encrypt_rsa_local(plain_url: str, version: str) -> str:
    return await asyncio.to_thread(_encrypt_rsa_local_sync, plain_url, version)


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
    if mode == HAPP_CRYPTO_CRYPT3_LOCAL:
        return await _encrypt_rsa_local(plain_url, "crypt3")
    if mode == HAPP_CRYPTO_CRYPT4_LOCAL:
        return await _encrypt_rsa_local(plain_url, "crypt4")
    if mode == HAPP_CRYPTO_CRYPT5_API:
        return await _encrypt_crypt5_api(plain_url)
    return plain_url


async def encrypt_happ_subscription_link(plain_url: str, *, mode: str | None = None) -> str:
    """
    Шифрует plain URL для клиента Happ.
    Локальный RSA: crypt3_local → happ://crypt3/, crypt4_local → happ://crypt4/.
    """
    url = (plain_url or "").strip()
    if not url:
        return url

    if mode is not None:
        resolved_mode = normalize_happ_crypto_mode(mode)
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
        logger.debug("Happ crypto {} → {}", resolved_mode, encrypted[:40])
        return encrypted