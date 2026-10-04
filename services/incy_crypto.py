"""
Шифрование ссылок подписки для клиента INCY (incy://crypt1/<payload>).
Совместимо с vpn-website/app/services/incy_crypto.py (детерминированный AES-256-GCM).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.parse
from typing import Final, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from loguru import logger

from config.settings import settings

try:
    from incy_link_encoder import (
        decrypt_link as _pkg_decrypt_link,
        encrypt_link_deterministic as _pkg_encrypt_deterministic,
    )
    _HAS_INCY_PKG = True
except Exception:
    _HAS_INCY_PKG = False

_INCY_CRYPT1_PREFIX: Final[str] = "incy://crypt1/"
_INCY_KEY_HEX: Final[str] = "f6d40ea0c8a8899d7c682d09ba0d4165dfe2b3dd45e6bb3e25cb233cf00c2462"
_INCY_KEY_BYTES: Final[bytes] = bytes.fromhex(_INCY_KEY_HEX)
_IV_LEN: Final[int] = 12
_TAG_LEN: Final[int] = 16

_memory_cache: dict[str, str] = {}
_MAX_INCY_CACHE_SIZE: Final[int] = 2000


def clear_incy_crypto_cache() -> None:
    _memory_cache.clear()


def _set_cache(key: str, val: str) -> None:
    if len(_memory_cache) >= _MAX_INCY_CACHE_SIZE:
        for k in list(_memory_cache.keys())[:200]:
            _memory_cache.pop(k, None)
    _memory_cache[key] = val


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "" if len(s) % 4 == 0 else "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _derive_deterministic_iv(url: str, name: str | None) -> bytes:
    """Генерирует стабильный 12-байтный IV для пары (url, name)."""
    seed = f"incy_iv_v1:{name or ''}:{url}".encode("utf-8")
    return hashlib.sha256(seed).digest()[:_IV_LEN]


def build_incy_target_url(plain_url: str, extra_params: Optional[dict[str, str]] = None) -> str:
    """
    Формирует целевой URL подписки специально для клиента INCY.
    Позволяет добавлять query-параметры под INCY отдельно от Happ.
    """
    url = (plain_url or "").strip()
    if not url or url.startswith(("incy://", "happ://")):
        return url
    if not extra_params:
        return url
    try:
        parsed = urllib.parse.urlsplit(url)
        query_dict = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        for k, v in extra_params.items():
            if v is not None and str(v) != "":
                query_dict[str(k)] = str(v)
        new_query = urllib.parse.urlencode(query_dict)
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment)
        )
    except Exception:
        return url


def encrypt_incy_crypt1(
    plain_url: str,
    *,
    name: Optional[str] = None,
    deterministic: bool = True,
    extra_params: Optional[dict[str, str]] = None,
) -> str:
    """
    Шифрует HTTP(S) ссылку подписки в формат incy://crypt1/<payload>.
    Поддерживает кастомное имя провайдера/подписки в поле 'n' (до 128 символов).
    """
    url = (plain_url or "").strip()
    if not url:
        return ""
    if url.startswith(_INCY_CRYPT1_PREFIX):
        return url

    target_url = build_incy_target_url(url, extra_params=extra_params)
    site_name = getattr(settings, "SITE_NAME", None) or getattr(settings, "BRAND_NAME", None) or "VPN"
    provider_name = (name or site_name or "VPN Service").strip()
    if provider_name and "vpn" not in provider_name.lower():
        provider_name = f"{provider_name} VPN"
    provider_name = provider_name[:128] if provider_name else None

    cache_key = f"{provider_name or ''}:{target_url}"
    if deterministic and cache_key in _memory_cache:
        return _memory_cache[cache_key]

    iv = _derive_deterministic_iv(target_url, provider_name) if deterministic else os.urandom(_IV_LEN)

    if _HAS_INCY_PKG:
        try:
            encrypted = _pkg_encrypt_deterministic(target_url, iv=iv, name=provider_name)
            if deterministic:
                _set_cache(cache_key, encrypted)
            return encrypted
        except Exception as e:
            logger.warning("incy_link_encoder failed, fallback AESGCM: {}", e)

    payload_obj: dict[str, object] = {"url": target_url, "v": 1}
    if provider_name:
        payload_obj["n"] = provider_name
    plaintext = json.dumps(
        payload_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

    out = AESGCM(_INCY_KEY_BYTES).encrypt(iv, plaintext, None)
    encrypted = _INCY_CRYPT1_PREFIX + _b64url_encode(iv + out)
    if deterministic:
        _set_cache(cache_key, encrypted)
    return encrypted


def decrypt_incy_crypt1(link: str) -> dict[str, object]:
    """Расшифровывает ссылку incy://crypt1/<payload> и возвращает {'url': ..., 'name': ..., 'v': 1, 'u': ..., 'n': ...}."""
    clean = (link or "").strip()
    if not clean.startswith(_INCY_CRYPT1_PREFIX):
        raise ValueError(f"Expected {_INCY_CRYPT1_PREFIX} prefix")

    if _HAS_INCY_PKG:
        dec = _pkg_decrypt_link(clean)
        return {"v": 1, "url": dec.url, "name": dec.name, "u": dec.url, "n": dec.name}

    payload = clean[len(_INCY_CRYPT1_PREFIX) :].rstrip("/")
    wire = _b64url_decode(payload)
    if len(wire) < _IV_LEN + _TAG_LEN + 1:
        raise ValueError("Payload too short")
    iv, ct_and_tag = wire[:_IV_LEN], wire[_IV_LEN:]
    try:
        plaintext = AESGCM(_INCY_KEY_BYTES).decrypt(iv, ct_and_tag, None)
    except InvalidTag:
        raise ValueError("Authentication failed") from None

    parsed = json.loads(plaintext.decode("utf-8"))
    return {
        "v": parsed.get("v", 1),
        "url": parsed.get("url"),
        "name": parsed.get("n"),
        "u": parsed.get("url"),
        "n": parsed.get("n"),
    }


