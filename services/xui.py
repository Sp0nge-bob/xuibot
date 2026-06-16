"""
Unified client API 3x-ui 3.2+ (report/api.txt).

  POST clients/add + inboundIds  — новая подписка
  POST clients/update/{email}    — продление / disable
  POST clients/groups/bulkAdd    — привязка группы (UI панели)
  POST clients/del/{email}       — удаление tg*
  POST clients/{email}/attach    — догон инбаунда (если нет в settings)
  POST clients/{email}/detach    — снятие лишнего инбаунда
  GET  clients/get/{email}       — чтение клиента
"""
import asyncio
import re
import secrets
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple

from py3xui import AsyncApi, Client
from py3xui.api.api_base import ApiFields
from loguru import logger

from config.settings import settings
from db.bot_settings import get_subscription_inbound_ids
from services.panel_cache import panel_cache

_api: Optional[AsyncApi] = None
_bot_group_ensured: bool = False
_BOT_CLIENT_EMAIL = re.compile(r"^tg(?:free)?\d+$")


def _assert_bot_client_email(email: str) -> None:
    if not _BOT_CLIENT_EMAIL.match(email or ""):
        raise ValueError(f"Запрещено: операция только для tg-клиентов бота, получено {email!r}")


def _tg_id_from_email(email: str) -> int:
    if not email:
        return 0
    if email.startswith("tgfree"):
        return int(email[6:])
    if email.startswith("tg"):
        return int(email[2:])
    return 0


def normalize_xui_host(host: str) -> str:
    host = host.strip().rstrip("/")
    if host.endswith("/panel"):
        host = host[: -len("/panel")]
        logger.warning("XUI_HOST содержит /panel — убран суффикс. URL: {}", host)
    return host


def build_sub_link(sub_id: str) -> str:
    if settings.SUBSCRIPTION_BASE_URL:
        base = settings.SUBSCRIPTION_BASE_URL.rstrip("/")
        return f"{base}/{sub_id}"
    base = normalize_xui_host(settings.XUI_HOST).rstrip("/")
    return f"{base}/sub/{sub_id}"


async def get_api() -> AsyncApi:
    global _api
    if _api is None:
        host = normalize_xui_host(settings.XUI_HOST)
        if settings.XUI_TOKEN:
            _api = AsyncApi(host, token=settings.XUI_TOKEN, use_tls_verify=True)
        else:
            _api = AsyncApi(
                host, settings.XUI_USERNAME, settings.XUI_PASSWORD, use_tls_verify=True,
            )
            await _api.login()
        logger.info("Connected to 3x-ui at {}", host)
    return _api


async def _throttle() -> None:
    delay = settings.XUI_REQUEST_DELAY_MS / 1000
    if delay > 0:
        await asyncio.sleep(delay)


def _is_not_found_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "record not found" in msg or "not found" in msg


def _bot_group() -> str:
    return (settings.XUI_CLIENT_GROUP or "").strip()


async def ensure_bot_group() -> str:
    """Один раз при старте бота — не в hot-path оплаты."""
    global _bot_group_ensured
    group = _bot_group()
    if not group or _bot_group_ensured:
        return group

    api = await get_api()
    names: set[str] = set()
    url = api.client._url("panel/api/clients/groups")
    await _throttle()
    try:
        resp = await api.client._get(url, {"Accept": "application/json"})
        for item in resp.json().get(ApiFields.OBJ) or []:
            if isinstance(item, dict) and item.get("name"):
                names.add(str(item["name"]))
    except Exception as e:
        logger.warning("Не удалось получить список групп: {}", e)
        return group

    if group not in names:
        create_url = api.client._url("panel/api/clients/groups/create")
        await _throttle()
        try:
            await api.client._post(create_url, {"Accept": "application/json"}, {"name": group})
            logger.info("Создана группа {} на панели", group)
        except Exception as e:
            if not _is_not_found_error(e):
                logger.warning("Не удалось создать группу {}: {}", group, e)

    _bot_group_ensured = True
    return group


