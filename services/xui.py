"""
Unified client API 3x-ui 3.2+ (report/api.txt).

  POST clients/add + inboundIds  — новая подписка
  POST clients/update/{email}    — продление / disable
  POST clients/groups/bulkAdd    — привязка группы (UI панели)
  POST clients/del/{email}       — удаление tg*
  POST clients/delDepleted       — все истёкшие / исчерпавшие трафик
  POST clients/delOrphans        — без привязки к inbound (+ мусор трафика/IP)
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
from services.panel_cache import get_panel_cache, invalidate_panel_cache, panel_cache
from services.panel_inbounds import fetch_inbound_by_id, fetch_inbounds_list

_apis: dict[int, AsyncApi] = {}
_bot_group_ensured: set[int] = set()
_connect_logged: set[int] = set()
_BOT_CLIENT_EMAIL = re.compile(r"^tg(?:free)?\d+(?:_\d+)?$")


def is_bot_client_email(email: str) -> bool:
    return bool(_BOT_CLIENT_EMAIL.match(email or ""))


def _assert_bot_client_email(email: str) -> None:
    if not is_bot_client_email(email):
        raise ValueError(f"Запрещено: операция только для tg-клиентов бота, получено {email!r}")


def _tg_id_from_email(email: str) -> int:
    if not email:
        return 0
    body = email
    if body.startswith("tgfree"):
        body = body[6:]
    elif body.startswith("tg"):
        body = body[2:]
    else:
        return 0
    if "_" in body:
        body = body.split("_", 1)[0]
    return int(body)


def normalize_xui_host(host: str) -> str:
    host = host.strip().rstrip("/")
    if host.endswith("/panel"):
        host = host[: -len("/panel")]
        logger.warning("XUI_HOST содержит /panel — убран суффикс. URL: {}", host)
    return host


def _node_host_key(node: dict) -> str:
    return normalize_xui_host(node.get("host") or "").lower()


def _dedupe_nodes_by_host(nodes: list[dict]) -> list[dict]:
    """Одна панель — один проход (дубликаты записей в xui_nodes игнорируются)."""
    seen: set[str] = set()
    unique: list[dict] = []
    for node in nodes:
        key = _node_host_key(node)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(node)
    return unique


async def build_plain_sub_link(sub_id: str) -> str:
    """Обычная HTTPS-ссылка на подписку (без Happ crypto)."""
    if settings.SUBSCRIPTION_BASE_URL:
        base = settings.SUBSCRIPTION_BASE_URL.rstrip("/")
        return f"{base}/{sub_id}"
    try:
        from db.xui_nodes import get_primary_node
        primary = await get_primary_node()
        if primary and primary.get("host"):
            base = normalize_xui_host(primary["host"]).rstrip("/")
            return f"{base}/sub/{sub_id}"
    except Exception:
        pass
    base = normalize_xui_host(settings.XUI_HOST).rstrip("/")
    return f"{base}/sub/{sub_id}"


async def build_sub_link(sub_id: str) -> str:
    """Ссылка для клиента: plain или happ://crypt3|crypt5/… по настройке шифрования."""
    from services.happ_crypto import encrypt_happ_subscription_link

    plain = await build_plain_sub_link(sub_id)
    return await encrypt_happ_subscription_link(plain)


def invalidate_api_cache(node_id: int) -> None:
    _apis.pop(node_id, None)
    _bot_group_ensured.discard(node_id)
    _connect_logged.discard(node_id)


async def _probe_panel_read_api(api: AsyncApi) -> bool:
    """Проверка чтения панели: inbounds/list или unified clients/list."""
    try:
        await fetch_inbounds_list(api)
        return True
    except Exception:
        pass
    url = api.client._url("panel/api/clients/list")
    await _throttle()
    try:
        resp = await api.client._get(url, {"Accept": "application/json"})
        data = resp.json()
        return bool(data.get(ApiFields.SUCCESS, True))
    except Exception:
        return False


async def get_api_for_node(node: dict, *, force_new: bool = False) -> AsyncApi:
    node_id = int(node.get("id") or 0)
    if force_new:
        invalidate_api_cache(node_id)
    if node_id not in _apis:
        host = normalize_xui_host(node["host"])
        token = (node.get("token") or "").strip()
        username = (node.get("username") or "").strip()
        password = node.get("password") or ""
        api: AsyncApi | None = None

        if token:
            api = AsyncApi(host, token=token, use_tls_verify=True)
            if not await _probe_panel_read_api(api) and username and password:
                logger.warning(
                    "Token API недоступен для [{}], пробуем login/password",
                    node.get("name") or node_id,
                )
                api = None

        if api is None:
            if not username or not password:
                raise ValueError(
                    f"Нода {node.get('name') or node_id}: укажите API token или login/password",
                )
            api = AsyncApi(host, username, password, use_tls_verify=True)
            await api.login()
            if not await _probe_panel_read_api(api):
                logger.warning(
                    "Панель [{}] отвечает, но inbounds/list и clients/list недоступны",
                    node.get("name") or node_id,
                )

        _apis[node_id] = api
        name = node.get("name") or node_id
        if node_id not in _connect_logged:
            _connect_logged.add(node_id)
            logger.info("Connected to 3x-ui [{}] at {}", name, host)
        else:
            logger.debug("Reconnected to 3x-ui [{}] at {}", name, host)
    return _apis[node_id]


