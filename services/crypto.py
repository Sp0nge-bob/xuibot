from __future__ import annotations

import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from loguru import logger

from config.settings import settings

_ENC_PREFIX = "enc:v1:"
_cached_fernet: Optional[Fernet] = None
_cached_legacy_fernet: Optional[Fernet] = None


def _get_secret_key() -> str:
    key = (getattr(settings, "SECRET_KEY", "") or "").strip()
    if not key:
        logger.warning("SECRET_KEY is empty in settings, using fallback dev key")
        key = "default_dev_secret_key_change_in_production"
    return key


def _derive_legacy_key() -> Fernet:
    global _cached_legacy_fernet
    if _cached_legacy_fernet is not None:
        return _cached_legacy_fernet
    salt = b"caelix_flow_vpn_db_encryption_salt_2026"
    secret_key = _get_secret_key()
    derived_32 = hashlib.sha256(secret_key.encode("utf-8") + salt).digest()
    _cached_legacy_fernet = Fernet(base64.urlsafe_b64encode(derived_32))
    return _cached_legacy_fernet


def _get_fernet() -> Fernet:
    global _cached_fernet
    if _cached_fernet is not None:
        return _cached_fernet

    key_raw = (getattr(settings, "ENCRYPTION_KEY", "") or "").strip()
    if key_raw:
        try:
            decoded = base64.urlsafe_b64decode(key_raw.encode("utf-8"))
            if len(decoded) == 32:
                _cached_fernet = Fernet(key_raw.encode("utf-8"))
                return _cached_fernet
        except Exception:
            logger.warning("Configured ENCRYPTION_KEY is invalid, deriving key via HKDF from SECRET_KEY")

    salt = b"caelix_flow_vpn_db_encryption_salt_2026"
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"caelix-flow-fernet-key-derivation",
    )
    derived_32 = hkdf.derive(_get_secret_key().encode("utf-8"))
    b64_key = base64.urlsafe_b64encode(derived_32)
    _cached_fernet = Fernet(b64_key)
    return _cached_fernet


def decrypt_secret(ciphertext: Optional[str]) -> str:
    """
    Расшифровывает строку, если она была зашифрована веб-панелью (префикс enc:v1:).
    Если префикса нет, возвращает строку как есть.
    """
    if not ciphertext:
        return ""
    if not ciphertext.startswith(_ENC_PREFIX):
        return ciphertext

    token_b64 = ciphertext[len(_ENC_PREFIX):]
    try:
        fernet = _get_fernet()
        decrypted = fernet.decrypt(token_b64.encode("utf-8"))
        return decrypted.decode("utf-8")
    except InvalidToken:
        try:
            legacy = _derive_legacy_key()
            decrypted = legacy.decrypt(token_b64.encode("utf-8"))
            return decrypted.decode("utf-8")
        except Exception as e:
            logger.error("Failed to decrypt node credential using legacy key: {}", e)
            return ""
    except Exception as e:
        logger.error("Failed to decrypt node credential: {}", e)
        return ""


def encrypt_secret(plaintext: str) -> str:
    """Шифрует конфиденциальную строку алгоритмом Fernet."""
    if not plaintext:
        return ""
    if plaintext.startswith(_ENC_PREFIX):
        return plaintext
    fernet = _get_fernet()
    token = fernet.encrypt(plaintext.encode("utf-8"))
    return f"{_ENC_PREFIX}{token.decode('utf-8')}"