async def _assign_client_group(api: AsyncApi, email: str) -> bool:
    """Привязать клиента к группе бота через groups/bulkAdd (видно в UI панели)."""
    _assert_bot_client_email(email)
    group = _bot_group()
    if not group:
        return False

    url = api.client._url("panel/api/clients/groups/bulkAdd")
    await _throttle()
    try:
        resp = await api.client._post(
            url, {"Accept": "application/json"}, {"group": group, "emails": [email]},
        )
        data = resp.json()
        if not data.get(ApiFields.SUCCESS):
            logger.warning("groups/bulkAdd {} → {}: {}", email, group, data.get(ApiFields.MSG))
            return False
        affected = (data.get(ApiFields.OBJ) or {}).get("affected", 0)
        panel_cache.invalidate()
        logger.success("groups/bulkAdd {} → {} (affected={})", email, group, affected)
        return affected > 0
    except Exception as e:
        logger.warning("groups/bulkAdd {} → {}: {}", email, group, e)
        return False


async def _unified_get_client_info(
    api: AsyncApi, email: str,
) -> Optional[Tuple[Client, list[int], str]]:
    endpoint = f"panel/api/clients/get/{email}"
    url = api.client._url(endpoint)
    await _throttle()
    try:
        resp = await api.client._get(url, {"Accept": "application/json"})
    except Exception as e:
        if _is_not_found_error(e):
            return None
        raise

    obj = resp.json().get(ApiFields.OBJ)
    if not obj:
        return None

    if isinstance(obj, dict) and isinstance(obj.get("client"), dict):
        client_payload = dict(obj["client"])
        inbound_ids = obj.get("inboundIds") or []
        group = str(client_payload.get("group") or "")
        if isinstance(inbound_ids, list) and inbound_ids:
            client_payload.setdefault("inboundId", inbound_ids[0])
        return Client.model_validate(client_payload), [int(x) for x in inbound_ids], group

    if isinstance(obj, dict):
        return Client.model_validate(obj), [], str(obj.get("group") or "")

    return None


def _unified_add_client_body(
    *,
    email: str,
    expiry_time: int,
    total_gb: int = 0,
    sub_id: str = "",
    enable: bool = True,
    limit_ip: int = 0,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "email": email,
        "totalGB": total_gb,
        "expiryTime": expiry_time,
        "tgId": _tg_id_from_email(email),
        "limitIp": limit_ip,
        "enable": enable,
    }
    if sub_id:
        body["subId"] = sub_id
    group = _bot_group()
    if group:
        body["group"] = group
    return body


async def _unified_add_client(
    api: AsyncApi,
    *,
    email: str,
    sub_id: str,
    expiry_time: int,
    total_gb: int,
    inbound_ids: list[int],
) -> Client:
    _assert_bot_client_email(email)
    payload = _unified_add_client_body(
        email=email, expiry_time=expiry_time, total_gb=total_gb, sub_id=sub_id,
    )
    url = api.client._url("panel/api/clients/add")
    await _throttle()
    await api.client._post(url, {"Accept": "application/json"}, {
        "client": payload,
        "inboundIds": inbound_ids,
    })
    logger.success(
        "clients/add {} → inboundIds {} (subId={}, group={})",
        email, inbound_ids, sub_id, payload.get("group") or "—",
    )
    await _assign_client_group(api, email)
    panel_cache.invalidate()
    return Client.model_validate(payload)


async def _unified_update_client(api: AsyncApi, client: Client, **overrides: Any) -> None:
    _assert_bot_client_email(client.email)
    expiry = overrides.get("expiryTime", overrides.get("expiry_time", client.expiry_time or 0))
    sub = overrides.get("subId", overrides.get("sub_id", client.sub_id or ""))
    data: dict[str, Any] = {
        "email": client.email,
        "totalGB": int(overrides.get("totalGB", overrides.get("total_gb", client.total_gb or 0))),
        "expiryTime": int(expiry),
        "tgId": _tg_id_from_email(client.email),
        "enable": bool(overrides.get("enable", client.enable)),
    }
    if sub:
        data["subId"] = str(sub)
    group = overrides.get("group") or _bot_group()
    if group:
        data["group"] = str(group)

    url = api.client._url(f"panel/api/clients/update/{client.email}")
    await _throttle()
    await api.client._post(url, {"Accept": "application/json"}, data)
    await _assign_client_group(api, client.email)
    panel_cache.invalidate()
    logger.debug("clients/update {} expiry={}", client.email, data.get("expiryTime"))