async def get_api() -> AsyncApi:
    try:
        from db.xui_nodes import get_primary_node
        primary = await get_primary_node()
        if primary:
            return await get_api_for_node(primary)
    except Exception:
        pass
    fallback = {
        "id": 0,
        "name": "env",
        "host": settings.XUI_HOST,
        "username": settings.XUI_USERNAME or "",
        "password": settings.XUI_PASSWORD or "",
        "token": settings.XUI_TOKEN or "",
    }
    return await get_api_for_node(fallback)


async def _throttle() -> None:
    delay = settings.XUI_REQUEST_DELAY_MS / 1000
    if delay > 0:
        await asyncio.sleep(delay)


def _is_not_found_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "record not found" in msg or "not found" in msg


def _is_port_conflict_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "port" in msg and "already used" in msg


def _bot_group() -> str:
    return (settings.XUI_CLIENT_GROUP or "").strip()


async def ensure_bot_group_on_node(api: AsyncApi, node_id: int = 0) -> str:
    """Создать группу бота на панели ноды (идемпотентно)."""
    group = _bot_group()
    if not group or node_id in _bot_group_ensured:
        return group
    try:
        names: set[str] = set()
        url = api.client._url("panel/api/clients/groups")
        await _throttle()
        try:
            resp = await api.client._get(url, {"Accept": "application/json"})
            for item in resp.json().get(ApiFields.OBJ) or []:
                if isinstance(item, dict) and item.get("name"):
                    names.add(str(item["name"]))
        except Exception as e:
            if _is_not_found_error(e):
                logger.debug("groups API недоступен на панели — пропуск")
            else:
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
    finally:
        _bot_group_ensured.add(node_id)
    return group


async def ensure_bot_group() -> str:
    """Один раз при старте бота на основной ноде."""
    api = await get_api()
    try:
        from db.xui_nodes import get_primary_node
        primary = await get_primary_node()
        node_id = int((primary or {}).get("id") or 0)
    except Exception:
        node_id = 0
    return await ensure_bot_group_on_node(api, node_id)


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
    enable: bool = True,
    limit_ip: int = 0,
) -> Client:
    _assert_bot_client_email(email)
    payload = _unified_add_client_body(
        email=email,
        expiry_time=expiry_time,
        total_gb=total_gb,
        sub_id=sub_id,
        enable=enable,
        limit_ip=limit_ip,
    )
    url = api.client._url("panel/api/clients/add")
    await _throttle()
    await api.client._post(url, {"Accept": "application/json"}, {
        "client": payload,
        "inboundIds": inbound_ids,
    })
    logger.success(
        "clients/add {} → inboundIds {} expiryTime={} (subId={}, group={})",
        email, inbound_ids, expiry_time, sub_id, payload.get("group") or "—",
    )
    await _assign_client_group(api, email)
    panel_cache.invalidate()
    return Client.model_validate(payload)


