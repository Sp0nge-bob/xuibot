"""Таймер и данные экрана ожидания оплаты (PENDING)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from services.test_mode import is_test_mode
from services import platega_simulator as platega_sim
from services.platega import parse_status_response
from services.platega_client import get_transaction_status

PAYMENT_WINDOW_MINUTES = 30


def format_expires_in(total_seconds: int) -> str:
    if total_seconds <= 0:
        return "00:00:00"
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def expires_in_from_order_created(created_at: str | None) -> str | None:
    """Оставшееся время от created_at + 30 мин (fallback)."""
    if not created_at:
        return None
    try:
        created = datetime.fromisoformat(str(created_at).replace("Z", ""))
    except ValueError:
        return None
    deadline = created + timedelta(minutes=PAYMENT_WINDOW_MINUTES)
    left = int((deadline - datetime.utcnow()).total_seconds())
    return format_expires_in(left)


def _parse_platega_expires_in(raw: str | None) -> str | None:
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    parts = text.split(":")
    try:
        if len(parts) == 3:
            h, m, s = (int(p) for p in parts)
            return format_expires_in(h * 3600 + m * 60 + s)
        if len(parts) == 2:
            m, s = (int(p) for p in parts)
            return format_expires_in(m * 60 + s)
    except ValueError:
        pass
    return text


async def fetch_pending_expires_in(tx_id: str, order: dict[str, Any]) -> str | None:
    """Актуальный таймер: Platega API → fallback 30 мин от создания заказа."""
    is_test = await is_test_mode() and tx_id.startswith("test-")
    if is_test:
        try:
            sim = platega_sim.simulate_get_status(tx_id)
            parsed = _parse_platega_expires_in(sim.get("expiresIn"))
            if parsed:
                return parsed
        except KeyError:
            pass
        return expires_in_from_order_created(order.get("created_at"))

    try:
        data = await get_transaction_status(tx_id)
        parsed = parse_status_response(data)
        platega_ttl = _parse_platega_expires_in(parsed.get("expires_in"))
        if platega_ttl:
            return platega_ttl
    except Exception:
        pass
    return expires_in_from_order_created(order.get("created_at"))


def is_payment_window_expired(expires_in: str | None) -> bool:
    return expires_in == "00:00:00"


async def get_resumable_pending_order(tg_id: int) -> dict[str, Any] | None:
    """Активный pending-заказ, к которому можно вернуться с главного меню."""
    from config.plans import get_plan
    from db import database as db

    order = await db.get_pending_order(tg_id)
    if not order:
        return None
    if not get_plan(order.get("plan_id") or ""):
        return None
    tx_id = (order.get("platega_tx_id") or "").strip()
    if not tx_id:
        return None
    redirect = (order.get("payment_redirect") or "").strip()
    is_test = await is_test_mode() and tx_id.startswith("test-")
    if not redirect and not is_test:
        return None
    expires_in = expires_in_from_order_created(order.get("created_at"))
    if is_payment_window_expired(expires_in):
        return None
    return order