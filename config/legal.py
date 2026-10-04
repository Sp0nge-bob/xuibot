"""Ссылки на юридические документы и инструкции проекта (CaelixFlow)."""
from __future__ import annotations

import os
import re
from pathlib import Path
from loguru import logger

DEFAULT_PRIVACY_POLICY_URL = "https://telegra.ph/Politika-konfidencialnosti-10-01-95"
DEFAULT_TERMS_OF_SERVICE_URL = "https://telegra.ph/Polzovatelskoe-soglashenie-CaelixFlow-10-01"
DEFAULT_REFUND_POLICY_URL = "https://my.caelixflow.com/refund"
DEFAULT_IOS_HAPP_BLOCKED_URL = "https://my.caelixflow.com/ios-guide"

# Константы по умолчанию (обратная совместимость импортов)
PRIVACY_POLICY_URL = DEFAULT_PRIVACY_POLICY_URL
TERMS_OF_SERVICE_URL = DEFAULT_TERMS_OF_SERVICE_URL
REFUND_POLICY_URL = DEFAULT_REFUND_POLICY_URL


def normalize_doc_url(raw: str | None) -> str:
    val = (raw or "").strip().strip('"').strip("'")
    if not val or val.lower() in ("false", "0", "none", "off", "no", "-"):
        return ""
    if not val.startswith(("http://", "https://")):
        val = f"https://{val}"
    return val


def get_env_privacy_policy_url() -> str:
    from config.settings import settings

    return normalize_doc_url(getattr(settings, "PRIVACY_POLICY_URL", "")) or DEFAULT_PRIVACY_POLICY_URL


def get_env_terms_of_service_url() -> str:
    from config.settings import settings

    return normalize_doc_url(getattr(settings, "TERMS_OF_SERVICE_URL", "")) or DEFAULT_TERMS_OF_SERVICE_URL


def get_env_refund_policy_url() -> str:
    from config.settings import settings

    return normalize_doc_url(getattr(settings, "REFUND_POLICY_URL", "")) or DEFAULT_REFUND_POLICY_URL


def get_env_ios_happ_blocked_url() -> str:
    from config.settings import settings

    return normalize_doc_url(getattr(settings, "IOSHAPPBLOCKED", ""))


_DOC_ENV_KEY_PATTERNS = {
    "PRIVACY_POLICY_URL": re.compile(r"^\s*#?\s*PRIVACY_POLICY_URL\s*=", re.IGNORECASE | re.MULTILINE),
    "TERMS_OF_SERVICE_URL": re.compile(r"^\s*#?\s*TERMS_OF_SERVICE_URL\s*=", re.IGNORECASE | re.MULTILINE),
    "REFUND_POLICY_URL": re.compile(r"^\s*#?\s*REFUND_POLICY_URL\s*=", re.IGNORECASE | re.MULTILINE),
    "ioshappblocked": re.compile(
        r"^\s*#?\s*(?:ioshappblocked|ios_happ_blocked|ios_region_guide_url)\s*=",
        re.IGNORECASE | re.MULTILINE,
    ),
}


def env_file_has_documents_section(env_path: Path | None = None) -> bool:
    path = env_path or Path(".env")
    if not path.is_file():
        return False
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(pat.search(content) for pat in _DOC_ENV_KEY_PATTERNS.values())


def _is_pytest_default_env(env_path: Path | None) -> bool:
    return env_path is None and (
        os.environ.get("PYTEST_RUNNING") == "1" or "PYTEST_CURRENT_TEST" in os.environ
    )


def write_or_update_env_key(key: str, value: str, env_path: Path | None = None) -> bool:
    """Обновляет или добавляет ключ в .env на диске (без сброса остальных настроек)."""
    if _is_pytest_default_env(env_path):
        return False
    path = env_path or Path(".env")
    if not path.is_file():
        return False
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        key_re = re.compile(rf"^\s*{re.escape(key)}\s*=", re.IGNORECASE)
        replaced = False
        new_lines: list[str] = []
        for line in lines:
            if not replaced and key_re.match(line):
                new_lines.append(f"{key}={value}")
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            if new_lines and new_lines[-1].strip() != "":
                new_lines.append("")
            new_lines.append(f"{key}={value}")
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return True
    except OSError as e:
        logger.debug("Не удалось обновить {} в {}: {}", key, path, e)
        return False


def migrate_documents_to_env_file(
    *,
    privacy_url: str,
    terms_url: str,
    refund_url: str,
    ios_happ_blocked_url: str,
    env_path: Path | None = None,
) -> bool:
    """
    Однократная миграция при обновлении: если в .env ещё нет секции «Документы и инструкции»,
    дописывает текущие ссылки из бота в .env, чтобы ничего не сбросилось.
    """
    if _is_pytest_default_env(env_path):
        return False
    path = env_path or Path(".env")
    if not path.is_file():
        return False
    if env_file_has_documents_section(path):
        return False
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        block_lines = [
            "",
            "# --- Документы и инструкции ---",
            "# Ссылки на юридические документы (раздел «Документы» в боте)",
            f"PRIVACY_POLICY_URL={privacy_url}",
            f"TERMS_OF_SERVICE_URL={terms_url}",
            f"REFUND_POLICY_URL={refund_url}",
            "# Ссылка на инструкцию по установке Happ на iOS (смена региона App Store).",
            "# Если переменная не указана или пустая — в боте не упоминается, что Happ заблокирован в РФ.",
            f"ioshappblocked={ios_happ_blocked_url}",
            "",
        ]
        if content and not content.endswith("\n"):
            content += "\n"
        path.write_text(content + "\n".join(block_lines), encoding="utf-8")
        logger.info("Секция «Документы и инструкции» автоматически перенесена в {}", path)
        return True
    except OSError as e:
        logger.warning("Не удалось записать секцию документов в {}: {}", path, e)
        return False