async def _unified_update_client(api: AsyncApi, client: Client, **overrides: Any) -> None:
    _assert_bot_client_email(client.email)
    expiry = overrides.get("expiryTime", overrides.get("expiry_time", client.expiry_time or 0))
    sub = overrides.get("subId", overrides.get("sub_id", client.sub_id or ""))
    limit_ip = overrides.get("limitIp", overrides.get("limit_ip"))
    if limit_ip is None:
        limit_ip = client.limit_ip or 0
    data: dict[str, Any] = {
        "email": client.email,
        "totalGB": int(overrides.get("totalGB", overrides.get("total_gb", client.total_gb or 0))),
        "expiryTime": int(expiry),
        "tgId": _tg_id_from_email(client.email),
        "limitIp": int(limit_ip),
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
    *,
    limit_ip: int | None = None,
) -> None:
    from services.limit_ip import resolve_limit_ip_for_email

    info = await _unified_get_client_info(api, email)
    if not info:
        raise ValueError(f"Клиент {email} не найден для обновления expiry")
    client, _, _ = info
    resolved_limit = limit_ip if limit_ip is not None else await resolve_limit_ip_for_email(email)
    await _unified_update_client(
        api,
        client,
        expiryTime=expiry_time,
        subId=sub_id or client.sub_id or "",
        enable=True,
        limitIp=resolved_limit,
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


def _parse_bulk_delete_count(response: Any) -> int:
    try:
        body = response.json()
    except Exception:
        return 0
    if not isinstance(body, dict):
        return 0
    obj = body.get("obj")
    if isinstance(obj, bool):
        return 0
    if isinstance(obj, int):
        return max(0, obj)
    if isinstance(obj, dict):
        for key in ("count", "deleted", "deletedCount", "num"):
            if key in obj:
                try:
                    return max(0, int(obj[key]))
                except (TypeError, ValueError):
                    continue
    for key in ("count", "deleted"):
        if key in body:
            try:
                return max(0, int(body[key]))
            except (TypeError, ValueError):
                continue
    return 0


async def delete_depleted_clients_on_panel(api: AsyncApi) -> int:
    """Удалить на панели всех клиентов с истёкшим сроком или исчерпанным трафиком."""
    url = api.client._url("panel/api/clients/delDepleted")
    await _throttle()
    response = await api.client._post(url, {"Accept": "application/json"}, {})
    panel_cache.invalidate()
    deleted = _parse_bulk_delete_count(response)
    logger.info("clients/delDepleted → удалено {}", deleted)
    return deleted


async def delete_orphan_clients_on_panel(api: AsyncApi) -> int:
    """Удалить клиентов без attach к inbound (delOrphans)."""
    url = api.client._url("panel/api/clients/delOrphans")
    await _throttle()
    response = await api.client._post(url, {"Accept": "application/json"}, {})
    panel_cache.invalidate()
    deleted = _parse_bulk_delete_count(response)
    logger.info("clients/delOrphans → удалено {}", deleted)
    return deleted


async def delete_orphan_clients_on_nodes(
    nodes: list[dict],
    *,
    label: str = "nodes",
) -> dict[str, Any]:
    """POST clients/delOrphans на указанных нодах."""
    nodes = _dedupe_nodes_by_host(nodes)
    stats: dict[str, Any] = {
        "nodes": len(nodes),
        "deleted": 0,
        "failed": 0,
        "by_node": {},
    }
    if not nodes:
        return stats
    sem = asyncio.Semaphore(settings.XUI_PANEL_CONCURRENCY)

    async def _one(node: dict) -> None:
        nid = int(node.get("id") or 0)
        async with sem:
            try:
                api = await get_api_for_node(node) if node.get("host") else await get_api()
                removed = await delete_orphan_clients_on_panel(api)
                stats["by_node"][nid] = removed
                stats["deleted"] += removed
            except Exception as e:
                stats["failed"] += 1
                stats["by_node"][nid] = None
                logger.error("clients/delOrphans на {} {}: {}", label, nid, e)

    await asyncio.gather(*[_one(node) for node in nodes])
    return stats


async def delete_depleted_clients_everywhere() -> dict[str, Any]:
    """POST clients/delDepleted на каждой включённой ноде."""
    from db.xui_nodes import list_nodes

    nodes = _dedupe_nodes_by_host(await list_nodes(enabled_only=True))
    if not nodes:
        nodes = [{"id": 0, "host": settings.XUI_HOST}]
    stats: dict[str, Any] = {
        "nodes": len(nodes),
        "deleted": 0,
        "failed": 0,
        "by_node": {},
    }
    sem = asyncio.Semaphore(settings.XUI_PANEL_CONCURRENCY)

    async def _one(node: dict) -> None:
        nid = int(node.get("id") or 0)
        async with sem:
            try:
                api = await get_api_for_node(node) if node.get("host") else await get_api()
                removed = await delete_depleted_clients_on_panel(api)
                stats["by_node"][nid] = removed
                stats["deleted"] += removed
            except Exception as e:
                stats["failed"] += 1
                stats["by_node"][nid] = None
                logger.error("clients/delDepleted на ноде {}: {}", nid, e)

    await asyncio.gather(*[_one(node) for node in nodes])
    return stats


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
    inbound = await fetch_inbound_by_id(api, inbound_id)
    clients = list(inbound.settings.clients or [])
    filtered = [c for c in clients if (c.email or "").lower() != email.lower()]
    if len(filtered) == len(clients):
        return False
    inbound.settings.clients = filtered
    await _throttle()
    try:
        await api.inbound.update(inbound_id, inbound)
    except Exception as e:
        if _is_port_conflict_error(e):
            logger.warning(
                "settings purge {} из inbound {} пропущен (same-port): {}",
                email, inbound_id, e,
            )
            panel_cache.invalidate()
            return False
        raise
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
    """Полная очистка перед add: unified del + settings всех инбаундов (только если есть следы)."""
    if not await _is_client_present_on_panel(api, email):
        return []
    return await _purge_client_from_panel(api, email)


async def _locate_client_inbounds(
    api: AsyncApi, email: str, *, force: bool = False,
) -> dict[int, Client]:
    cache = get_panel_cache(api)
    await cache.refresh(api, force=force)
    return cache.locate(email)


async def _is_client_present_on_panel(api: AsyncApi, email: str) -> bool:
    """Следы клиента на панели (unified, кэш инбаундов, groups) — без clients/del."""
    _assert_bot_client_email(email)
    key = email.lower()
    if await _unified_get_client_info(api, email):
        return True
    if await _locate_client_inbounds(api, email, force=False):
        return True
    cache = get_panel_cache(api)
    for inbound in await cache.refresh(api, force=False):
        for client in inbound.settings.clients or []:
            if (client.email or "").lower() == key:
                return True
    if key in await _list_bot_group_emails_on_panel(api):
        return True
    return False


async def _purge_client_from_panel(
    api: AsyncApi,
    email: str,
    *,
    inbound_ids: list[int] | None = None,
) -> list[int]:
    """clients/del + settings purge (вызывать только если клиент найден на панели)."""
    panel_cache.invalidate()
    await _delete_client_by_email(api, email)
    purged: list[int] = []
    try:
        if inbound_ids:
            for iid in inbound_ids:
                if await _remove_email_from_inbound_settings(api, email, iid):
                    purged.append(iid)
        else:
            purged = await _purge_email_from_all_inbound_settings(api, email)
    except Exception as e:
        logger.warning("settings purge {} на панели: {}", email, e)
        purged = []
    if purged:
        await asyncio.sleep(0.5)
    panel_cache.invalidate()
    return sorted(set(purged))


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
    try:
        conflicts = await get_inbound_port_conflict_groups()
    except Exception as e:
        logger.warning("Не удалось проверить конфликты портов инбаундов: {}", e)
        return
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


async def _fetch_sub_links(
    api: AsyncApi,
    sub_id: str,
    email: str,
) -> list[Any]:
    """Фактические ссылки подписки — надёжнее settings при same-port drift."""
    for endpoint in (
        f"panel/api/clients/subLinks/{sub_id}",
        f"panel/api/clients/links/{email}",
    ):
        url = api.client._url(endpoint)
        await _throttle()
        try:
            resp = await api.client._get(url, {"Accept": "application/json"})
            obj = resp.json().get(ApiFields.OBJ)
            if isinstance(obj, list):
                return obj
            if isinstance(obj, dict):
                links = obj.get("links") or obj.get("subs") or []
                if isinstance(links, list):
                    return links
        except Exception as e:
            if not _is_not_found_error(e):
                logger.debug("subLinks {}: {}", endpoint, e)
    return []


async def get_missing_required_inbounds(
    api: AsyncApi,
    email: str,
    *,
    sub_id: str = "",
) -> list[int]:
    """
    Нехватка инбаундов: unified inboundIds и subLinks (не settings — там ghost на same-port).
    """
    inbound_ids = await get_subscription_inbound_ids()
    if not inbound_ids:
        return []

    required = set(inbound_ids)
    info = await _unified_get_client_info(api, email)
    if not info:
        return sorted(required)

    client, unified_ids, _ = info
    unified_set = set(unified_ids or [])
    missing = sorted(required - unified_set)

    resolved_sub = (sub_id or client.sub_id or "").strip()
    link_count = 0
    if resolved_sub:
        links = await _fetch_sub_links(api, resolved_sub, email)
        link_count = len(links)
        if link_count and link_count < len(required):
            logger.info(
                "Инбаунды {}: subLinks={} < required={} (unified={}) — нужно пересоздание",
                email, link_count, sorted(required), sorted(unified_set),
            )
            return sorted(required)

    if missing:
        logger.info(
            "Инбаунды {}: unified не хватает {} (есть {}, нужно {})",
            email, missing, sorted(unified_set), sorted(required),
        )
    elif link_count:
        logger.debug(
            "Инбаунды {}: unified={} subLinks={} required={}",
            email, sorted(unified_set), link_count, sorted(required),
        )

    return missing


async def verify_client_inbounds_stable(
    api: AsyncApi,
    email: str,
    *,
    sub_id: str = "",
    settle_sec: float = 5.0,
) -> tuple[bool, list[int]]:
    """
    Проверка после add/recreate: ждём same-port drift и смотрим subLinks/unified снова.
    """
    if settle_sec > 0:
        await asyncio.sleep(settle_sec)
    panel_cache.invalidate()
    missing = await get_missing_required_inbounds(api, email, sub_id=sub_id)
    return not missing, missing


async def try_attach_missing_inbounds(
    api: AsyncApi, email: str, *, sub_id: str = "",
) -> list[int]:
    """Одна попытка attach; возвращает inbounds, которые всё ещё отсутствуют."""
    missing = await get_missing_required_inbounds(api, email, sub_id=sub_id)
    if not missing:
        return []
    try:
        await _unified_attach(api, email, missing)
        await asyncio.sleep(0.3)
        panel_cache.invalidate()
    except Exception as e:
        logger.warning("clients/attach {} → {}: {}", email, missing, e)
    return await get_missing_required_inbounds(api, email, sub_id=sub_id)


async def audit_client_inbounds(email: str) -> dict:
    api = await get_api()
    inbound_ids = await get_subscription_inbound_ids()
    located = await _locate_client_inbounds(api, email, force=False)
    return _audit_from_located(email, inbound_ids, located)


async def get_panel_client_for_sync(email: str) -> Optional[Client]:
    return await get_unified_panel_client(email)


async def update_client_limit_ip_on_primary(email: str, limit_ip: int) -> str:
    """Обновить limitIp на основной ноде. Возвращает updated | skipped | missing."""
    _assert_bot_client_email(email)
    api = await get_api()
    info = await _unified_get_client_info(api, email)
    if not info:
        return "missing"
    client, _, _ = info
    target = max(0, int(limit_ip))
    if (client.limit_ip or 0) == target:
        return "skipped"
    await _unified_update_client(api, client, limitIp=target)
    logger.info("limitIp {} → {} on primary", email, target)
    return "updated"


async def repair_client_inbounds(
    email: str,
    *,
    sub_id: str,
    expiry_time: int,
    total_gb: int = 0,
    attach_only: bool = False,
    limit_ip: int | None = None,
) -> dict[str, int]:
    from services.limit_ip import resolve_limit_ip_for_email

    api = await get_api()
    inbound_ids = await get_subscription_inbound_ids()
    resolved_limit = limit_ip if limit_ip is not None else await resolve_limit_ip_for_email(email)

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
                limit_ip=resolved_limit,
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
                limit_ip=resolved_limit,
            )
        return {"skip": 0, "update": 0, "create": len(inbound_ids), "purge": 0}

    located = await _locate_client_inbounds(api, email, force=False)
    extra = [ib for ib in located if ib not in set(inbound_ids)]
    if extra:
        await _unified_detach(api, email, extra)
        return {"skip": 0, "update": 0, "create": 0, "purge": len(extra)}

    client, _, _ = info
    if _client_needs_update(client, expiry_time=expiry_time, sub_id=sub_id) or (
        (client.limit_ip or 0) != resolved_limit
    ):
        await _set_client_expiry_on_panel(
            api, email, expiry_time, sub_id, limit_ip=resolved_limit,
        )
        return {"skip": 0, "update": len(inbound_ids), "create": 0, "purge": 0}

    return {"skip": len(inbound_ids), "update": 0, "create": 0, "purge": 0}