async def _set_client_expiry_on_panel(
    api: AsyncApi, email: str, expiry_time: int, sub_id: str,
) -> None:
    info = await _unified_get_client_info(api, email)
    if not info:
        raise ValueError(f"Клиент {email} не найден для обновления expiry")
    client, _, _ = info
    await _unified_update_client(
        api, client, expiryTime=expiry_time, subId=sub_id or client.sub_id or "", enable=True,
    )
    logger.success("clients/update {} expiry={}", email, expiry_time)


async def _unified_attach(api: AsyncApi, email: str, inbound_ids: list[int]) -> None:
    if not inbound_ids:
        return
    _assert_bot_client_email(email)
    if not await _unified_get_client_info(api, email):
        logger.warning("clients/attach пропущен — {} не найден в unified API", email)
        return
    url = api.client._url(f"panel/api/clients/{email}/attach")
    await _throttle()
    try:
        await api.client._post(url, {"Accept": "application/json"}, {"inboundIds": inbound_ids})
    except Exception as e:
        if _is_not_found_error(e):
            logger.warning("clients/attach {} → {}: клиент не найден", email, inbound_ids)
            return
        raise
    panel_cache.invalidate()
    logger.info("clients/attach {} → {}", email, inbound_ids)


async def _unified_detach(api: AsyncApi, email: str, inbound_ids: list[int]) -> None:
    if not inbound_ids:
        return
    _assert_bot_client_email(email)
    url = api.client._url(f"panel/api/clients/{email}/detach")
    await _throttle()
    await api.client._post(url, {"Accept": "application/json"}, {"inboundIds": inbound_ids})
    panel_cache.invalidate()
    logger.info("clients/detach {} → {}", email, inbound_ids)


async def _delete_client_by_email(api: AsyncApi, email: str) -> None:
    _assert_bot_client_email(email)
    url = api.client._url(f"panel/api/clients/del/{email}")
    await _throttle()
    try:
        await api.client._post(url, {"Accept": "application/json"}, {})
    except Exception as e:
        if _is_not_found_error(e):
            panel_cache.invalidate()
            return
        info = await _unified_get_client_info(api, email)
        if not info and not panel_cache.locate(email):
            panel_cache.invalidate()
            return
        raise
    panel_cache.invalidate()
    logger.info("clients/del {}", email)


async def _remove_email_from_inbound_settings(
    api: AsyncApi, email: str, inbound_id: int,
) -> bool:
    """Убрать клиента из settings инбаунда → SyncInbound на подключённых нодах."""
    _assert_bot_client_email(email)
    inbound = await api.inbound.get_by_id(inbound_id)
    clients = list(inbound.settings.clients or [])
    filtered = [c for c in clients if (c.email or "").lower() != email.lower()]
    if len(filtered) == len(clients):
        return False
    inbound.settings.clients = filtered
    await _throttle()
    await api.inbound.update(inbound_id, inbound)
    panel_cache.invalidate()
    logger.info("settings purge {} из inbound {}", email, inbound_id)
    return True


async def _purge_email_from_all_inbound_settings(api: AsyncApi, email: str) -> list[int]:
    """clients/del не всегда снимает клиента с нод — чистим settings всех инбаундов."""
    _assert_bot_client_email(email)
    inbounds = await panel_cache.refresh(api, force=True)
    purged: list[int] = []
    for inbound in inbounds:
        clients = inbound.settings.clients or []
        if any((c.email or "").lower() == email.lower() for c in clients):
            if await _remove_email_from_inbound_settings(api, email, inbound.id):
                purged.append(inbound.id)
    if purged:
        logger.warning(
            "Ghost {} оставался в settings inbounds {} — удалён (sync на ноды)",
            email, purged,
        )
    return purged


