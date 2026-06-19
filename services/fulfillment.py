"""Общая логика выдачи и продления подписки (тест, webhook, ручная проверка)."""
import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import qrcode
from aiogram.types import BufferedInputFile, FSInputFile
from loguru import logger

from services.fulfillment_text import (
    panel_sync_notice_text,
    sub_link_caption_lines,
    sub_link_standalone_message,
)
from services.limit_ip import format_connections_limit_line, get_paid_limit_ip
from services.subscription_labels import subscription_display_name
from config.plans import Plan, get_plan
from db import database as db
from db.bot_settings import get_subscription_inbound_count
from services.xui import (
    provision_client,
    extend_client,
    build_sub_link,
    get_unified_panel_client,
)

from services.pricing import apply_promo_on_paid_order
from services.node_sync import schedule_secondary_sync

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SETUP_ASSETS_DIR = _PROJECT_ROOT / "assets" / "setup"


@dataclass
class FulfillmentResult:
    text: str
    photo: Optional[BufferedInputFile] = None
    link_message: Optional[str] = None
    setup_text: Optional[str] = None
    setup_photos: List[FSInputFile] = field(default_factory=list)


async def fulfill_paid_order(order: dict) -> FulfillmentResult:
    """Обрабатывает оплаченный заказ: создаёт или продлевает подписку."""
    await apply_promo_on_paid_order(order)
    plan = get_plan(order["plan_id"])
    if not plan:
        raise ValueError(f"План {order['plan_id']} не найден")

    is_test = order["platega_tx_id"].startswith("test-")
    return await fulfill_plan_for_tg(
        order["tg_id"],
        plan,
        order_id=order.get("id"),
        order_type=order.get("order_type") or "new",
        subscription_id=order.get("subscription_id"),
        sub_display_name=order.get("sub_display_name"),
        is_test=is_test,
        title_new="Оплата прошла успешно!",
        log_context=f"Order {order['id']}",
    )


async def fulfill_plan_for_tg(
    tg_id: int,
    plan: Plan,
    *,
    order_id: Optional[int] = None,
    order_type: str = "new",
    subscription_id: Optional[int] = None,
    sub_display_name: Optional[str] = None,
    is_test: bool = False,
    title_new: str = "Оплата прошла успешно!",
    title_extend: str = "Подписка продлена!",
    log_context: str = "",
) -> FulfillmentResult:
    if order_type == "extend":
        return await _fulfill_extend(
            tg_id,
            plan,
            order_id=order_id,
            subscription_id=subscription_id,
            is_test=is_test,
            title=title_extend,
            log_context=log_context,
        )
    return await _fulfill_new(
        tg_id,
        plan,
        order_id=order_id,
        sub_display_name=sub_display_name,
        is_test=is_test,
        title=title_new,
        log_context=log_context,
    )


async def _fulfill_extend(
    tg_id: int,
    plan: Plan,
    *,
    order_id: Optional[int],
    subscription_id: Optional[int],
    is_test: bool,
    title: str,
    log_context: str,
) -> FulfillmentResult:
    target_sub = None
    if subscription_id:
        target_sub = await db.get_subscription_by_id(subscription_id)
        if target_sub and target_sub["tg_id"] != tg_id:
            target_sub = None
    if not target_sub:
        target_sub = await db.get_primary_paid_subscription(tg_id)
    if not target_sub:
        raise ValueError("Нет подписки для продления")

    new_end_iso = await db.extend_subscription_record(target_sub["id"], plan["days"])
    new_expiry_ms = int(
        datetime.fromisoformat(new_end_iso.replace("Z", "")).timestamp() * 1000
    )
    email = target_sub["client_email"]
    panel_client = await get_unified_panel_client(email)
    if panel_client:
        await extend_client(
            email,
            plan["days"],
            target_expiry_ms=new_expiry_ms,
        )
    else:
        logger.warning(
            "Клиент {} есть в БД, но отсутствует на панели — clients/add",
            email,
        )
        await provision_client(
            tg_id=tg_id,
            plan_days=plan["days"],
            traffic_gb=plan["traffic_gb"],
            sub_id=target_sub.get("sub_id"),
            target_expiry_ms=new_expiry_ms,
            client_email=email,
        )
    sub = await db.get_subscription_by_id(target_sub["id"])
    sub_link = await build_sub_link(sub["sub_id"]) if sub.get("sub_id") else None
    schedule_secondary_sync(target_sub["id"])
    inbound_count = await get_subscription_inbound_count()
    limit_ip = await get_paid_limit_ip()
    text = _success_text(
        title=title,
        plan=plan,
        end_date=new_end_iso[:10],
        sub_link=sub_link,
        client_email=email,
        display_name=subscription_display_name(sub),
        is_test=is_test,
        inbound_count=inbound_count,
        limit_ip=limit_ip,
    )
    photo = make_qr_photo(sub_link or email, "vpn_extend.png")
    if log_context:
        logger.success("{} extended sub #{} for tg_id={}", log_context, target_sub["id"], tg_id)
    return FulfillmentResult(
        text=text,
        photo=photo,
        link_message=sub_link_standalone_message(sub_link),
    )