async def is_client_present_on_any_node(email: str) -> bool:
    """Есть ли следы клиента на любой включённой ноде."""
    from db.xui_nodes import list_nodes

    _assert_bot_client_email(email)
    nodes = _dedupe_nodes_by_host(await list_nodes(enabled_only=True))
    targets = nodes or [{"host": settings.XUI_HOST}]

    for node in targets:
        try:
            api = await get_api_for_node(node) if nodes else await get_api()
            if await _is_client_present_on_panel(api, email):
                return True
        except Exception as e:
            logger.debug(
                "Проверка {} на {}: {}",
                email, node.get("name") or node.get("host"), e,
            )
    return False


async def ensure_client_absent_everywhere(email: str) -> list[int]:
    """Полная очистка на всех нодах: clients/del + settings purge."""
    from db.xui_nodes import list_nodes

    _assert_bot_client_email(email)
    all_purged: list[int] = []
    nodes = _dedupe_nodes_by_host(await list_nodes(enabled_only=True))
    targets = nodes or [{"host": settings.XUI_HOST}]

    for node in targets:
        name = node.get("name") or node.get("host") or node.get("id")
        try:
            api = await get_api_for_node(node) if nodes else await get_api()
            purged = await _remove_client_on_node(api, email, inbound_ids=None)
            all_purged.extend(purged)
            logger.info("Очистка {} на {} (settings inbounds {})", email, name, purged or "—")
        except Exception as e:
            logger.error("Очистка {} на {} failed: {}", email, name, e)

    panel_cache.invalidate()
    return sorted(set(all_purged))


