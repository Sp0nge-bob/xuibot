"""Общая логика выдачи и продления подписки (тест, webhook, ручная проверка)."""
import io
from datetime import datetime, timedelta
from typing import Optional, Tuple

import qrcode
from aiogram.types import BufferedInputFile
from loguru import logger

from config.plans import Plan, get_plan
from config.trial import is_trial_email
from db import database as db
from services.xui import (
    provision_client,
    extend_client,
    build_sub_link,
    get_unified_panel_client,
)

from services.pricing import apply_promo_on_paid_order
from services.node_sync import schedule_secondary_sync


async def fulfill_paid_order(order: dict) -> Tuple[str, Optional[BufferedInputFile]]:
    """
    Обрабатывает оплаченный заказ: создаёт или продлевает подписку.
    Возвращает (текст сообщения, QR-фото или None).
    """
    await apply_promo_on_paid_order(order)
    plan = get_plan(order["plan_id"])
    if not plan:
        raise ValueError(f"План {order['plan_id']} не найден")

    tg_id = order["tg_id"]
    order_type = order.get("order_type") or "new"
    is_test = order["platega_tx_id"].startswith("test-")
    existing_sub = await db.get_primary_subscription(tg_id)
    if existing_sub and is_trial_email(existing_sub.get("client_email")):
        existing_sub = None

    # Повторная покупка при активной подписке = продление
    if order_type == "extend" or existing_sub:
        if existing_sub:
            # Сначала продлеваем в БД (надёжный источник даты), затем пушим на панель
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
            title = "Подписка продлена!"
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
                order_id=order["id"],
                inbound_id=0,
                client_email=email,
                client_uuid=sub_id,
                sub_id=sub_id,
                days=plan["days"],
                traffic_gb=plan["traffic_gb"],
            )
            schedule_secondary_sync(sub_db_id)
            title = "Подписка продлена!"

        text = _success_text(
            title=title,
            plan=plan,
            end_date=end_date,
            sub_link=sub_link,
            client_email=email,
            is_test=is_test,
        )
        photo = make_qr_photo(sub_link or email, "vpn_extend.png")
        logger.success("Order {} extended for tg_id={}", order["id"], tg_id)
        return text, photo

    email, sub_id, sub_link = await provision_client(
        tg_id=tg_id,
        plan_days=plan["days"],
        traffic_gb=plan["traffic_gb"],
    )

    end_date = (datetime.utcnow() + timedelta(days=plan["days"])).strftime("%Y-%m-%d")
    sub_db_id = await db.create_subscription(
        tg_id=tg_id,
        order_id=order["id"],
        inbound_id=0,
        client_email=email,
        client_uuid=sub_id,
        sub_id=sub_id,
        days=plan["days"],
        traffic_gb=plan["traffic_gb"],
    )
    schedule_secondary_sync(sub_db_id)
    text = _success_text(
        title="Оплата прошла успешно!",
        plan=plan,
        end_date=end_date,
        sub_link=sub_link,
        client_email=email,
        is_test=is_test,
    )
    photo = make_qr_photo(sub_link or email, "vpn.png")
    logger.success("Order {} fulfilled for tg_id={}", order["id"], tg_id)
    return text, photo


def _success_text(
    *,
    title: str,
    plan: Plan,
    end_date: str,
    sub_link: Optional[str],
    client_email: str,
    is_test: bool,
) -> str:
    traffic = "безлимит" if plan["traffic_gb"] == 0 else f"{plan['traffic_gb']} ГБ"
    lines = [
        f"✅ <b>{title}</b>",
        "",
        f"📦 Тариф: <b>{plan['name']}</b>",
        f"📅 Действует до: <b>{end_date}</b>",
        f"📊 Трафик: {traffic}",
        "",
    ]
    if sub_link:
        lines += [f"🔗 <b>Ссылка на подписку:</b>", f"<code>{sub_link}</code>", ""]
    lines.append(f"👤 Клиент: <code>{client_email}</code>")
    if is_test:
        lines += ["", "⚠️ <i>Тестовый режим — оплата симулирована</i>"]
    else:
        lines += ["", "Скопируйте ссылку или отсканируйте QR-код ниже."]
    return "\n".join(lines)


def make_qr_photo(qr_text: str, filename: str) -> BufferedInputFile:
    qr_img = qrcode.make(qr_text)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    buf.seek(0)
    return BufferedInputFile(buf.read(), filename=filename)