async def _ensure_email_absent_on_panel(api: AsyncApi, email: str) -> list[int]:
    """Полная очистка перед add: unified del + settings всех инбаундов."""
    await _delete_client_by_email(api, email)
    purged = await _purge_email_from_all_inbound_settings(api, email)
    if purged:
        await asyncio.sleep(0.5)
    return purged


async def _locate_client_inbounds(
    api: AsyncApi, email: str, *, force: bool = False,
) -> dict[int, Client]:
    await panel_cache.refresh(api, force=force)
    return panel_cache.locate(email)


async def _missing_inbound_ids(
    api: AsyncApi, email: str, inbound_ids: list[int], *, force: bool = False,
) -> list[int]:
    located = await _locate_client_inbounds(api, email, force=force)
    return [ib for ib in inbound_ids if ib not in located]


async def _attach_if_missing(
    api: AsyncApi, email: str, inbound_ids: list[int], *, force: bool = False,
) -> list[int]:
    missing = await _missing_inbound_ids(api, email, inbound_ids, force=force)
    if missing:
        await _unified_attach(api, email, missing)
    return missing


async def get_inbound_port_conflict_groups(
    inbound_ids: Optional[list[int]] = None,
) -> dict[int, list[int]]:
    if inbound_ids is None:
        inbound_ids = await get_subscription_inbound_ids()
    api = await get_api()
    inbounds = await panel_cache.refresh(api)
    id_set = set(inbound_ids)
    by_port: dict[int, list[int]] = {}
    for inbound in inbounds:
        if inbound.id in id_set:
            by_port.setdefault(inbound.port, []).append(inbound.id)
    return {port: ids for port, ids in by_port.items() if len(ids) > 1}


async def log_inbound_port_conflicts() -> None:
    conflicts = await get_inbound_port_conflict_groups()
    for port, ids in conflicts.items():
        logger.info("Инбаунды {} на порту {}", ids, port)


def _client_needs_update(
    client: Client,
    *,
    expiry_time: int,
    sub_id: str,
    enable: bool = True,
    expiry_tolerance_ms: int = 60_000,
) -> bool:
    if client.enable != enable:
        return True
    if abs((client.expiry_time or 0) - expiry_time) > expiry_tolerance_ms:
        return True
    if sub_id and (client.sub_id or "") != sub_id:
        return True
    return False


async def _find_reference_client(api: AsyncApi, email: str) -> Optional[Client]:
    """Для оплаты/продления — только unified GET, без кэша инбаундов."""
    info = await _unified_get_client_info(api, email)
    return info[0] if info else None


async def get_unified_panel_client(email: str) -> Optional[Client]:
    api = await get_api()
    return await _find_reference_client(api, email)


async def _purge_extra_inbounds(
    api: AsyncApi, email: str, allowed_inbound_ids: list[int],
) -> list[int]:
    if not await _unified_get_client_info(api, email):
        return []
    located = await _locate_client_inbounds(api, email, force=False)
    extra = [ib for ib in located if ib not in set(allowed_inbound_ids)]
    if extra:
        await _unified_detach(api, email, extra)
    return extra


async def _ensure_clients(
    api: AsyncApi,
    email: str,
    inbound_ids: list[int],
    *,
    expiry_time: int,
    total_gb: int,
    sub_id: str,
    purge_extra: bool,
) -> dict[str, int]:
    stats = {"skip": 0, "update": 0, "create": 0, "purge": 0}
    allowed = set(inbound_ids)

    info = await _unified_get_client_info(api, email)

    if info is None:
        try:
            await _unified_add_client(
                api, email=email, sub_id=sub_id, expiry_time=expiry_time,
                total_gb=total_gb, inbound_ids=inbound_ids,
            )
        except ValueError as e:
            if "duplicate email" in str(e).lower():
                logger.warning("Дубликат {} — clients/del и повторный add", email)
                await _delete_client_by_email(api, email)
                await asyncio.sleep(0.5)
                await _unified_add_client(
                    api, email=email, sub_id=sub_id, expiry_time=expiry_time,
                    total_gb=total_gb, inbound_ids=inbound_ids,
                )
            else:
                raise
        stats["create"] = len(inbound_ids)
        await panel_cache.refresh(api, force=True)
        return stats

    client, _, _ = info

    if purge_extra:
        extra = await _purge_extra_inbounds(api, email, inbound_ids)
        stats["purge"] = len(extra)

    panel_expiry = client.expiry_time or 0
    needs_update = _client_needs_update(client, expiry_time=expiry_time, sub_id=sub_id)
    if not needs_update and expiry_time > panel_expiry:
        needs_update = True

    if needs_update:
        await _set_client_expiry_on_panel(api, email, expiry_time, sub_id)
        stats["update"] = len(inbound_ids)
    else:
        stats["skip"] = len(inbound_ids)

    await panel_cache.refresh(api, force=True)
    return stats