async def purge_client_on_secondaries(email: str) -> list[str]:
    """Удалить клиента с вторичных нод (призраки перед созданием на основной)."""
    from db.xui_nodes import get_secondary_nodes

    _assert_bot_client_email(email)
    purged_nodes: list[str] = []
    nodes = _dedupe_nodes_by_host(await get_secondary_nodes(healthy_only=False))

    for node in nodes:
        if not node.get("is_enabled", True):
            continue
        name = node.get("name") or str(node.get("id"))
        try:
            api = await get_api_for_node(node)
            if not await _is_client_present_on_panel(api, email):
                continue
            await remove_bot_client_on_panel(api, email)
            purged_nodes.append(name)
            logger.info("Призрак {} удалён с вторичной {}", email, name)
        except Exception as e:
            logger.error("Не удалось удалить призрак {} с {}: {}", email, name, e)

    panel_cache.invalidate()
    return purged_nodes


async def ensure_client_absent_on_primary(email: str) -> list[int]:
    """Лёгкая очистка только на основной ноде перед clients/add."""
    api = await get_api()
    return await _ensure_email_absent_on_panel(api, email)


async def reactivate_client_on_primary(
    email: str,
    *,
    sub_id: Optional[str] = None,
    expiry_time: int,
    total_gb: int = 0,
    limit_ip: int | None = None,
) -> str:
    """
    Включить существующего клиента на основной: новый срок, трафик, enable=True.
    Возвращает итоговый sub_id (сохраняется прежний, если был на панели).
    """
    api = await get_api()
    info = await _unified_get_client_info(api, email)
    if not info:
        raise ValueError(f"Клиент {email} не найден на основной для реактивации")
    from services.limit_ip import resolve_limit_ip_for_email

    client, _, _ = info
    resolved_sub_id = (sub_id or client.sub_id or "").strip() or secrets.token_urlsafe(12)[:16]
    resolved_limit = limit_ip if limit_ip is not None else await resolve_limit_ip_for_email(email)
    await _unified_update_client(
        api,
        client,
        expiryTime=expiry_time,
        totalGB=total_gb,
        subId=resolved_sub_id,
        enable=True,
        limitIp=resolved_limit,
    )
    missing = await try_attach_missing_inbounds(api, email, sub_id=resolved_sub_id)
    if missing:
        logger.warning(
            "После реактивации {} не хватает инбаундов {} — догонит синк нод",
            email, missing,
        )
    logger.success("Reactivated {} expiry={} enable=True", email, expiry_time)
    return resolved_sub_id


