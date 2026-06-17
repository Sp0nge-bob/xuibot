"""Общая логика выдачи и продления подписки (тест, webhook, ручная проверка)."""
import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import qrcode
from aiogram.types import BufferedInputFile, FSInputFile
from loguru import logger

from services.fulfillment_text import happ_setup_text, qr_and_sync_footer
from config.plans import Plan, get_plan
from config.trial import is_trial_email
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
    is_test: bool = False,
    title_new: str = "Оплата прошла успешно!",
    title_extend: str = "Подписка продлена!",
    log_context: str = "",
) -> FulfillmentResult:
    existing_sub = await db.get_primary_subscription(tg_id)
    if existing_sub and is_trial_email(existing_sub.get("client_email")):
        existing_sub = None

    if order_type == "extend" or existing_sub:
        if existing_sub:
            new_end_iso = await db.extend_subscription_record(
                existing_sub["id"], plan["days"],
            )
            new_expiry_ms = int(
                datetime.fromisoformat(new_end_iso.replace("Z", "")).timestamp() * 1000
            )
            email = existing_sub["client_email"]
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
                    sub_id=existing_sub.get("sub_id"),
                    target_expiry_ms=new_expiry_ms,
                )
            sub = await db.get_subscription_by_id(existing_sub["id"])
            sub_link = (
                await build_sub_link(sub["sub_id"]) if sub.get("sub_id") else None
            )
            schedule_secondary_sync(existing_sub["id"])
            title = title_extend
            end_date = new_end_iso[:10]
        else:
            email, sub_id, sub_link = await provision_client(
                tg_id=tg_id,
                plan_days=plan["days"],
                traffic_gb=plan["traffic_gb"],
            )
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
            )
            schedule_secondary_sync(sub_db_id)
            title = title_extend

        inbound_count = await get_subscription_inbound_count()
        text = _success_text(
            title=title,
            plan=plan,
            end_date=end_date,
            sub_link=sub_link,
            client_email=email,
            is_test=is_test,
            inbound_count=inbound_count,
        )
        photo = make_qr_photo(sub_link or email, "vpn_extend.png")
        if log_context:
            logger.success("{} extended for tg_id={}", log_context, tg_id)
        return FulfillmentResult(text=text, photo=photo)

    last_paid = await db.get_last_paid_subscription(tg_id)
    email, sub_id, sub_link = await provision_client(
        tg_id=tg_id,
        plan_days=plan["days"],
        traffic_gb=plan["traffic_gb"],
        sub_id=last_paid.get("sub_id") if last_paid else None,
        client_email=last_paid.get("client_email") if last_paid else None,
    )

    if (
        last_paid
        and last_paid.get("client_email") == email
        and not last_paid.get("is_active")
    ):
        end_iso = await db.reactivate_subscription_record(
            last_paid["id"],
            plan["days"],
            order_id=order_id,
        )
        end_date = end_iso[:10]
        sub_db_id = last_paid["id"]
    else:
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
        )
    schedule_secondary_sync(sub_db_id)
    inbound_count = await get_subscription_inbound_count()
    text = _success_text(
        title=title_new,
        plan=plan,
        end_date=end_date,
        sub_link=sub_link,
        client_email=email,
        is_test=is_test,
        inbound_count=inbound_count,
    )
    photo = make_qr_photo(sub_link or email, "vpn.png")
    setup_photos = load_happ_setup_photos()
    setup_text = happ_setup_text()
    if log_context:
        logger.success("{} fulfilled for tg_id={}", log_context, tg_id)
    return FulfillmentResult(
        text=text,
        photo=photo,
        setup_text=setup_text,
        setup_photos=setup_photos,
    )


def _success_text(
    *,
    title: str,
    plan: Plan,
    end_date: str,
    sub_link: Optional[str],
    client_email: str,
    is_test: bool,
    inbound_count: int,
) -> str:
    from ui.theme import screen, traffic_label

    details = [
        f"📦 Тариф: <b>{plan['name']}</b>",
        f"📅 Действует до: <b>{end_date}</b>",
        f"📊 Трафик: {traffic_label(plan['traffic_gb'])}",
    ]
    if sub_link:
        details += ["", "🔗 <b>Ссылка на подписку:</b>", f"<code>{sub_link}</code>"]
    details.append(f"👤 Клиент: <code>{client_email}</code>")
    footer = "⚠️ <i>Тестовый режим — оплата симулирована</i>" if is_test else None
    text = screen(f"✅ <b>{title}</b>", "\n".join(details), footer=footer)
    return text + qr_and_sync_footer(inbound_count)


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