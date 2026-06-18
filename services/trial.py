"""Выдача и админский сброс пробной подписки."""
from datetime import datetime, timedelta

from loguru import logger

from config.trial import (
    TRIAL_COOLDOWN_DAYS,
    TRIAL_DAYS,
    TRIAL_TRAFFIC_GB,
    trial_client_email,
)
from db import database as db
from db import trial_grants as trial_db
from db.bot_settings import get_subscription_inbound_count
from services.fulfillment import (
    FulfillmentResult,
    load_happ_setup_photos,
    make_qr_photo,
)
from services.fulfillment_text import (
    happ_setup_text,
    qr_and_sync_footer,
    sub_link_caption_lines,
    sub_link_standalone_message,
)
from services.limit_ip import format_connections_limit_line, get_trial_limit_ip
from services.node_sync import schedule_secondary_sync
from services.subscription_admin import admin_reset_all_trials, admin_reset_trial_for_user
from services.xui import provision_client


async def get_trial_button_visible(tg_id: int) -> bool:
    ok, _ = await trial_db.can_claim_trial(tg_id)
    return ok


async def claim_trial(tg_id: int) -> FulfillmentResult:
    ok, reason = await trial_db.can_claim_trial(tg_id)
    if not ok:
        raise ValueError(reason)

    email = trial_client_email(tg_id)
    email, sub_id, sub_link = await provision_client(
        tg_id=tg_id,
        plan_days=TRIAL_DAYS,
        traffic_gb=TRIAL_TRAFFIC_GB,
        client_email=email,
    )

    sub_db_id = await db.create_subscription(
        tg_id=tg_id,
        order_id=None,
        inbound_id=0,
        client_email=email,
        client_uuid=sub_id,
        sub_id=sub_id,
        days=TRIAL_DAYS,
        traffic_gb=TRIAL_TRAFFIC_GB,
    )
    await trial_db.record_trial_grant(tg_id, sub_db_id)
    schedule_secondary_sync(sub_db_id)

    inbound_count = await get_subscription_inbound_count()
    limit_ip = await get_trial_limit_ip()
    end_date = (datetime.utcnow() + timedelta(days=TRIAL_DAYS)).strftime("%d.%m.%Y")
    lines = [
        "✅ <b>Пробный период активирован!</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"⏱ Срок: <b>{TRIAL_DAYS} дн.</b> (до {end_date})",
        f"📊 Трафик: <b>{TRIAL_TRAFFIC_GB} ГБ</b>",
        format_connections_limit_line(limit_ip),
        "",
    ]
    lines += sub_link_caption_lines(sub_link)
    if sub_link:
        lines.append("")
    lines += [
        f"👤 Клиент: <code>{email}</code>",
        qr_and_sync_footer(inbound_count),
        "",
        f"<i>Повторно — не раньше чем через {TRIAL_COOLDOWN_DAYS} дн.</i>",
    ]

    photo = make_qr_photo(sub_link or email, "trial_vpn.png")
    logger.info("Trial granted for tg_id={} sub_id={}", tg_id, sub_db_id)
    return FulfillmentResult(
        text="\n".join(lines),
        photo=photo,
        link_message=sub_link_standalone_message(sub_link),
        setup_text=happ_setup_text(),
        setup_photos=load_happ_setup_photos(),
    )


async def admin_reset_trial(tg_id: int) -> dict:
    return await admin_reset_trial_for_user(tg_id)


async def admin_reset_all_trial_subscriptions() -> dict:
    return await admin_reset_all_trials()