async def provision_client(
    tg_id: int,
    plan_days: int,
    traffic_gb: int = 0,
    *,
    sub_id: Optional[str] = None,
    target_expiry_ms: Optional[int] = None,
    client_email: Optional[str] = None,
    skip_preclean: bool = False,
) -> Tuple[str, str, Optional[str]]:
    """
    Выдача / повторная покупка:
    - клиент есть на основной → включить с новым сроком (ссылка/sub_id сохраняются);
    - нет на основной → удалить призраков на вторичных, clients/add на основной.
    """
    api = await get_api()
    email = client_email or f"tg{tg_id}"
    _assert_bot_client_email(email)
    inbound_ids = await get_subscription_inbound_ids()
    if not inbound_ids:
        raise ValueError("Нет инбаундов для создания подписки")

    total_gb = traffic_gb * 1024 * 1024 * 1024 if traffic_gb > 0 else 0
    if target_expiry_ms is not None:
        expiry_time = target_expiry_ms
    else:
        expiry_time = int((datetime.utcnow() + timedelta(days=plan_days)).timestamp() * 1000)

    from services.limit_ip import resolve_limit_ip_for_email

    limit_ip = await resolve_limit_ip_for_email(email)

    if not skip_preclean:
        info = await _unified_get_client_info(api, email)
        if info:
            resolved_sub_id = await reactivate_client_on_primary(
                email,
                sub_id=sub_id,
                expiry_time=expiry_time,
                total_gb=total_gb,
                limit_ip=limit_ip,
            )
            sub_link = await build_sub_link(resolved_sub_id)
            return email, resolved_sub_id, sub_link

    ghost_nodes = await purge_client_on_secondaries(email)
    if ghost_nodes:
        logger.info(
            "Перед созданием {}: удалены призраки на вторичных {}",
            email, ", ".join(ghost_nodes),
        )
    await ensure_client_absent_on_primary(email)

    resolved_sub_id = sub_id or secrets.token_urlsafe(12)[:16]

    async def _add() -> None:
        await _unified_add_client(
            api,
            email=email,
            sub_id=resolved_sub_id,
            expiry_time=expiry_time,
            total_gb=total_gb,
            inbound_ids=inbound_ids,
            limit_ip=limit_ip,
        )

    try:
        await _add()
    except ValueError as e:
        if "duplicate email" not in str(e).lower():
            raise
        logger.warning(
            "Дубликат {} на основной — локальная очистка и повторный add",
            email,
        )
        await _delete_client_by_email(api, email)
        await asyncio.sleep(0.5)
        await _add()

    sub_link = await build_sub_link(resolved_sub_id)
    return email, resolved_sub_id, sub_link


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

    from services.limit_ip import resolve_limit_ip_for_email

    limit_ip = await resolve_limit_ip_for_email(email)
    logger.info("Продление {}: expiry {} ms", email, new_expiry)
    await _set_client_expiry_on_panel(api, email, new_expiry, sub_id, limit_ip=limit_ip)
    return new_expiry


