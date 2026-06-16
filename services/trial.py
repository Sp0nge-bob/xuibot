"""Выдача и админский сброс пробной подписки."""
from datetime import datetime, timedelta
from typing import Optional, Tuple

from aiogram.types import BufferedInputFile
from loguru import logger

from config.trial import (
    TRIAL_COOLDOWN_DAYS,
    TRIAL_DAYS,
    TRIAL_TRAFFIC_GB,
    trial_client_email,
)
from db import database as db
from db import trial_grants as trial_db
from services.fulfillment import make_qr_photo
from services.subscription_admin import admin_reset_trial_for_user
from services.xui import provision_client


async def get_trial_button_visible(tg_id: int) -> bool:
    ok, _ = await trial_db.can_claim_trial(tg_id)
    return ok


async def claim_trial(tg_id: int) -> Tuple[str, Optional[BufferedInputFile]]:
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

    end_date = (datetime.utcnow() + timedelta(days=TRIAL_DAYS)).strftime("%d.%m.%Y")
    lines = [
        "✅ <b>Пробный период активирован!</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"⏱ Срок: <b>{TRIAL_DAYS} дн.</b> (до {end_date})",
        f"📊 Трафик: <b>{TRIAL_TRAFFIC_GB} ГБ</b>",
        "",
    ]
    if sub_link:
        lines += [f"🔗 <b>Ссылка:</b>", f"<code>{sub_link}</code>", ""]
    lines += [
        f"👤 Клиент: <code>{email}</code>",
        "",
        "Скопируйте ссылку или отсканируйте QR-код ниже.",
        f"<i>Повторно — не раньше чем через {TRIAL_COOLDOWN_DAYS} дн.</i>",
    ]

    photo = make_qr_photo(sub_link or email, "trial_vpn.png")
    logger.info("Trial granted for tg_id={} sub_id={}", tg_id, sub_db_id)
    return "\n".join(lines), photo


async def admin_reset_trial(tg_id: int) -> dict:
    return await admin_reset_trial_for_user(tg_id)