def _audit_from_located(
    email: str, inbound_ids: list[int], located: dict[int, Client],
) -> dict:
    allowed_set = set(inbound_ids)
    return {
        "allowed": inbound_ids,
        "present_allowed": [ib for ib in inbound_ids if ib in located],
        "missing_allowed": [ib for ib in inbound_ids if ib not in located],
        "extra": [ib for ib in located if ib not in allowed_set],
    }


def _needs_sync(
    located: dict[int, Client], inbound_ids: list[int], *, expiry_time: int, sub_id: str,
) -> bool:
    if any(ib not in set(inbound_ids) for ib in located):
        return True
    for ib_id in inbound_ids:
        client = located.get(ib_id)
        if not client or _client_needs_update(client, expiry_time=expiry_time, sub_id=sub_id):
            return True
    return False


async def audit_client_inbounds(email: str) -> dict:
    api = await get_api()
    inbound_ids = await get_subscription_inbound_ids()
    located = await _locate_client_inbounds(api, email, force=False)
    return _audit_from_located(email, inbound_ids, located)


async def get_panel_client_for_sync(email: str) -> Optional[Client]:
    return await get_unified_panel_client(email)


async def repair_client_inbounds(
    email: str,
    *,
    sub_id: str,
    expiry_time: int,
    total_gb: int = 0,
    attach_only: bool = False,
) -> dict[str, int]:
    api = await get_api()
    inbound_ids = await get_subscription_inbound_ids()

    if attach_only:
        logger.debug("Attach-only пропущен для {} — не используем attach-циклы", email)
        return {"skip": len(inbound_ids), "update": 0, "create": 0, "purge": 0}

    info = await _unified_get_client_info(api, email)
    if info is None:
        try:
            await _unified_add_client(
                api,
                email=email,
                sub_id=sub_id,
                expiry_time=expiry_time,
                total_gb=total_gb,
                inbound_ids=inbound_ids,
            )
        except ValueError as e:
            if "duplicate email" not in str(e).lower():
                raise
            await _delete_client_by_email(api, email)
            await asyncio.sleep(0.5)
            await _unified_add_client(
                api,
                email=email,
                sub_id=sub_id,
                expiry_time=expiry_time,
                total_gb=total_gb,
                inbound_ids=inbound_ids,
            )
        return {"skip": 0, "update": 0, "create": len(inbound_ids), "purge": 0}

    located = await _locate_client_inbounds(api, email, force=False)
    extra = [ib for ib in located if ib not in set(inbound_ids)]
    if extra:
        await _unified_detach(api, email, extra)
        return {"skip": 0, "update": 0, "create": 0, "purge": len(extra)}

    client, _, _ = info
    if _client_needs_update(client, expiry_time=expiry_time, sub_id=sub_id):
        await _set_client_expiry_on_panel(api, email, expiry_time, sub_id)
        return {"skip": 0, "update": len(inbound_ids), "create": 0, "purge": 0}

    return {"skip": len(inbound_ids), "update": 0, "create": 0, "purge": 0}