async def _list_unified_clients_emails_on_panel(api: AsyncApi) -> set[str]:
    """tg/tgfree через GET clients/list — fallback без inbounds/settings."""
    url = api.client._url("panel/api/clients/list")
    await _throttle()
    try:
        resp = await api.client._get(url, {"Accept": "application/json"})
        data = resp.json()
        if not data.get(ApiFields.SUCCESS, True):
            logger.debug("clients/list: {}", data.get(ApiFields.MSG) or "not success")
            return set()
        obj = data.get(ApiFields.OBJ) or []
    except Exception as e:
        if not _is_not_found_error(e):
            logger.warning("clients/list: {}", e)
        return set()

    emails: set[str] = set()
    if not isinstance(obj, list):
        return emails
    for item in obj:
        if isinstance(item, str):
            email = item.strip()
        elif isinstance(item, dict):
            email = (item.get("email") or "").strip()
        else:
            continue
        if is_bot_client_email(email):
            emails.add(email.lower())
    return emails


async def _list_bot_group_emails_on_panel(api: AsyncApi) -> set[str]:
    """tg/tgfree из unified store (группа бота) — дополняет settings на child-нодах."""
    group = _bot_group()
    if not group:
        return set()
    url = api.client._url(f"panel/api/clients/groups/{group}/emails")
    await _throttle()
    try:
        resp = await api.client._get(url, {"Accept": "application/json"})
        data = resp.json()
        if not data.get(ApiFields.SUCCESS):
            logger.debug(
                "groups/{}/emails: {}",
                group, data.get(ApiFields.MSG) or "not success",
            )
            return set()
        obj = data.get(ApiFields.OBJ) or []
    except Exception as e:
        if not _is_not_found_error(e):
            logger.warning("groups/{}/emails: {}", group, e)
        return set()

    emails: set[str] = set()
    if not isinstance(obj, list):
        return emails
    for item in obj:
        if isinstance(item, str):
            email = item.strip()
        elif isinstance(item, dict):
            email = (item.get("email") or "").strip()
        else:
            continue
        if is_bot_client_email(email):
            emails.add(email.lower())
    return emails


async def list_bot_client_emails_on_panel(api: AsyncApi, *, force: bool = False) -> set[str]:
    """Все tg/tgfree: settings ∪ groups/emails ∪ clients/list (fallback)."""
    from services.panel_cache import get_cached_bot_emails, store_cached_bot_emails

    if not force:
        cached = get_cached_bot_emails(api)
        if cached is not None:
            return cached

    emails: set[str] = set()
    cache = get_panel_cache(api)
    inbounds = await cache.refresh(api, force=force)
    for inbound in inbounds:
        for client in inbound.settings.clients or []:
            email = (client.email or "").strip()
            if is_bot_client_email(email):
                emails.add(email.lower())
    emails.update(await _list_bot_group_emails_on_panel(api))
    if not emails:
        emails.update(await _list_unified_clients_emails_on_panel(api))
    store_cached_bot_emails(api, emails)
    return emails


async def remove_bot_client_on_panel(api: AsyncApi, email: str) -> list[int]:
    """Удалить tg-клиента с панели (unified del + settings purge)."""
    return await _remove_client_on_node(api, email, inbound_ids=None)


async def _remove_client_on_node(
    api: AsyncApi,
    email: str,
    *,
    inbound_ids: list[int] | None = None,
) -> list[int]:
    """Удаление на ноде: только если клиент найден (unified del + settings purge)."""
    if not await _is_client_present_on_panel(api, email):
        return []
    return await _purge_client_from_panel(api, email, inbound_ids=inbound_ids)