async def encrypt_incy_subscription_link(
    plain_url: str,
    *,
    sub_id: Optional[str] = None,
    name: Optional[str] = None,
    extra_params: Optional[dict[str, str]] = None,
) -> str:
    """
    Асинхронная обёртка генерации зашифрованной ссылки incy://crypt1/...
    Если plain_url пустой или это уже зашифрованная ссылка Happ, восстанавливает plain URL по sub_id.
    """
    url = (plain_url or "").strip()
    if url.startswith(_INCY_CRYPT1_PREFIX):
        return url

    if not url or url.startswith("happ://"):
        if sub_id:
            from services.xui import build_plain_sub_link

            url = await build_plain_sub_link(sub_id)
        else:
            return ""

    return encrypt_incy_crypt1(url, name=name, deterministic=True, extra_params=extra_params)


def build_incy_redirect_url(sub_key: str | int) -> str:
    """
    Генерирует веб-ссылку для 1-клик добавления подписки в INCY.
    Открывает /incy/{sub_key} на сайте — аналог build_happ_redirect_url.
    """
    origin = getattr(settings, "website_base_url", "")

    if not origin:
        target = (getattr(settings, "PUBLIC_WEBHOOK_URL", "") or "").strip()
        if target:
            if not target.startswith(("http://", "https://")):
                target = f"https://{target}"
            parts = urllib.parse.urlsplit(target)
            if parts.netloc:
                origin = f"{parts.scheme}://{parts.netloc}"

    if not origin:
        target = (getattr(settings, "SUBSCRIPTION_BASE_URL", "") or "").strip()
        if target:
            if not target.startswith(("http://", "https://")):
                target = f"https://{target}"
            parts = urllib.parse.urlsplit(target)
            if parts.netloc:
                origin = f"{parts.scheme}://{parts.netloc}"

    if not origin:
        origin = "https://example.com"

    return f"{origin.rstrip('/')}/incy/{sub_key}"
