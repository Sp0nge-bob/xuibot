"""Режимы шифрования ссылок подписки для Happ."""
from __future__ import annotations

from typing import Final

HAPP_CRYPTO_NONE: Final[str] = "none"
HAPP_CRYPTO_CRYPT5_API: Final[str] = "crypt5_api"
HAPP_CRYPTO_CRYPT4_LOCAL: Final[str] = "crypt4_local"

HAPP_CRYPTO_MODES: Final[tuple[str, ...]] = (
    HAPP_CRYPTO_NONE,
    HAPP_CRYPTO_CRYPT5_API,
    HAPP_CRYPTO_CRYPT4_LOCAL,
)

HAPP_CRYPTO_MODE_LABELS: Final[dict[str, str]] = {
    HAPP_CRYPTO_NONE: "Без шифрования",
    HAPP_CRYPTO_CRYPT5_API: "Crypt5 (API Happ)",
    HAPP_CRYPTO_CRYPT4_LOCAL: "Crypt4 (RSA локально)",
}


def normalize_happ_crypto_mode(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value in HAPP_CRYPTO_MODES:
        return value
    if value in {"crypt5", "api", "crypt5-api"}:
        return HAPP_CRYPTO_CRYPT5_API
    if value in {"crypt4", "local", "rsa", "crypt4-local"}:
        return HAPP_CRYPTO_CRYPT4_LOCAL
    return HAPP_CRYPTO_NONE