async def _remove_client_on_panel(api: AsyncApi, email: str) -> list[int]:
    if not await _is_client_present_on_panel(api, email):
        return []
    located = await _locate_client_inbounds(api, email, force=False)
    removed = set(located.keys())
    purged = await _purge_client_from_panel(api, email)
    removed.update(purged)
    await panel_cache.refresh(api, force=True)
    return sorted(removed)


async def remove_client_from_secondaries(
    email: str,
    *,
    skip_hosts: set[str] | None = None,
) -> list[int]:
    """Удаление tg-клиента только на вторичных нодах (без дублей host)."""
    from db.xui_nodes import get_secondary_nodes

    _assert_bot_client_email(email)
    try:
        nodes = _dedupe_nodes_by_host(
            await get_secondary_nodes(healthy_only=False),
        )
    except Exception:
        nodes = []

    skip = {h.lower() for h in (skip_hosts or set())}
    all_removed: list[int] = []
    for node in nodes:
        if not node.get("is_enabled", True):
            continue
        host_key = _node_host_key(node)
        if host_key in skip:
            continue
        try:
            api = await get_api_for_node(node)
            removed = await _remove_client_on_node(api, email, inbound_ids=None)
            all_removed.extend(removed)
            logger.info(
                "Removed {} from secondary {} ({}) inbounds {}",
                email, node.get("name"), node.get("id"), removed,
            )
        except Exception as e:
            logger.error(
                "Remove {} on secondary node {} failed: {}",
                email, node.get("id"), e,
            )
    return sorted(set(all_removed))


async def remove_client_everywhere(email: str) -> list[int]:
    """Полное удаление tg-клиента на всех нодах без следов."""
    return await ensure_client_absent_everywhere(email)


async def disable_client(email: str, inbound_id: Optional[int] = None):
    _assert_bot_client_email(email)
    try:
        from db.xui_nodes import list_nodes
        nodes = _dedupe_nodes_by_host(await list_nodes(enabled_only=True))
    except Exception:
        nodes = []
    if not nodes:
        nodes = [{"id": 0, "host": settings.XUI_HOST}]
    for node in nodes:
        try:
            api = await get_api_for_node(node) if node.get("host") else await get_api()
            info = await _unified_get_client_info(api, email)
            if not info:
                continue
            client, _, _ = info
            if client.enable:
                await _unified_update_client(api, client, enable=False)
                logger.info("Disabled client {} on node {}", email, node.get("id"))
        except Exception as e:
            logger.error("Failed to disable {} on node {}: {}", email, node.get("id"), e)


def sub_desired_state_from_db(sub: dict) -> dict:
    end = datetime.fromisoformat(str(sub["end_date"]).replace("Z", ""))
    now = datetime.utcnow()
    traffic_gb = int(sub.get("traffic_limit_gb") or 0)
    total_gb = traffic_gb * 1024 * 1024 * 1024 if traffic_gb > 0 else 0
    return {
        "sub_id": sub.get("sub_id") or "",
        "expiry_ms": int(end.timestamp() * 1000),
        "total_gb": total_gb,
        "enable": bool(sub.get("is_active")) and end > now,
    }


def _client_needs_replica_update(
    client: Client,
    *,
    expiry_ms: int,
    total_gb: int,
    sub_id: str,
    enable: bool,
) -> bool:
    if client.enable != enable:
        return True
    if abs((client.total_gb or 0) - total_gb) > 1024:
        return True
    if _client_needs_update(client, expiry_time=expiry_ms, sub_id=sub_id, enable=enable):
        return True
    return False


async def sync_client_state_on_node(
    api: AsyncApi,
    *,
    node: dict,
    email: str,
    sub_id: str,
    expiry_ms: int,
    total_gb: int,
    enable: bool,
) -> str:
    """
    Вторичная нода: только синхронизация существующего клиента.
    Создание — только на основной (inboundIds из админки); на ноды уходит через панель.
    """
    _assert_bot_client_email(email)
    info = await _unified_get_client_info(api, email)
    if info is None:
        logger.debug(
            "Клиент {} отсутствует на вторичной {} — пропуск (ожидается sync с основной)",
            email, node.get("name"),
        )
        return "missing"

    client, _, _ = info
    if not _client_needs_replica_update(
        client,
        expiry_ms=expiry_ms,
        total_gb=total_gb,
        sub_id=sub_id,
        enable=enable,
    ):
        return "skipped"

    await _unified_update_client(
        api,
        client,
        expiryTime=expiry_ms,
        totalGB=total_gb,
        subId=sub_id or client.sub_id or "",
        enable=enable,
    )
    return "updated"


# обратная совместимость для импортов
replicate_client_on_node = sync_client_state_on_node