async def provision_client(
    tg_id: int,
    plan_days: int,
    traffic_gb: int = 0,
    *,
    sub_id: Optional[str] = None,
    target_expiry_ms: Optional[int] = None,
    client_email: Optional[str] = None,
) -> Tuple[str, str, Optional[str]]:
    """Новая подписка — только POST clients/add + inboundIds из настроек."""
    api = await get_api()
    email = client_email or f"tg{tg_id}"
    _assert_bot_client_email(email)
    inbound_ids = await get_subscription_inbound_ids()
    if not inbound_ids:
        raise ValueError("Нет инбаундов для создания подписки")

    total_gb = traffic_gb * 1024 * 1024 * 1024 if traffic_gb > 0 else 0
    resolved_sub_id = sub_id or secrets.token_urlsafe(12)[:16]
    if target_expiry_ms is not None:
        expiry_time = target_expiry_ms
    else:
        expiry_time = int((datetime.utcnow() + timedelta(days=plan_days)).timestamp() * 1000)

    await _ensure_email_absent_on_panel(api, email)
    try:
        await _unified_add_client(
            api,
            email=email,
            sub_id=resolved_sub_id,
            expiry_time=expiry_time,
            total_gb=total_gb,
            inbound_ids=inbound_ids,
        )
    except ValueError as e:
        if "duplicate email" not in str(e).lower():
            raise
        logger.warning("Дубликат {} — повторная очистка и add", email)
        await _ensure_email_absent_on_panel(api, email)
        await _unified_add_client(
            api,
            email=email,
            sub_id=resolved_sub_id,
            expiry_time=expiry_time,
            total_gb=total_gb,
            inbound_ids=inbound_ids,
        )

    return email, resolved_sub_id, build_sub_link(resolved_sub_id)


async def extend_client(
    email: str,
    additional_days: int,
    inbound_id: Optional[int] = None,
    *,
    target_expiry_ms: Optional[int] = None,
    min_base_ms: Optional[int] = None,
) -> int:
    api = await get_api()
    inbound_ids = await get_subscription_inbound_ids()
    if inbound_id and inbound_id not in inbound_ids:
        inbound_ids = [inbound_id]

    reference = await _find_reference_client(api, email)
    if not reference:
        raise ValueError(f"Клиент {email} не найден в 3x-ui")

    now_ms = int(datetime.utcnow().timestamp() * 1000)
    sub_id = reference.sub_id or secrets.token_urlsafe(12)[:16]

    if target_expiry_ms is not None:
        new_expiry = target_expiry_ms
    else:
        current_expiry = reference.expiry_time or 0
        base_ms = current_expiry if current_expiry > now_ms else now_ms
        if min_base_ms and min_base_ms > base_ms:
            base_ms = min_base_ms
        new_expiry = base_ms + additional_days * 24 * 60 * 60 * 1000

    logger.info("Продление {}: expiry {} ms", email, new_expiry)
    await _set_client_expiry_on_panel(api, email, new_expiry, sub_id)
    return new_expiry


async def remove_client_everywhere(email: str) -> list[int]:
    _assert_bot_client_email(email)
    api = await get_api()
    located = await _locate_client_inbounds(api, email, force=False)
    if (
        not located
        and not await _unified_get_client_info(api, email)
        and not any(
            (c.email or "").lower() == email.lower()
            for ib in (await panel_cache.refresh(api, force=True))
            for c in (ib.settings.clients or [])
        )
    ):
        return []
    removed = set(located.keys())
    purged = await _ensure_email_absent_on_panel(api, email)
    removed.update(purged)
    await panel_cache.refresh(api, force=True)
    remaining = panel_cache.locate(email)
    if remaining:
        logger.warning(
            "После удаления {} остался в inbounds {}",
            email, sorted(remaining.keys()),
        )
    return sorted(removed)


async def disable_client(email: str, inbound_id: Optional[int] = None):
    api = await get_api()
    try:
        info = await _unified_get_client_info(api, email)
        if not info:
            return
        client, _, _ = info
        if client.enable:
            await _unified_update_client(api, client, enable=False)
            logger.info("Disabled client {}", email)
    except Exception as e:
        logger.error("Failed to disable client {}: {}", email, e)