from __future__ import annotations

import base64
import hashlib
from typing import Any, Optional
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from loguru import logger

from config.settings import settings

_ENC_PREFIX = "enc:v1:"
_SALT = b"caelix_flow_vpn_db_encryption_salt_2026"
_cached_fernet: Optional[Fernet] = None
_cached_candidates: Optional[list[Fernet]] = None

KNOWN_FALLBACK_SECRETS = (
    "super_secret_jwt_key_vpn_website_2026",
    "default_dev_secret_key_change_in_production",
)


def _clean_str(val: Any) -> str:
    s = str(val or "").strip()
    return s.strip("\"'")


def _get_secret_key() -> str:
    key = _clean_str(getattr(settings, "SECRET_KEY", ""))
    if not key:
        logger.warning("SECRET_KEY is empty in settings, using fallback dev key")
        key = "default_dev_secret_key_change_in_production"
    return key


def _make_hkdf_fernet(secret: str) -> Optional[Fernet]:
    if not secret:
        return None
    try:
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_SALT,
            info=b"caelix-flow-fernet-key-derivation",
        )
        derived_32 = hkdf.derive(secret.encode("utf-8"))
        return Fernet(base64.urlsafe_b64encode(derived_32))
    except Exception as e:
        logger.debug("Failed to derive HKDF fernet: {}", e)
        return None


def _make_sha256_fernet(secret: str) -> Optional[Fernet]:
    if not secret:
        return None
    try:
        derived_32 = hashlib.sha256(secret.encode("utf-8") + _SALT).digest()
        return Fernet(base64.urlsafe_b64encode(derived_32))
    except Exception as e:
        logger.debug("Failed to derive SHA256 fernet: {}", e)
        return None


def _get_fernet() -> Fernet:
    global _cached_fernet
    if _cached_fernet is not None:
        return _cached_fernet

    key_raw = _clean_str(getattr(settings, "ENCRYPTION_KEY", ""))
    if key_raw:
        try:
            decoded = base64.urlsafe_b64decode(key_raw.encode("utf-8"))
            if len(decoded) == 32:
                _cached_fernet = Fernet(key_raw.encode("utf-8"))
                return _cached_fernet
        except Exception:
            logger.warning("Configured ENCRYPTION_KEY is invalid, deriving key via HKDF from SECRET_KEY")

    hkdf_f = _make_hkdf_fernet(_get_secret_key())
    if hkdf_f is not None:
        _cached_fernet = hkdf_f
        return _cached_fernet

    _cached_fernet = Fernet(Fernet.generate_key())
    return _cached_fernet


def _get_candidate_fernets() -> list[Fernet]:
    global _cached_candidates
    if _cached_candidates is not None:
        return _cached_candidates

    candidates: list[Fernet] = []
    seen_keys: set[bytes] = set()

    def add_fernet(f: Optional[Fernet]) -> None:
        if f is None:
            return
        try:
            k = getattr(f, "_encryption_key", None)
            if k and k in seen_keys:
                return
            if k:
                seen_keys.add(k)
        except Exception:
            pass
        candidates.append(f)

    # 1. Primary configured fernet (ENCRYPTION_KEY или текущий HKDF)
    add_fernet(_get_fernet())

    # 2. Текущий SECRET_KEY (HKDF + legacy SHA256)
    current_sec = _get_secret_key()
    add_fernet(_make_hkdf_fernet(current_sec))
    add_fernet(_make_sha256_fernet(current_sec))

    # 3. Резервный ключ из .env (если задан OLD_SECRET_KEY)
    old_sec = _clean_str(getattr(settings, "OLD_SECRET_KEY", ""))
    if old_sec and old_sec != current_sec:
        add_fernet(_make_hkdf_fernet(old_sec))
        add_fernet(_make_sha256_fernet(old_sec))

    # 4. Общеизвестные дефолты разработчика
    for fallback_sec in KNOWN_FALLBACK_SECRETS:
        if fallback_sec != current_sec and fallback_sec != old_sec:
            add_fernet(_make_hkdf_fernet(fallback_sec))
            add_fernet(_make_sha256_fernet(fallback_sec))

    _cached_candidates = candidates
    return _cached_candidates


def decrypt_secret(ciphertext: Optional[str]) -> str:
    """
    Расшифровывает строку, если она была зашифрована веб-панелью (префикс enc:v1:).
    Если префикса нет, возвращает строку как есть.
    Поддерживает бесшовную расшифровку через цепочку ключей (ENCRYPTION_KEY, HKDF, legacy SHA-256).
    """
    if not ciphertext:
        return ""
    if not ciphertext.startswith(_ENC_PREFIX):
        return ciphertext

    token_b64 = ciphertext[len(_ENC_PREFIX):].strip()
    candidates = _get_candidate_fernets()

    for idx, fernet in enumerate(candidates):
        try:
            decrypted = fernet.decrypt(token_b64.encode("utf-8"))
            if idx > 0:
                logger.info("Successfully decrypted node credential using fallback key #{}", idx)
            return decrypted.decode("utf-8")
        except InvalidToken:
            continue
        except Exception as e:
            logger.debug("Fernet candidate #{} failed: {}", idx, e)
            continue

    logger.error("Failed to decrypt node credential with all configured and fallback keys")
    return ""


def encrypt_secret(plaintext: str) -> str:
    """Шифрует конфиденциальную строку алгоритмом Fernet с использованием активного ключа."""
    if not plaintext:
        return ""
    if plaintext.startswith(_ENC_PREFIX):
        return plaintext
    fernet = _get_fernet()
    token = fernet.encrypt(plaintext.encode("utf-8"))
    return f"{_ENC_PREFIX}{token.decode('utf-8')}"