async def _fulfill_new(
    tg_id: int,
    plan: Plan,
    *,
    order_id: Optional[int],
    sub_display_name: Optional[str],
    is_test: bool,
    title: str,
    log_context: str,
) -> FulfillmentResult:
    email = await db.allocate_client_email(tg_id)
    email, sub_id, sub_link = await provision_client(
        tg_id=tg_id,
        plan_days=plan["days"],
        traffic_gb=plan["traffic_gb"],
        client_email=email,
    )
    display_name = (sub_display_name or "").strip() or await db.suggest_subscription_display_name(tg_id)
    end_date = (datetime.utcnow() + timedelta(days=plan["days"])).strftime("%Y-%m-%d")
    sub_db_id = await db.create_subscription(
        tg_id=tg_id,
        order_id=order_id,
        inbound_id=0,
        client_email=email,
        client_uuid=sub_id,
        sub_id=sub_id,
        days=plan["days"],
        traffic_gb=plan["traffic_gb"],
        display_name=display_name,
    )
    schedule_secondary_sync(sub_db_id)
    inbound_count = await get_subscription_inbound_count()
    limit_ip = await get_paid_limit_ip()
    text = _success_text(
        title=title,
        plan=plan,
        end_date=end_date,
        sub_link=sub_link,
        client_email=email,
        display_name=display_name,
        is_test=is_test,
        inbound_count=inbound_count,
        limit_ip=limit_ip,
    )
    photo = make_qr_photo(sub_link or email, "vpn.png")
    if log_context:
        logger.success("{} created sub #{} for tg_id={}", log_context, sub_db_id, tg_id)
    return FulfillmentResult(
        text=text,
        photo=photo,
        link_message=sub_link_standalone_message(sub_link),
    )


def _success_text(
    *,
    title: str,
    plan: Plan,
    end_date: str,
    sub_link: Optional[str],
    client_email: str,
    display_name: str,
    is_test: bool,
    inbound_count: int,
    limit_ip: int,
) -> str:
    from ui.theme import screen, traffic_label

    details = [
        f"📱 Подписка: <b>{display_name}</b>",
        f"📦 Тариф: <b>{plan['name']}</b>",
        f"📅 Действует до: <b>{end_date}</b>",
        f"📊 Трафик: {traffic_label(plan['traffic_gb'])}",
        format_connections_limit_line(limit_ip),
    ]
    details += sub_link_caption_lines(sub_link)
    details.append(f"👤 Клиент: <code>{client_email}</code>")
    details.append(panel_sync_notice_text(inbound_count))
    footer = "⚠️ <i>Тестовый режим — оплата симулирована</i>" if is_test else None
    return screen(f"✅ <b>{title}</b>", "\n".join(details), footer=footer)


def load_happ_setup_photos() -> List[FSInputFile]:
    """Скриншоты Happ из assets/setup/import_* и happ*."""
    if not _SETUP_ASSETS_DIR.is_dir():
        return []
    paths: list[Path] = []
    for pattern in (
        "import_*.png", "import_*.jpg", "import_*.jpeg", "import_*.webp",
        "happ*.png", "happ*.jpg", "happ*.jpeg", "happ*.webp",
    ):
        paths.extend(_SETUP_ASSETS_DIR.glob(pattern))
    paths = sorted({p.resolve() for p in paths if p.is_file()})
    return [FSInputFile(path) for path in paths]


def make_qr_photo(qr_text: str, filename: str) -> BufferedInputFile:
    qr_img = qrcode.make(qr_text)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    buf.seek(0)
    return BufferedInputFile(buf.read(), filename=filename)